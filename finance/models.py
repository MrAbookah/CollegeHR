"""Finance: a lightweight general ledger — chart of accounts, department
budgets, and balanced journal entries. Enough for budget-vs-actual screens;
automated rollup from the bursar subledger is documented as post-MVP."""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from core.models import Department, TimeStampedModel


class FiscalYear(TimeStampedModel):
    code = models.CharField(max_length=8, unique=True)  # "FY2026"
    start_date = models.DateField()
    end_date = models.DateField()

    class Meta:
        ordering = ["-start_date"]

    def __str__(self):
        return self.code


class GLAccount(TimeStampedModel):
    ASSET, LIABILITY, NET_ASSET, REVENUE, EXPENSE = (
        "ASSET", "LIABILITY", "NET_ASSET", "REVENUE", "EXPENSE",
    )
    TYPES = [
        (ASSET, "Asset"), (LIABILITY, "Liability"), (NET_ASSET, "Net asset"),
        (REVENUE, "Revenue"), (EXPENSE, "Expense"),
    ]

    number = models.CharField(max_length=10, unique=True)
    name = models.CharField(max_length=120)
    type = models.CharField(max_length=10, choices=TYPES)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["number"]

    def __str__(self):
        return f"{self.number} — {self.name}"


class DepartmentBudget(TimeStampedModel):
    fiscal_year = models.ForeignKey(FiscalYear, on_delete=models.PROTECT, related_name="budgets")
    department = models.ForeignKey(Department, on_delete=models.PROTECT, related_name="budgets")
    gl_account = models.ForeignKey(GLAccount, on_delete=models.PROTECT, related_name="budgets")
    amount = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["fiscal_year", "department", "gl_account"], name="uniq_budget_line"
            )
        ]

    def __str__(self):
        return f"{self.fiscal_year} {self.department.code} {self.gl_account.number}: ${self.amount}"


class JournalEntry(TimeStampedModel):
    DRAFT, POSTED = "DRAFT", "POSTED"
    STATUSES = [(DRAFT, "Draft"), (POSTED, "Posted")]

    entry_date = models.DateField()
    description = models.CharField(max_length=200)
    status = models.CharField(max_length=10, choices=STATUSES, default=DRAFT)
    posted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["-entry_date"]
        verbose_name_plural = "journal entries"

    def __str__(self):
        return f"JE {self.entry_date}: {self.description} [{self.status}]"

    def totals(self):
        from django.db.models import Sum

        agg = self.lines.aggregate(debits=Sum("debit"), credits=Sum("credit"))
        return agg["debits"] or 0, agg["credits"] or 0

    def post(self, user):
        debits, credits = self.totals()
        if debits != credits or debits == 0:
            raise ValidationError(f"Entry does not balance (debits {debits}, credits {credits}).")
        self.status = self.POSTED
        self.posted_by = user
        self.save()


class JournalLine(TimeStampedModel):
    entry = models.ForeignKey(JournalEntry, on_delete=models.CASCADE, related_name="lines")
    gl_account = models.ForeignKey(GLAccount, on_delete=models.PROTECT, related_name="lines")
    department = models.ForeignKey(
        Department, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    debit = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    credit = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    def __str__(self):
        return f"{self.gl_account.number} D{self.debit} C{self.credit}"
