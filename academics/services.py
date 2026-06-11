"""Registrar services. Registration, grading, degree audit, and the
graduation clearance cycle all live here so every entry point (views,
change-request approvals, seeds, tests) shares one rulebook."""

from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from core import audit, permissions
from core.models import Affiliation, Department
from workflow.models import Task
from workflow.services import create_task, notify_department, require_no_blocks

from .grades import GRADE_POINTS, NON_GPA_GRADES, PASSING
from .models import (ClearanceItem, Enrollment, GraduationApplication,
                     Section, StudentProgram)


def _times_overlap(a, b):
    if not (a.days and b.days and a.start_time and b.start_time):
        return False
    shared_days = set(a.days) & set(b.days)
    return bool(shared_days) and a.start_time < b.end_time and b.start_time < a.end_time


@transaction.atomic
def register(person, section, actor):
    """All registration guards in one place; raises BlockedByHold or
    ValidationError with a human explanation."""
    section = Section.objects.select_for_update().select_related("term", "course").get(pk=section.pk)
    require_no_blocks(person, "registration")
    term = section.term
    today = timezone.localdate()
    if not (term.registration_opens <= today <= term.registration_closes):
        raise ValidationError(f"Registration for {term.name} is not open.")
    if section.status != Section.OPEN:
        raise ValidationError("This section is not open for registration.")
    if section.seats_taken >= section.capacity:
        raise ValidationError(f"{section} is full ({section.capacity} seats).")
    if Enrollment.objects.filter(
        person=person, section__term=term, section__course=section.course,
        status=Enrollment.REGISTERED,
    ).exists():
        raise ValidationError(f"Already registered for {section.course.code} this term.")
    for existing in Enrollment.objects.filter(
        person=person, section__term=term, status=Enrollment.REGISTERED
    ).select_related("section"):
        if _times_overlap(existing.section, section):
            raise ValidationError(
                f"Time conflict with {existing.section} ({existing.section.schedule_display})."
            )

    enrollment = Enrollment.objects.filter(person=person, section=section).first()
    if enrollment:
        enrollment.status = Enrollment.REGISTERED
        enrollment.dropped_at = None
        enrollment.save()
    else:
        enrollment = Enrollment.objects.create(person=person, section=section)
    return enrollment


def drop(enrollment, actor):
    if enrollment.status != Enrollment.REGISTERED:
        raise ValidationError("Only registered enrollments can be dropped.")
    enrollment.status = Enrollment.DROPPED
    enrollment.dropped_at = timezone.now()
    enrollment.save()
    return enrollment


def can_grade(user, section):
    """REG owns grades; instructors own their own sections."""
    if permissions.can_edit_domain(user, "ACADEMIC"):
        return True
    person = getattr(user, "person", None)
    return person is not None and section.instructor_id == person.pk


def apply_grade_fields(enrollment, actor=None):
    """Derive grade_points/status from the letter grade. Also runs as the
    post-apply hook when a grade change-request is approved."""
    grade = enrollment.grade
    if not grade:
        return enrollment
    enrollment.grade_points = GRADE_POINTS.get(grade)
    if grade == "W":
        enrollment.status = Enrollment.WITHDRAWN
    else:
        enrollment.status = Enrollment.COMPLETED
    enrollment.graded_by = actor
    enrollment.graded_at = timezone.now()
    enrollment.save()
    return enrollment


def enter_grade(enrollment, grade, actor):
    if not can_grade(actor, enrollment.section):
        raise PermissionDenied("Only the Registrar or the section instructor can enter grades.")
    if grade not in GRADE_POINTS and grade not in NON_GPA_GRADES:
        raise ValidationError(f"'{grade}' is not a valid grade.")
    enrollment.grade = grade
    return apply_grade_fields(enrollment, actor)


def gpa(person, term=None):
    qs = Enrollment.objects.filter(
        person=person, status=Enrollment.COMPLETED, grade_points__isnull=False
    ).select_related("section__course")
    if term:
        qs = qs.filter(section__term=term)
    points = credits = Decimal("0")
    for e in qs:
        c = e.section.course.credits
        credits += c
        points += e.grade_points * c
    return (points / credits).quantize(Decimal("0.01")) if credits else None


def completed_credits(person):
    total = Decimal("0")
    for e in Enrollment.objects.filter(
        person=person, status=Enrollment.COMPLETED
    ).select_related("section__course"):
        if e.grade in PASSING:
            total += e.section.course.credits
    return total


def degree_audit(student_program):
    """Greedy bucket-fill of passed credits into requirement categories.
    Returns {categories: [...], total_required, total_earned, satisfied}."""
    person = student_program.person
    program = student_program.program
    passed = [
        e for e in Enrollment.objects.filter(
            person=person, status=Enrollment.COMPLETED
        ).select_related("section__course")
        if e.grade in PASSING
    ]
    unused = {e.pk: e for e in passed}
    categories = []
    requirements = list(program.requirements.prefetch_related("applicable_courses"))
    # Specific-course buckets claim courses before open electives do.
    for req in sorted(requirements, key=lambda r: (r.applicable_courses.exists() is False, r.order)):
        allowed = set(req.applicable_courses.values_list("pk", flat=True))
        earned = Decimal("0")
        used_courses = []
        for pk, e in list(unused.items()):
            if earned >= req.credits_required:
                break
            if allowed and e.section.course_id not in allowed:
                continue
            earned += e.section.course.credits
            used_courses.append(e.section.course.code)
            del unused[pk]
        categories.append({
            "requirement": req,
            "category": req.category,
            "required": req.credits_required,
            "earned": min(earned, req.credits_required),
            "satisfied": earned >= req.credits_required,
            "courses": used_courses,
        })
    categories.sort(key=lambda c: c["requirement"].order)
    total_earned = completed_credits(person)
    return {
        "categories": categories,
        "total_required": program.total_credits_required,
        "total_earned": total_earned,
        "satisfied": total_earned >= program.total_credits_required
        and all(c["satisfied"] for c in categories),
    }


# --- Graduation ------------------------------------------------------------

STANDARD_CLEARANCES = [
    ("REG", "Degree audit complete"),
    ("BUR", "Account balance zero"),
    ("LIB", "Library materials returned"),
]


@transaction.atomic
def apply_for_graduation(person, student_program, term, actor):
    require_no_blocks(person, "graduation")
    if GraduationApplication.objects.filter(
        person=person, student_program=student_program,
        status__in=[GraduationApplication.SUBMITTED, GraduationApplication.IN_REVIEW,
                    GraduationApplication.CLEARED],
    ).exists():
        raise ValidationError("An open graduation application already exists.")
    app = GraduationApplication.objects.create(
        person=person, student_program=student_program, term=term
    )
    open_clearance(app, actor)
    return app


def open_clearance(app, actor=None):
    """Create the standard clearance checklist and one task per office —
    the multi-department fan-out."""
    items = list(STANDARD_CLEARANCES)
    from finaid.models import AidAward, AidProgram

    has_loans = AidAward.objects.filter(
        person=app.person, status=AidAward.ACCEPTED, program__aid_type=AidProgram.LOAN
    ).exists()
    if has_loans:
        items.append(("FA", "Loan exit counseling complete"))

    for dept_code, label in items:
        dept = Department.objects.get(code=dept_code)
        ClearanceItem.objects.create(application=app, department=dept, item=label)
        create_task(
            title=f"Graduation clearance: {label} — {app.person.display_name}",
            task_type=Task.GRADUATION_CLEARANCE,
            assigned_department=dept,
            person=app.person,
            originating_department=Department.objects.get(code="REG"),
            related=app,
            description=(
                f"{app.person.display_name} applied to graduate in {app.term.name} "
                f"({app.student_program.program.name}). Clear or flag your item."
            ),
            created_by=actor,
        )
    if app.status == GraduationApplication.SUBMITTED:
        app.status = GraduationApplication.IN_REVIEW
        app.save()


@transaction.atomic
def clear_item(item, actor, note="", flag=False):
    if not permissions.is_member_of(actor, item.department.code):
        raise PermissionDenied(f"Only {item.department.name} can act on this item.")
    item.status = ClearanceItem.FLAGGED if flag else ClearanceItem.CLEARED
    item.cleared_by = actor
    item.cleared_at = timezone.now()
    item.note = note[:255]
    item.save()
    app = item.application
    audit.log(
        "VERIFY" if not flag else "REJECT", item, person=app.person, actor=actor,
        summary=f"Graduation clearance '{item.item}' {item.status.lower()} ({item.department.code})",
    )

    # Close this department's clearance task once it has nothing pending.
    if not app.clearance_items.filter(
        department=item.department, status=ClearanceItem.PENDING
    ).exists():
        from django.contrib.contenttypes.models import ContentType

        ct = ContentType.objects.get_for_model(GraduationApplication)
        task = Task.objects.filter(
            content_type=ct, object_id=str(app.pk),
            assigned_department=item.department,
        ).exclude(status__in=[Task.DONE, Task.CANCELLED]).first()
        if task:
            task.status = Task.DONE
            task.outcome = Task.COMPLETED
            task.completed_by = actor
            task.completed_at = timezone.now()
            task.save()

    if not flag and not app.clearance_items.exclude(status=ClearanceItem.CLEARED).exists():
        app.status = GraduationApplication.CLEARED
        app.save()
        notify_department(
            Department.objects.get(code="REG"),
            f"{app.person.display_name} fully cleared for graduation — ready to award",
            url=reverse("graduation_detail", args=[app.pk]),
        )
    return item


@transaction.atomic
def award_degree(app, actor):
    if not permissions.can_edit_domain(actor, "ACADEMIC"):
        raise PermissionDenied("Only the Registrar can award degrees.")
    if app.status != GraduationApplication.CLEARED:
        raise ValidationError("All clearance items must be cleared before awarding.")
    app.status = GraduationApplication.AWARDED
    app.decided_at = timezone.now()
    app.save()

    sp = app.student_program
    sp.status = StudentProgram.COMPLETED
    sp.save()

    student_aff = app.person.affiliations.filter(
        type=Affiliation.STUDENT, status=Affiliation.ACTIVE
    ).first()
    if student_aff and not StudentProgram.objects.filter(
        person=app.person, status=StudentProgram.ACTIVE
    ).exists():
        student_aff.status = Affiliation.INACTIVE
        student_aff.end_date = timezone.localdate()
        student_aff.save()

    # Cross-silo lifecycle hook: graduate today, alumni record today.
    from advancement.services import make_alumni

    make_alumni(
        app.person,
        class_year=app.term.end_date.year,
        degree=f"{sp.program.get_degree_display()} {sp.program.name}",
        actor=actor,
    )
    return app
