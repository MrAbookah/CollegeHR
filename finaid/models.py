"""Financial aid: aid years, programs, awards, disbursements. Disbursing
posts straight to the bursar ledger in the same transaction — no overnight
batch, no reconciliation meeting."""

from django.db import models

from core.models import Person, TimeStampedModel


class AidYear(TimeStampedModel):
    code = models.CharField(max_length=9, unique=True)  # "2025-26"
    start_date = models.DateField()
    end_date = models.DateField()

    class Meta:
        ordering = ["-start_date"]

    def __str__(self):
        return self.code


class AidProgram(TimeStampedModel):
    FEDERAL, STATE, INSTITUTIONAL = "FEDERAL", "STATE", "INSTITUTIONAL"
    SOURCES = [(FEDERAL, "Federal"), (STATE, "State"), (INSTITUTIONAL, "Institutional")]
    GRANT, SCHOLARSHIP, LOAN, WORKSTUDY = "GRANT", "SCHOLARSHIP", "LOAN", "WORKSTUDY"
    TYPES = [
        (GRANT, "Grant"), (SCHOLARSHIP, "Scholarship"),
        (LOAN, "Loan"), (WORKSTUDY, "Work-study"),
    ]

    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=100)
    source = models.CharField(max_length=15, choices=SOURCES)
    aid_type = models.CharField(max_length=12, choices=TYPES)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return self.name


class AidAward(TimeStampedModel):
    data_domain = "FINANCIAL_AID"

    OFFERED, ACCEPTED, DECLINED = "OFFERED", "ACCEPTED", "DECLINED"
    STATUSES = [(OFFERED, "Offered"), (ACCEPTED, "Accepted"), (DECLINED, "Declined")]

    person = models.ForeignKey(Person, on_delete=models.PROTECT, related_name="aid_awards")
    aid_year = models.ForeignKey(AidYear, on_delete=models.PROTECT, related_name="awards")
    program = models.ForeignKey(AidProgram, on_delete=models.PROTECT, related_name="awards")
    amount_offered = models.DecimalField(max_digits=10, decimal_places=2)
    amount_accepted = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    status = models.CharField(max_length=10, choices=STATUSES, default=OFFERED)
    offered_at = models.DateTimeField(auto_now_add=True)
    responded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-offered_at"]

    def __str__(self):
        return f"{self.program.code} ${self.amount_offered} — {self.person.display_name} ({self.aid_year})"


class Disbursement(TimeStampedModel):
    SCHEDULED, DISBURSED = "SCHEDULED", "DISBURSED"
    STATUSES = [(SCHEDULED, "Scheduled"), (DISBURSED, "Disbursed")]

    award = models.ForeignKey(AidAward, on_delete=models.PROTECT, related_name="disbursements")
    term = models.ForeignKey("academics.Term", on_delete=models.PROTECT, related_name="+")
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=10, choices=STATUSES, default=SCHEDULED)
    disbursed_at = models.DateTimeField(null=True, blank=True)
    ledger_entry = models.ForeignKey(
        "student_accounts.LedgerEntry", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )

    def __str__(self):
        return f"{self.award.program.code} ${self.amount} ({self.term.code}) [{self.status}]"

    @property
    def person(self):  # so audit logging can attribute the row
        return self.award.person

    @property
    def person_id(self):
        return self.award.person_id
