from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.generic import DetailView, ListView, TemplateView

from core import audit, permissions
from core.models import Person
from workflow.mixins import GovernedFormMixin, StaffRequiredMixin

from .forms import EmploymentRecordForm
from .models import EmploymentRecord, PayrollRun


class RosterView(StaffRequiredMixin, ListView):
    template_name = "hr/roster.html"
    context_object_name = "records"

    def get_queryset(self):
        if not permissions.can_view_domain(self.request.user, "EMPLOYMENT"):
            return EmploymentRecord.objects.none()
        return (
            EmploymentRecord.objects.filter(status__in=[EmploymentRecord.ACTIVE, EmploymentRecord.ON_LEAVE])
            .select_related("person", "position__department")
            .order_by("person__last_name")
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["forbidden"] = not permissions.can_view_domain(self.request.user, "EMPLOYMENT")
        return ctx


class EmployeeDetailView(StaffRequiredMixin, TemplateView):
    template_name = "hr/employee.html"

    def get(self, request, person_id):
        person = get_object_or_404(Person, pk=person_id)
        if not permissions.can_view_domain(request.user, "EMPLOYMENT"):
            return render(request, "registration/no_access.html", status=403)
        salary_visible = permissions.can_see_field(request.user, "hr.employmentrecord", "salary")
        if salary_visible:
            audit.log("VIEW", person=person,
                      summary=f"Viewed employment file incl. salary for {person.display_name}")
        return render(request, self.template_name, {
            "person": person,
            "records": person.employment_records.select_related("position__department", "supervisor"),
            "paychecks": person.paychecks.select_related("payroll_run")[:12],
            "salary_visible": salary_visible,
            "can_edit": permissions.can_edit_domain(request.user, "EMPLOYMENT"),
        })


class EmploymentEditView(GovernedFormMixin, StaffRequiredMixin, TemplateView):
    """HR edits directly; anyone else's edit is held for HR approval."""

    template_name = "hr/employment_form.html"
    data_domain = "EMPLOYMENT"

    def get(self, request, pk):
        record = get_object_or_404(EmploymentRecord, pk=pk)
        form = EmploymentRecordForm(instance=record, user=request.user)
        return render(request, self.template_name, {"form": form, "record": record})

    def post(self, request, pk):
        record = get_object_or_404(EmploymentRecord, pk=pk)
        self.record = record
        form = EmploymentRecordForm(request.POST, instance=record, user=request.user)
        if not form.is_valid():
            return render(request, self.template_name, {"form": form, "record": record})
        return self.form_valid(form)

    def get_success_url(self):
        return reverse("hr_employee", args=[self.record.person_id])


class PayrollListView(StaffRequiredMixin, ListView):
    template_name = "hr/payroll.html"
    context_object_name = "runs"

    def get_queryset(self):
        if not permissions.can_view_domain(self.request.user, "EMPLOYMENT"):
            return PayrollRun.objects.none()
        return PayrollRun.objects.all()[:24]


class PayrollDetailView(StaffRequiredMixin, DetailView):
    model = PayrollRun
    template_name = "hr/payroll_detail.html"
    context_object_name = "run"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        allowed = permissions.can_view_domain(self.request.user, "EMPLOYMENT")
        ctx["forbidden"] = not allowed
        if allowed:
            ctx["paychecks"] = self.object.paychecks.select_related("person")
            ctx["salary_visible"] = permissions.can_see_field(
                self.request.user, "hr.employmentrecord", "salary")
        return ctx
