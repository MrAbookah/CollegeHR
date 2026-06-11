from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.generic import DetailView, ListView, TemplateView, UpdateView

from core import audit, permissions
from core.models import Person
from workflow.mixins import GovernedFormMixin, StaffRequiredMixin
from workflow.services import BlockedByHold, check_blocks

from . import services
from .forms import GradeForm, GraduationApplyForm, SectionAddForm
from .models import (ClearanceItem, Course, Enrollment, GraduationApplication,
                     Section, Subject, Term)


class CatalogView(StaffRequiredMixin, ListView):
    template_name = "academics/catalog.html"
    context_object_name = "subjects"

    def get_queryset(self):
        return Subject.objects.prefetch_related("courses")


class CourseDetailView(StaffRequiredMixin, DetailView):
    model = Course
    template_name = "academics/course_detail.html"
    context_object_name = "course"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["sections"] = self.object.sections.select_related("term", "instructor").order_by("-term__start_date")
        return ctx


class SectionListView(StaffRequiredMixin, ListView):
    template_name = "academics/sections.html"
    context_object_name = "sections"

    def get_queryset(self):
        self.term = _resolve_term(self.request)
        return (
            Section.objects.filter(term=self.term)
            .select_related("course__subject", "instructor", "term")
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["term"] = self.term
        ctx["terms"] = Term.objects.all()
        return ctx


def _resolve_term(request):
    code = request.GET.get("term")
    if code:
        term = Term.objects.filter(code=code).first()
        if term:
            return term
    return Term.objects.filter(is_current=True).first() or Term.objects.first()


class SectionDetailView(StaffRequiredMixin, DetailView):
    model = Section
    template_name = "academics/section_detail.html"
    context_object_name = "section"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["roster"] = self.object.enrollments.exclude(
            status=Enrollment.DROPPED
        ).select_related("person")
        ctx["can_grade"] = services.can_grade(self.request.user, self.object)
        ctx["grade_form"] = GradeForm()
        return ctx


@login_required
def enter_grade(request, pk, enrollment_id):
    section = get_object_or_404(Section, pk=pk)
    enrollment = get_object_or_404(Enrollment, pk=enrollment_id, section=section)
    if request.method == "POST":
        form = GradeForm(request.POST)
        if form.is_valid():
            try:
                services.enter_grade(enrollment, form.cleaned_data["grade"], request.user)
                messages.success(
                    request,
                    f"Grade {enrollment.grade} recorded for {enrollment.person.display_name}.",
                )
            except (PermissionDenied, ValidationError) as exc:
                messages.error(request, str(getattr(exc, "message", exc)))
    return redirect("section_detail", pk=pk)


class GradeChangeView(GovernedFormMixin, StaffRequiredMixin, UpdateView):
    """Grade changes from outside the Registrar (or the instructor) become
    HOLD_FOR_APPROVAL change requests — nothing moves until REG signs off."""

    model = Enrollment
    form_class = GradeForm
    template_name = "academics/grade_change.html"
    data_domain = "ACADEMIC"

    def user_owns_domain(self):
        return services.can_grade(self.request.user, self.get_object().section)

    def form_valid(self, form):
        response = super().form_valid(form)
        # When the owner saved directly, run the same derivation the service
        # applies (points, status, graded_by).
        if self.user_owns_domain() and self.object:
            services.apply_grade_fields(self.object, self.request.user)
        return response

    def get_success_url(self):
        return reverse("person_detail", args=[self.get_object().person_id])


class RegistrationView(StaffRequiredMixin, TemplateView):
    """Registrar-side add/drop. Hold blocking happens in the service; the
    template names the blocking hold and who owns it."""

    template_name = "academics/register.html"

    def get(self, request, person_id):
        return self.render_page(request, person_id)

    def post(self, request, person_id):
        person = get_object_or_404(Person, pk=person_id)
        if not permissions.can_edit_domain(request.user, "ACADEMIC"):
            raise PermissionDenied("Only the Registrar registers students in this screen.")
        action = request.POST.get("action")
        try:
            if action == "add":
                form = SectionAddForm(request.POST, term=_resolve_term(request))
                if form.is_valid():
                    enrollment = services.register(person, form.cleaned_data["section"], request.user)
                    messages.success(request, f"Registered in {enrollment.section}.")
                else:
                    messages.error(request, "; ".join(e for errs in form.errors.values() for e in errs))
            elif action == "drop":
                enrollment = get_object_or_404(
                    Enrollment, pk=request.POST.get("enrollment_id"), person=person
                )
                services.drop(enrollment, request.user)
                messages.success(request, f"Dropped {enrollment.section}.")
        except BlockedByHold as exc:
            return self.render_page(request, person_id, blocked=exc.holds)
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
        return self.render_page(request, person_id)

    def render_page(self, request, person_id, blocked=None):
        person = get_object_or_404(Person, pk=person_id)
        term = _resolve_term(request)
        schedule = person.enrollments.filter(
            section__term=term, status=Enrollment.REGISTERED
        ).select_related("section__course__subject", "section__instructor")
        return render(request, self.template_name, {
            "person": person,
            "term": term,
            "terms": Term.objects.all(),
            "schedule": schedule,
            "credits": sum(e.section.course.credits for e in schedule),
            "blocked_holds": blocked or check_blocks(person, "registration"),
            "add_form": SectionAddForm(term=term),
            "can_register": permissions.can_edit_domain(request.user, "ACADEMIC"),
        })


@login_required
def transcript(request, person_id):
    person = get_object_or_404(Person, pk=person_id)
    if not permissions.is_staff_member(request.user):
        raise PermissionDenied
    blocking = check_blocks(person, "transcript")
    if blocking:
        return render(request, "academics/transcript_blocked.html", {
            "person": person, "holds": blocking,
        })
    audit.log("VIEW", person=person, summary=f"Viewed transcript of {person.display_name}")
    terms = {}
    for e in person.enrollments.filter(
        status__in=[Enrollment.COMPLETED, Enrollment.WITHDRAWN, Enrollment.REGISTERED]
    ).select_related("section__term", "section__course__subject").order_by("section__term__start_date"):
        terms.setdefault(e.section.term, []).append(e)
    return render(request, "academics/transcript.html", {
        "person": person,
        "terms": [
            {"term": t, "enrollments": rows, "gpa": services.gpa(person, t)}
            for t, rows in terms.items()
        ],
        "cumulative_gpa": services.gpa(person),
        "total_credits": services.completed_credits(person),
        "programs": person.student_programs.select_related("program"),
    })


class GraduationBoardView(StaffRequiredMixin, TemplateView):
    """Rows = applicants, columns = departments. The whole cross-office
    story on one screen."""

    template_name = "academics/graduation_board.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        apps = (
            GraduationApplication.objects.exclude(status=GraduationApplication.DENIED)
            .select_related("person", "student_program__program", "term")
            .prefetch_related("clearance_items__department")
            .order_by("status", "person__last_name")
        )
        dept_codes = []
        for app in apps:
            for item in app.clearance_items.all():
                if item.department.code not in dept_codes:
                    dept_codes.append(item.department.code)
        rows = []
        for app in apps:
            by_dept = {}
            for item in app.clearance_items.all():
                by_dept.setdefault(item.department.code, []).append(item)
            rows.append({
                "app": app,
                "cells": [by_dept.get(code, []) for code in dept_codes],
            })
        ctx["dept_codes"] = dept_codes
        ctx["rows"] = rows
        return ctx


class GraduationDetailView(StaffRequiredMixin, DetailView):
    model = GraduationApplication
    template_name = "academics/graduation_detail.html"
    context_object_name = "app"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        app = self.object
        user = self.request.user
        ctx["items"] = app.clearance_items.select_related("department", "cleared_by")
        ctx["audit_result"] = services.degree_audit(app.student_program)
        ctx["actionable_items"] = [
            i for i in ctx["items"]
            if i.status == ClearanceItem.PENDING and permissions.is_member_of(user, i.department.code)
        ]
        ctx["can_award"] = (
            app.status == GraduationApplication.CLEARED
            and permissions.can_edit_domain(user, "ACADEMIC")
        )
        return ctx


@login_required
def clearance_action(request, pk, item_id):
    app = get_object_or_404(GraduationApplication, pk=pk)
    item = get_object_or_404(ClearanceItem, pk=item_id, application=app)
    if request.method == "POST":
        try:
            services.clear_item(
                item, request.user,
                note=request.POST.get("note", ""),
                flag=request.POST.get("verdict") == "flag",
            )
        except PermissionDenied as exc:
            messages.error(request, str(exc))
        else:
            verb = "flagged" if item.status == ClearanceItem.FLAGGED else "cleared"
            messages.success(request, f"{item.item} {verb}.")
    return redirect("graduation_detail", pk=pk)


@login_required
def award_degree(request, pk):
    app = get_object_or_404(GraduationApplication, pk=pk)
    if request.method == "POST":
        try:
            services.award_degree(app, request.user)
        except (PermissionDenied, ValidationError) as exc:
            messages.error(request, str(getattr(exc, "message", exc)))
        else:
            messages.success(
                request,
                f"Degree awarded — {app.person.display_name} is now an alum. Advancement was notified.",
            )
    return redirect("graduation_detail", pk=pk)


@login_required
def graduation_apply(request, person_id):
    person = get_object_or_404(Person, pk=person_id)
    if request.method != "POST":
        return redirect("person_detail", pk=person_id)
    if not permissions.can_edit_domain(request.user, "ACADEMIC"):
        raise PermissionDenied("Only the Registrar submits graduation applications here.")
    form = GraduationApplyForm(request.POST, person=person)
    if not form.is_valid():
        messages.error(request, "; ".join(e for errs in form.errors.values() for e in errs))
        return redirect("person_detail", pk=person_id)
    try:
        app = services.apply_for_graduation(
            person, form.cleaned_data["student_program"], form.cleaned_data["term"], request.user
        )
    except BlockedByHold as exc:
        names = ", ".join(
            f"{h.hold_type.name} ({h.hold_type.owning_department.name})" for h in exc.holds
        )
        messages.error(request, f"Cannot apply: blocked by {names}.")
        return redirect("person_detail", pk=person_id)
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
        return redirect("person_detail", pk=person_id)
    messages.success(request, "Graduation application submitted — clearance items fanned out.")
    return redirect("graduation_detail", pk=app.pk)
