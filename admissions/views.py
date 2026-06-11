from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.generic import DetailView, TemplateView

from core import permissions
from core.models import Affiliation, Person
from workflow.mixins import StaffRequiredMixin

from . import services
from .forms import ApplicationForm, CommunicationForm
from .models import Application, ApplicationChecklistItem


class PipelineView(StaffRequiredMixin, TemplateView):
    template_name = "admissions/pipeline.html"

    def get_context_data(self, **kwargs):
        from academics.models import Term

        ctx = super().get_context_data(**kwargs)
        code = self.request.GET.get("term")
        term = Term.objects.filter(code=code).first() if code else None
        apps = Application.objects.select_related("person", "program", "term")
        if term:
            apps = apps.filter(term=term)
        columns = []
        for stage, label in Application.STAGES:
            cards = [a for a in apps if a.stage == stage]
            columns.append({"stage": stage, "label": label, "cards": cards, "count": len(cards)})
        ctx["columns"] = columns
        ctx["term"] = term
        ctx["terms"] = Term.objects.all()
        ctx["is_admissions"] = permissions.is_member_of(self.request.user, "ADM")
        return ctx


class ApplicationDetailView(StaffRequiredMixin, DetailView):
    model = Application
    template_name = "admissions/application_detail.html"
    context_object_name = "application"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        app = self.object
        ctx["checklist"] = app.checklist.select_related("doc_type", "document")
        ctx["communications"] = app.communications.select_related("logged_by")
        ctx["comm_form"] = CommunicationForm()
        ctx["is_admissions"] = permissions.is_member_of(self.request.user, "ADM")
        ctx["next_stages"] = [
            (s, dict(Application.STAGES)[s]) for s in app.next_stages
        ]
        return ctx


@login_required
def application_create(request, person_id):
    person = get_object_or_404(Person, pk=person_id)
    if not permissions.is_member_of(request.user, "ADM"):
        raise PermissionDenied("Only Admissions creates applications.")
    if request.method == "POST":
        form = ApplicationForm(request.POST)
        if form.is_valid():
            application = form.save(commit=False)
            application.person = person
            application.counselor = request.user
            application.save()
            Affiliation.objects.get_or_create(
                person=person, type=Affiliation.APPLICANT, status=Affiliation.ACTIVE,
                defaults={"start_date": timezone.localdate()},
            )
            messages.success(request, f"Application opened for {person.display_name}.")
            return redirect("application_detail", pk=application.pk)
    else:
        form = ApplicationForm()
    return render(request, "admissions/application_form.html", {"form": form, "person": person})


@login_required
def stage_change(request, pk):
    application = get_object_or_404(Application, pk=pk)
    if request.method == "POST":
        try:
            services.change_stage(application, request.POST.get("stage", ""), request.user)
        except (PermissionDenied, ValidationError) as exc:
            messages.error(request, str(getattr(exc, "message", exc)))
        else:
            messages.success(request, f"Moved to {application.get_stage_display()}.")
            if application.stage == Application.ENROLLED:
                messages.info(
                    request,
                    "Student affiliation created; Registrar got an advisor task; Financial Aid was notified.",
                )
    return redirect("application_detail", pk=pk)


@login_required
def checklist_waive(request, pk, item_id):
    application = get_object_or_404(Application, pk=pk)
    item = get_object_or_404(ApplicationChecklistItem, pk=item_id, application=application)
    if request.method == "POST":
        if not permissions.is_member_of(request.user, "ADM"):
            raise PermissionDenied
        item.status = ApplicationChecklistItem.WAIVED
        item.save()
        messages.success(request, f"Waived: {item.name}")
    return redirect("application_detail", pk=pk)


@login_required
def communication_add(request, pk):
    application = get_object_or_404(Application, pk=pk)
    if request.method == "POST":
        form = CommunicationForm(request.POST)
        if form.is_valid():
            comm = form.save(commit=False)
            comm.person = application.person
            comm.application = application
            comm.logged_by = request.user
            if not comm.occurred_at:
                comm.occurred_at = timezone.now()
            comm.save()
            messages.success(request, "Interaction logged.")
    return redirect("application_detail", pk=pk)
