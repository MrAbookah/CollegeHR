"""Advancement: gifts, pledges, and alumni records. The first gift makes a
DONOR affiliation appear on the person automatically; graduation creates the
ALUMNI one. Cradle to grave on a single person row."""

from django.db import models

from core.models import Person, TimeStampedModel


class Designation(TimeStampedModel):
    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=120)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return self.name


class Pledge(TimeStampedModel):
    MONTHLY, QUARTERLY, ANNUAL, ONE_TIME = "MONTHLY", "QUARTERLY", "ANNUAL", "ONE_TIME"
    FREQUENCIES = [
        (MONTHLY, "Monthly"), (QUARTERLY, "Quarterly"),
        (ANNUAL, "Annual"), (ONE_TIME, "One-time"),
    ]
    ACTIVE, FULFILLED, DEFAULTED = "ACTIVE", "FULFILLED", "DEFAULTED"
    STATUSES = [(ACTIVE, "Active"), (FULFILLED, "Fulfilled"), (DEFAULTED, "Defaulted")]

    person = models.ForeignKey(Person, on_delete=models.PROTECT, related_name="pledges")
    designation = models.ForeignKey(Designation, on_delete=models.PROTECT, related_name="pledges")
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    start_date = models.DateField()
    frequency = models.CharField(max_length=10, choices=FREQUENCIES, default=ONE_TIME)
    status = models.CharField(max_length=10, choices=STATUSES, default=ACTIVE)

    class Meta:
        ordering = ["-start_date"]

    def __str__(self):
        return f"{self.person.display_name}: ${self.total_amount} to {self.designation} ({self.status})"

    @property
    def fulfilled_amount(self):
        from django.db.models import Sum

        return self.gifts.aggregate(total=Sum("amount"))["total"] or 0


class Gift(TimeStampedModel):
    data_domain = "ADVANCEMENT"

    CHECK, CARD, STOCK, CASH, PAYROLL = "CHECK", "CARD", "STOCK", "CASH", "PAYROLL"
    METHODS = [
        (CHECK, "Check"), (CARD, "Card"), (STOCK, "Stock"),
        (CASH, "Cash"), (PAYROLL, "Payroll deduction"),
    ]

    person = models.ForeignKey(Person, on_delete=models.PROTECT, related_name="gifts")
    designation = models.ForeignKey(Designation, on_delete=models.PROTECT, related_name="gifts")
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    gift_date = models.DateField()
    method = models.CharField(max_length=10, choices=METHODS, default=CHECK)
    pledge = models.ForeignKey(
        Pledge, null=True, blank=True, on_delete=models.SET_NULL, related_name="gifts"
    )
    receipt_number = models.CharField(max_length=20, unique=True, blank=True)
    acknowledged = models.BooleanField(default=False)
    acknowledged_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-gift_date"]

    def __str__(self):
        return f"${self.amount} from {self.person.display_name} ({self.gift_date})"


class AlumniInfo(TimeStampedModel):
    person = models.OneToOneField(Person, on_delete=models.PROTECT, related_name="alumni_info")
    class_year = models.PositiveSmallIntegerField(null=True, blank=True)
    degree_received = models.CharField(max_length=80, blank=True)
    employer = models.CharField(max_length=120, blank=True)
    job_title = models.CharField(max_length=120, blank=True)
    do_not_solicit = models.BooleanField(default=False)

    class Meta:
        verbose_name_plural = "alumni info"

    def __str__(self):
        return f"{self.person.display_name} '{str(self.class_year)[-2:] if self.class_year else '?'}"
