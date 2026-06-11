from decimal import Decimal

from django.contrib import messages
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.generic import TemplateView

from core import permissions
from core.models import Person
from workflow.mixins import GovernedFormMixin, StaffRequiredMixin
from workflow.models import Hold

from .forms import LedgerEntryForm
from .models import LedgerEntry
from .services import balance, post_entry


class AccountListView(StaffRequiredMixin, TemplateView):
    template_name = "bursar/accounts.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        rows = (
            LedgerEntry.objects.values("person")
            .annotate(bal=Sum("amount"))
            .filter(bal__gt=0)
            .order_by("-bal")[:100]
        )
        people = {p.pk: p for p in Person.objects.filter(pk__in=[r["person"] for r in rows])}
        held = set(
            Hold.objects.filter(
                status=Hold.ACTIVE, hold_type__code="BURSAR_BALANCE",
                person_id__in=people.keys(),
            ).values_list("person_id", flat=True)
        )
        ctx["accounts"] = [
            {"person": people[r["person"]], "balance": r["bal"], "has_hold": r["person"] in held}
            for r in rows
        ]
        ctx["total_ar"] = sum((r["bal"] for r in rows), Decimal("0"))
        return ctx


class AccountDetailView(GovernedFormMixin, StaffRequiredMixin, TemplateView):
    """The ledger. BUR members post directly (and the hold automation runs);
    anyone else's posting becomes a HOLD_FOR_APPROVAL change request."""

    template_name = "bursar/account_detail.html"
    data_domain = "STUDENT_ACCOUNT"

    def get(self, request, person_id):
        return self.render_page(request, person_id)

    def post(self, request, person_id):
        self.person = get_object_or_404(Person, pk=person_id)
        form = LedgerEntryForm(request.POST)
        form.instance.person = self.person
        form.instance.posted_by = request.user
        if not form.is_valid():
            return self.render_page(request, person_id, form=form)
        if self.user_owns_domain():
            # Owners go through the service so hold automation runs.
            entry = post_entry(
                self.person,
                entry_type=form.cleaned_data["entry_type"],
                amount=form.cleaned_data["amount"],
                description=form.cleaned_data["description"],
                effective_date=form.cleaned_data.get("effective_date"),
                term=form.cleaned_data.get("term"),
                charge_code=form.cleaned_data.get("charge_code"),
                posted_by=request.user,
            )
            new_balance = balance(self.person)
            messages.success(
                request,
                f"Posted {entry.get_entry_type_display()} ${abs(entry.amount)} — balance is now ${new_balance}.",
            )
            return redirect("bursar_account", person_id=person_id)
        return self.form_valid(form)  # non-owner: change-request path

    def get_governed_person(self, form):
        return self.person

    def get_success_url(self):
        return reverse("bursar_account", args=[self.person.pk])

    def render_page(self, request, person_id, form=None):
        person = get_object_or_404(Person, pk=person_id)
        if not permissions.can_view_domain(request.user, "STUDENT_ACCOUNT"):
            return render(request, "registration/no_access.html", status=403)
        entries = person.ledger_entries.select_related("charge_code", "term", "posted_by")
        running = balance(person)
        return render(request, self.template_name, {
            "person": person,
            "entries": entries,
            "balance": running,
            "form": form or LedgerEntryForm(),
            "holds": person.active_holds(),
            "can_post": permissions.can_edit_domain(request.user, "STUDENT_ACCOUNT"),
        })
