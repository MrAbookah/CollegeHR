from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.views.generic import ListView, TemplateView

from core import permissions
from core.models import Person
from workflow.mixins import StaffRequiredMixin

from .forms import GiftForm, PledgeForm
from .models import Gift, Pledge
from .services import record_gift


class GiftListView(StaffRequiredMixin, TemplateView):
    template_name = "advancement/gifts.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        if not permissions.can_view_domain(self.request.user, "ADVANCEMENT"):
            ctx["forbidden"] = True
            return ctx
        ctx["gifts"] = Gift.objects.select_related("person", "designation")[:50]
        ctx["by_designation"] = (
            Gift.objects.values("designation__name")
            .annotate(total=Sum("amount"), n=Count("id")).order_by("-total")
        )
        ctx["total"] = Gift.objects.aggregate(t=Sum("amount"))["t"] or 0
        return ctx


class DonorView(StaffRequiredMixin, TemplateView):
    template_name = "advancement/donor.html"

    def get(self, request, person_id):
        return self.render_page(request, person_id)

    def post(self, request, person_id):
        person = get_object_or_404(Person, pk=person_id)
        if not permissions.can_edit_domain(request.user, "ADVANCEMENT"):
            raise PermissionDenied("Only Advancement records gifts.")
        form = GiftForm(request.POST)
        if form.is_valid():
            gift = record_gift(
                person,
                form.cleaned_data["designation"],
                form.cleaned_data["amount"],
                method=form.cleaned_data["method"],
                gift_date=form.cleaned_data["gift_date"],
                pledge=form.cleaned_data.get("pledge"),
                actor=request.user,
            )
            messages.success(
                request,
                f"Recorded ${gift.amount} gift (receipt {gift.receipt_number}). "
                "Donor affiliation is on their record.",
            )
            return redirect("donor_detail", person_id=person_id)
        return self.render_page(request, person_id, form=form)

    def render_page(self, request, person_id, form=None):
        person = get_object_or_404(Person, pk=person_id)
        if not permissions.can_view_domain(request.user, "ADVANCEMENT"):
            return render(request, "registration/no_access.html", status=403)
        return render(request, self.template_name, {
            "person": person,
            "gifts": person.gifts.select_related("designation", "pledge"),
            "pledges": person.pledges.select_related("designation"),
            "alumni_info": getattr(person, "alumni_info", None),
            "total": person.gifts.aggregate(t=Sum("amount"))["t"] or 0,
            "form": form or GiftForm(),
            "can_edit": permissions.can_edit_domain(request.user, "ADVANCEMENT"),
        })


class PledgeListView(StaffRequiredMixin, ListView):
    template_name = "advancement/pledges.html"
    context_object_name = "pledges"

    def get_queryset(self):
        if not permissions.can_view_domain(self.request.user, "ADVANCEMENT"):
            return Pledge.objects.none()
        return Pledge.objects.select_related("person", "designation")[:100]

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["forbidden"] = not permissions.can_view_domain(self.request.user, "ADVANCEMENT")
        return ctx


@login_required
def pledge_create(request, person_id):
    person = get_object_or_404(Person, pk=person_id)
    if not permissions.can_edit_domain(request.user, "ADVANCEMENT"):
        raise PermissionDenied
    if request.method == "POST":
        form = PledgeForm(request.POST)
        if form.is_valid():
            pledge = form.save(commit=False)
            pledge.person = person
            pledge.save()
            messages.success(request, f"Pledge of ${pledge.total_amount} recorded.")
    return redirect("donor_detail", person_id=person_id)
