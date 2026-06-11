"""Bursar / student accounts: a signed ledger per person. Posting recomputes
the balance synchronously and places/releases the bursar hold — the holds
appear and disappear the moment the money moves."""

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from core.models import Person, TimeStampedModel


class ChargeCode(TimeStampedModel):
    code = models.CharField(max_length=20, unique=True)
    description = models.CharField(max_length=120)
    default_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    gl_account = models.ForeignKey(
        "finance.GLAccount", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} — {self.description}"


class LedgerEntry(TimeStampedModel):
    data_domain = "STUDENT_ACCOUNT"

    CHARGE, PAYMENT, AID_CREDIT = "CHARGE", "PAYMENT", "AID_CREDIT"
    REFUND, ADJUSTMENT, WAIVER = "REFUND", "ADJUSTMENT", "WAIVER"
    TYPES = [
        (CHARGE, "Charge"), (PAYMENT, "Payment"), (AID_CREDIT, "Aid credit"),
        (REFUND, "Refund"), (ADJUSTMENT, "Adjustment"), (WAIVER, "Waiver"),
    ]

    person = models.ForeignKey(
        Person, on_delete=models.PROTECT, related_name="ledger_entries", db_index=True
    )
    term = models.ForeignKey(
        "academics.Term", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    entry_type = models.CharField(max_length=12, choices=TYPES)
    charge_code = models.ForeignKey(
        ChargeCode, null=True, blank=True, on_delete=models.PROTECT, related_name="entries"
    )
    # Signed: charges positive, payments/credits negative. Balance = SUM.
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    description = models.CharField(max_length=200)
    effective_date = models.DateField()
    posted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    posted_at = models.DateTimeField(auto_now_add=True)
    # Provenance: e.g. the finaid Disbursement that created this credit.
    content_type = models.ForeignKey(ContentType, null=True, blank=True, on_delete=models.SET_NULL)
    object_id = models.CharField(max_length=64, blank=True)
    source = GenericForeignKey("content_type", "object_id")

    class Meta:
        ordering = ["-effective_date", "-posted_at"]
        verbose_name_plural = "ledger entries"

    def __str__(self):
        return f"{self.entry_type} ${self.amount} — {self.person.display_name}"
