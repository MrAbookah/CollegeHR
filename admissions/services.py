"""Admissions services: legal stage transitions plus the enrollment
lifecycle hook that turns an applicant into a student across every
department in one click."""

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from core import permissions
from core.models import Affiliation, Department
from workflow.models import Task
from workflow.services import create_task, notify_department

from .models import Application, ApplicationChecklistItem

# Per-program-degree checklist templates applied when an application reaches
# APPLIED. doc_type codes map to documents.DocumentType.
CHECKLIST_TEMPLATES = {
    "DEFAULT": [
        ("High school transcript", "HS_TRANSCRIPT", True),
        ("Government ID", "GOVT_ID", True),
        ("Recommendation letter", "RECOMMENDATION", False),
    ],
    "TRANSFER": [
        ("College transcript", "COLLEGE_TRANSCRIPT", True),
        ("Government ID", "GOVT_ID", True),
    ],
}


def build_checklist(application):
    from documents.models import DocumentType

    key = "TRANSFER" if application.source == Application.TRANSFER else "DEFAULT"
    for name, doc_code, required in CHECKLIST_TEMPLATES[key]:
        doc_type = DocumentType.objects.filter(code=doc_code).first()
        ApplicationChecklistItem.objects.get_or_create(
            application=application, name=name,
            defaults={"doc_type": doc_type, "required": required},
        )


@transaction.atomic
def change_stage(application, new_stage, actor):
    if not permissions.is_member_of(actor, "ADM"):
        raise PermissionDenied("Only Admissions can move applications through the pipeline.")
    if new_stage not in application.next_stages:
        raise ValidationError(
            f"Cannot move from {application.get_stage_display()} to {new_stage}."
        )
    # Validate before mutating: a failed transition must leave the in-memory
    # instance exactly as it was.
    if new_stage == Application.IN_REVIEW and not application.checklist_complete:
        raise ValidationError("Checklist incomplete — collect or waive required items first.")

    application.stage = new_stage
    now = timezone.now()

    if new_stage == Application.APPLIED:
        application.submitted_at = now
        build_checklist(application)
    elif new_stage == Application.IN_REVIEW:
        create_task(
            title=f"Review application: {application.person.display_name} → {application.program.code}",
            task_type=Task.REVIEW_APPLICATION,
            assigned_department=Department.objects.get(code="ADM"),
            person=application.person,
            related=application,
            created_by=actor,
        )
    elif new_stage in (Application.ADMITTED, Application.DENIED, Application.WAITLISTED):
        application.decided_at = now
        application.decided_by = actor
    elif new_stage == Application.DEPOSITED:
        application.deposit_paid_at = now
    elif new_stage == Application.ENROLLED:
        application.save()
        enroll_student(application, actor)
        return application

    application.save()
    return application


def enroll_student(application, actor):
    """DEPOSITED → ENROLLED: the person becomes a student everywhere at
    once. Affiliation, program, advisor referral to REG, heads-up to FA."""
    from academics.models import StudentProgram

    person = application.person

    Affiliation.objects.get_or_create(
        person=person, type=Affiliation.STUDENT, status=Affiliation.ACTIVE,
        defaults={"start_date": application.term.start_date},
    )
    applicant_aff = person.affiliations.filter(
        type=Affiliation.APPLICANT, status=Affiliation.ACTIVE
    ).first()
    if applicant_aff:
        applicant_aff.status = Affiliation.INACTIVE
        applicant_aff.end_date = timezone.localdate()
        applicant_aff.save()

    start_year = application.term.start_date.year
    StudentProgram.objects.get_or_create(
        person=person, program=application.program, status=StudentProgram.ACTIVE,
        defaults={
            "catalog_year": f"{start_year}-{str(start_year + 1)[-2:]}",
            "declared_date": timezone.localdate(),
        },
    )

    create_task(
        title=f"New enrollee: assign advisor — {person.display_name}",
        task_type=Task.REFERRAL,
        assigned_department=Department.objects.get(code="REG"),
        person=person,
        originating_department=Department.objects.get(code="ADM"),
        related=application,
        description=(
            f"{person.display_name} enrolled in {application.program.name} for "
            f"{application.term.name}. Assign an advisor and confirm the program record."
        ),
        created_by=actor,
    )

    # FA always gets a heads-up: aid packaging starts at enrollment.
    notify_department(
            Department.objects.get(code="FA"),
        f"{person.display_name} enrolled for {application.term.name} — package aid if eligible",
        url=reverse("person_detail", args=[person.pk]),
        exclude_user=actor,
    )
    return application
