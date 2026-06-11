from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.views.generic import TemplateView

from core import permissions
from core.models import Person
from workflow.mixins import StaffRequiredMixin

from . import services
from .forms import AwardForm
from .models import AidAward, AidYear, Disbursement


class AwardListView(StaffRequiredMixin, TemplateView):
    template_name = "finaid/awards.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        if not permissions.can_view_domain(self.request.user, "FINANCIAL_AID"):
            ctx["forbidden"] = True
            return ctx
        code = self.request.GET.get("year")
        year = AidYear.objects.filter(code=code).first() or AidYear.objects.first()
        awards = AidAward.objects.filter(aid_year=year).select_related("person", "program")
        ctx.update(
            year=year,
            years=AidYear.objects.all(),
            awards=awards.order_by("person__last_name")[:200],
            total_offered=awards.aggregate(t=Sum("amount_offered"))["t"] or 0,
            total_accepted=awards.filter(status=AidAward.ACCEPTED).aggregate(
                t=Sum("amount_accepted"))["t"] or 0,
        )
        return ctx


class PackageView(StaffRequiredMixin, TemplateView):
    template_name = "finaid/package.html"

    def get(self, request, person_id):
        return self.render_page(request, person_id)

    def post(self, request, person_id):
        person = get_object_or_404(Person, pk=person_id)
        if not permissions.can_edit_domain(request.user, "FINANCIAL_AID"):
            raise PermissionDenied("Only Financial Aid can package awards.")
        form = AwardForm(request.POST)
        if form.is_valid():
            award = form.save(commit=False)
            award.person = person
            award.save()
            messages.success(request, f"Offered {award.program.name}: ${award.amount_offered}.")
            return redirect("finaid_package", person_id=person_id)
        return self.render_page(request, person_id, form=form)

    def render_page(self, request, person_id, form=None):
        person = get_object_or_404(Person, pk=person_id)
        if not permissions.can_view_domain(request.user, "FINANCIAL_AID"):
            return render(request, "registration/no_access.html", status=403)
        awards = person.aid_awards.select_related("program", "aid_year").prefetch_related(
            "disbursements__term"
        )
        return render(request, self.template_name, {
            "person": person,
            "awards": awards,
            "form": form or AwardForm(),
            "can_edit": permissions.can_edit_domain(request.user, "FINANCIAL_AID"),
        })


@login_required
def award_respond(request, pk):
    award = get_object_or_404(AidAward, pk=pk)
    if request.method == "POST":
        if not permissions.can_edit_domain(request.user, "FINANCIAL_AID"):
            raise PermissionDenied
        try:
            services.respond_to_award(
                award, accept=request.POST.get("decision") == "accept", actor=request.user
            )
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
        else:
            messages.success(request, f"Award {award.status.lower()}.")
    return redirect("finaid_package", person_id=award.person_id)


@login_required
def disburse(request, pk):
    disbursement = get_object_or_404(Disbursement, pk=pk)
    if request.method == "POST":
        if not permissions.can_edit_domain(request.user, "FINANCIAL_AID"):
            raise PermissionDenied
        try:
            services.disburse(disbursement, request.user)
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
        else:
            messages.success(
                request,
                f"Disbursed ${disbursement.amount} to {disbursement.award.person.display_name}'s "
                "account — the bursar ledger updated instantly.",
            )
    return redirect("finaid_package", person_id=disbursement.award.person_id)
