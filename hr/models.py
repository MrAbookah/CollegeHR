"""HR / payroll: positions, employment records, and simple payroll runs.
EMPLOYMENT data is readable only by HR; the salary field is sensitive even
within views that show the rest of the record."""

from django.db import models

from core.models import Department, Person, TimeStampedModel


class Position(TimeStampedModel):
    """Position control, Banner-style: the job title is a budgeted line that
    ties together its department (org segment) and the GL account that funds
    it. A person fills a position; the money traces through these segments."""

    position_number = models.CharField(max_length=10, unique=True)
    title = models.CharField(max_length=120)
    department = models.ForeignKey(Department, on_delete=models.PROTECT, related_name="positions")
    gl_account = models.ForeignKey(
        "finance.GLAccount", null=True, blank=True, on_delete=models.PROTECT,
        related_name="positions", help_text="Salary expense account funding this position.",
    )
    is_faculty = models.BooleanField(default=False)
    fte = models.DecimalField(max_digits=3, decimal_places=2, default=1)
    pay_grade = models.CharField(max_length=10, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["position_number"]

    def __str__(self):
        return f"{self.position_number} — {self.title}"


class EmploymentRecord(TimeStampedModel):
    data_domain = "EMPLOYMENT"

    ACTIVE, ON_LEAVE, TERMINATED = "ACTIVE", "ON_LEAVE", "TERMINATED"
    STATUSES = [(ACTIVE, "Active"), (ON_LEAVE, "On leave"), (TERMINATED, "Terminated")]
    SALARY, HOURLY = "SALARY", "HOURLY"
    PAY_BASES = [(SALARY, "Salaried"), (HOURLY, "Hourly")]

    person = models.ForeignKey(Person, on_delete=models.PROTECT, related_name="employment_records")
    position = models.ForeignKey(Position, on_delete=models.PROTECT, related_name="employment_records")
    status = models.CharField(max_length=10, choices=STATUSES, default=ACTIVE)
    hire_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    salary = models.DecimalField(max_digits=10, decimal_places=2)  # sensitive: HR-only
    pay_basis = models.CharField(max_length=6, choices=PAY_BASES, default=SALARY)
    supervisor = models.ForeignKey(
        Person, null=True, blank=True, on_delete=models.SET_NULL, related_name="direct_reports"
    )

    class Meta:
        ordering = ["-hire_date"]

    def __str__(self):
        return f"{self.person.display_name} — {self.position.title} [{self.status}]"


class PayrollRun(TimeStampedModel):
    DRAFT, POSTED = "DRAFT", "POSTED"
    STATUSES = [(DRAFT, "Draft"), (POSTED, "Posted")]

    period_start = models.DateField()
    period_end = models.DateField()
    pay_date = models.DateField()
    status = models.CharField(max_length=10, choices=STATUSES, default=DRAFT)

    class Meta:
        ordering = ["-pay_date"]

    def __str__(self):
        return f"Payroll {self.period_start} – {self.period_end} [{self.status}]"


class Paycheck(TimeStampedModel):
    payroll_run = models.ForeignKey(PayrollRun, on_delete=models.PROTECT, related_name="paychecks")
    person = models.ForeignKey(Person, on_delete=models.PROTECT, related_name="paychecks")
    gross = models.DecimalField(max_digits=10, decimal_places=2)
    taxes = models.DecimalField(max_digits=10, decimal_places=2)
    net = models.DecimalField(max_digits=10, decimal_places=2)

    def __str__(self):
        return f"{self.person.display_name} {self.payroll_run.pay_date}: ${self.net}"
