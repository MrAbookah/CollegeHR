from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.views.generic import DetailView, ListView, TemplateView

from core import permissions
from workflow.mixins import StaffRequiredMixin

from .forms import JournalEntryForm, JournalLineForm
from .models import DepartmentBudget, FiscalYear, JournalEntry, JournalLine


class BudgetView(StaffRequiredMixin, TemplateView):
    template_name = "finance/budgets.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        if not permissions.can_view_domain(self.request.user, "FINANCE"):
            ctx["forbidden"] = True
            return ctx
        fy = FiscalYear.objects.first()
        budgets = DepartmentBudget.objects.filter(fiscal_year=fy).select_related(
            "department", "gl_account"
        )
        actuals = {
            (row["department"], row["gl_account"]): (row["d"] or 0) - (row["c"] or 0)
            for row in JournalLine.objects.filter(entry__status=JournalEntry.POSTED)
            .values("department", "gl_account").annotate(d=Sum("debit"), c=Sum("credit"))
        }
        rows = []
        for b in budgets:
            actual = actuals.get((b.department_id, b.gl_account_id), 0)
            rows.append({"budget": b, "actual": actual, "remaining": b.amount - actual})
        ctx.update(fy=fy, rows=rows)
        return ctx


class JournalListView(StaffRequiredMixin, ListView):
    template_name = "finance/journal.html"
    context_object_name = "entries"
    paginate_by = 30

    def get_queryset(self):
        if not permissions.can_view_domain(self.request.user, "FINANCE"):
            return JournalEntry.objects.none()
        return JournalEntry.objects.all()

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["forbidden"] = not permissions.can_view_domain(self.request.user, "FINANCE")
        ctx["can_edit"] = permissions.can_edit_domain(self.request.user, "FINANCE")
        return ctx


@login_required
def journal_create(request):
    if not permissions.can_edit_domain(request.user, "FINANCE"):
        raise PermissionDenied("Only Finance creates journal entries.")
    if request.method == "POST":
        form = JournalEntryForm(request.POST)
        if form.is_valid():
            entry = form.save()
            messages.success(request, "Draft journal entry created — add balanced lines, then post.")
            return redirect("journal_detail", pk=entry.pk)
    else:
        form = JournalEntryForm()
    return render(request, "finance/journal_form.html", {"form": form})


class JournalDetailView(StaffRequiredMixin, DetailView):
    model = JournalEntry
    template_name = "finance/journal_detail.html"
    context_object_name = "entry"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        debits, credits = self.object.totals()
        ctx.update(
            lines=self.object.lines.select_related("gl_account", "department"),
            line_form=JournalLineForm(),
            debits=debits, credits=credits,
            balanced=debits == credits and debits > 0,
            can_edit=permissions.can_edit_domain(self.request.user, "FINANCE"),
        )
        return ctx


@login_required
def journal_add_line(request, pk):
    entry = get_object_or_404(JournalEntry, pk=pk)
    if request.method == "POST":
        if not permissions.can_edit_domain(request.user, "FINANCE"):
            raise PermissionDenied
        if entry.status == JournalEntry.POSTED:
            messages.error(request, "Posted entries are immutable.")
        else:
            form = JournalLineForm(request.POST)
            if form.is_valid():
                line = form.save(commit=False)
                line.entry = entry
                line.save()
    return redirect("journal_detail", pk=pk)


@login_required
def journal_post(request, pk):
    entry = get_object_or_404(JournalEntry, pk=pk)
    if request.method == "POST":
        if not permissions.can_edit_domain(request.user, "FINANCE"):
            raise PermissionDenied
        try:
            entry.post(request.user)
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
        else:
            messages.success(request, "Journal entry posted.")
    return redirect("journal_detail", pk=pk)
