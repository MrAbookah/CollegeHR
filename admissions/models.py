"""Admissions (Slate-lite): the applicant pipeline. Applicants enter through
the same search-before-create gate as everyone else, so a returning alum who
applies again reuses their Person row."""

from django.conf import settings
from django.db import models

from core.models import Person, TimeStampedModel


class Application(TimeStampedModel):
    data_domain = "ADMISSIONS"

    INQUIRY, APPLIED, IN_REVIEW, ADMITTED = "INQUIRY", "APPLIED", "IN_REVIEW", "ADMITTED"
    WAITLISTED, DENIED, DEPOSITED, ENROLLED, WITHDRAWN = (
        "WAITLISTED", "DENIED", "DEPOSITED", "ENROLLED", "WITHDRAWN",
    )
    STAGES = [
        (INQUIRY, "Inquiry"), (APPLIED, "Applied"), (IN_REVIEW, "In review"),
        (ADMITTED, "Admitted"), (WAITLISTED, "Waitlisted"), (DENIED, "Denied"),
        (DEPOSITED, "Deposited"), (ENROLLED, "Enrolled"), (WITHDRAWN, "Withdrawn"),
    ]
    # Stage -> stages reachable from it. The pipeline board renders buttons
    # straight from this map.
    TRANSITIONS = {
        INQUIRY: [APPLIED, WITHDRAWN],
        APPLIED: [IN_REVIEW, WITHDRAWN],
        IN_REVIEW: [ADMITTED, WAITLISTED, DENIED],
        WAITLISTED: [ADMITTED, DENIED, WITHDRAWN],
        ADMITTED: [DEPOSITED, WITHDRAWN],
        DEPOSITED: [ENROLLED, WITHDRAWN],
        ENROLLED: [],
        DENIED: [],
        WITHDRAWN: [],
    }

    WEB, FAIR, REFERRAL, TRANSFER = "WEB", "FAIR", "REFERRAL", "TRANSFER"
    SOURCES = [(WEB, "Web"), (FAIR, "College fair"), (REFERRAL, "Referral"), (TRANSFER, "Transfer")]

    person = models.ForeignKey(Person, on_delete=models.PROTECT, related_name="applications")
    term = models.ForeignKey("academics.Term", on_delete=models.PROTECT, related_name="applications")
    program = models.ForeignKey("academics.Program", on_delete=models.PROTECT, related_name="applications")
    stage = models.CharField(max_length=10, choices=STAGES, default=INQUIRY, db_index=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    deposit_paid_at = models.DateTimeField(null=True, blank=True)
    high_school = models.CharField(max_length=120, blank=True)
    gpa_reported = models.DecimalField(max_digits=3, decimal_places=2, null=True, blank=True)
    source = models.CharField(max_length=10, choices=SOURCES, default=WEB)
    counselor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="applications_counseled",
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.person.display_name} → {self.program.code} ({self.term.code}) [{self.stage}]"

    @property
    def next_stages(self):
        return self.TRANSITIONS.get(self.stage, [])

    @property
    def checklist_complete(self):
        return not self.checklist.filter(
            required=True, status=ApplicationChecklistItem.MISSING
        ).exists()


class ApplicationChecklistItem(TimeStampedModel):
    MISSING, RECEIVED, WAIVED = "MISSING", "RECEIVED", "WAIVED"
    STATUSES = [(MISSING, "Missing"), (RECEIVED, "Received"), (WAIVED, "Waived")]

    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name="checklist")
    name = models.CharField(max_length=80)
    doc_type = models.ForeignKey(
        "documents.DocumentType", null=True, blank=True, on_delete=models.SET_NULL
    )
    required = models.BooleanField(default=True)
    status = models.CharField(max_length=10, choices=STATUSES, default=MISSING)
    document = models.ForeignKey(
        "documents.Document", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    received_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.name} [{self.status}]"


class CommunicationLog(TimeStampedModel):
    EMAIL, PHONE, VISIT, TEXT = "EMAIL", "PHONE", "VISIT", "TEXT"
    CHANNELS = [(EMAIL, "Email"), (PHONE, "Phone"), (VISIT, "Visit"), (TEXT, "Text")]
    IN, OUT = "IN", "OUT"
    DIRECTIONS = [(IN, "Inbound"), (OUT, "Outbound")]

    person = models.ForeignKey(Person, on_delete=models.PROTECT, related_name="communications")
    application = models.ForeignKey(
        Application, null=True, blank=True, on_delete=models.SET_NULL, related_name="communications"
    )
    channel = models.CharField(max_length=6, choices=CHANNELS)
    direction = models.CharField(max_length=3, choices=DIRECTIONS, default=OUT)
    subject = models.CharField(max_length=200)
    notes = models.TextField(blank=True)
    logged_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    occurred_at = models.DateTimeField()

    class Meta:
        ordering = ["-occurred_at"]

    def __str__(self):
        return f"{self.get_channel_display()} {self.direction}: {self.subject}"
