"""
The cross-department work layer: Tasks routed between offices, Holds with
owner-only release, ChangeRequests ("you enter it, the owning office
verifies it"), and DB-backed Notifications. This is the layer Ellucian
sells separately; here it is the spine of the system.
"""

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models

from core.models import Department, Person, TimeStampedModel


class HoldType(TimeStampedModel):
    code = models.CharField(max_length=30, unique=True)
    name = models.CharField(max_length=100)
    owning_department = models.ForeignKey(
        Department, on_delete=models.PROTECT, related_name="hold_types"
    )
    blocks_registration = models.BooleanField(default=False)
    blocks_transcript = models.BooleanField(default=False)
    blocks_graduation = models.BooleanField(default=False)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return self.name

    @property
    def blocks_summary(self):
        blocked = [
            label
            for flag, label in [
                (self.blocks_registration, "registration"),
                (self.blocks_transcript, "transcript"),
                (self.blocks_graduation, "graduation"),
            ]
            if flag
        ]
        return ", ".join(blocked) or "nothing"


class Hold(TimeStampedModel):
    ACTIVE, RELEASED = "ACTIVE", "RELEASED"
    STATUSES = [(ACTIVE, "Active"), (RELEASED, "Released")]

    person = models.ForeignKey(Person, on_delete=models.PROTECT, related_name="holds")
    hold_type = models.ForeignKey(HoldType, on_delete=models.PROTECT, related_name="holds")
    status = models.CharField(max_length=10, choices=STATUSES, default=ACTIVE, db_index=True)
    reason = models.TextField()
    amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    placed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="holds_placed",
    )  # null = placed automatically by the system
    placed_at = models.DateTimeField(auto_now_add=True)
    released_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="holds_released",
    )
    released_at = models.DateTimeField(null=True, blank=True)
    release_note = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-placed_at"]

    def __str__(self):
        return f"{self.hold_type.code} on {self.person.display_name} ({self.status})"


class Task(TimeStampedModel):
    """The universal cross-department work item. Whatever the trigger —
    a referral, a change awaiting verification, a graduation clearance —
    it lands in exactly one department's queue."""

    VERIFY_CHANGE = "VERIFY_CHANGE"
    REVIEW_DOCUMENT = "REVIEW_DOCUMENT"
    GRADUATION_CLEARANCE = "GRADUATION_CLEARANCE"
    REVIEW_APPLICATION = "REVIEW_APPLICATION"
    REFERRAL = "REFERRAL"
    DATA_FIX = "DATA_FIX"
    GENERIC = "GENERIC"
    TYPES = [
        (VERIFY_CHANGE, "Verify change"), (REVIEW_DOCUMENT, "Review document"),
        (GRADUATION_CLEARANCE, "Graduation clearance"), (REVIEW_APPLICATION, "Review application"),
        (REFERRAL, "Referral"), (DATA_FIX, "Data fix"), (GENERIC, "Task"),
    ]

    OPEN, IN_PROGRESS, DONE, CANCELLED = "OPEN", "IN_PROGRESS", "DONE", "CANCELLED"
    STATUSES = [(OPEN, "Open"), (IN_PROGRESS, "In progress"), (DONE, "Done"), (CANCELLED, "Cancelled")]

    APPROVED, REJECTED, COMPLETED = "APPROVED", "REJECTED", "COMPLETED"
    OUTCOMES = [(APPROVED, "Approved"), (REJECTED, "Rejected"), (COMPLETED, "Completed")]

    LOW, NORMAL, HIGH = "LOW", "NORMAL", "HIGH"
    PRIORITIES = [(LOW, "Low"), (NORMAL, "Normal"), (HIGH, "High")]

    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    task_type = models.CharField(max_length=22, choices=TYPES, default=GENERIC)
    status = models.CharField(max_length=12, choices=STATUSES, default=OPEN, db_index=True)
    outcome = models.CharField(max_length=10, choices=OUTCOMES, blank=True)
    priority = models.CharField(max_length=6, choices=PRIORITIES, default=NORMAL)
    due_date = models.DateField(null=True, blank=True)
    person = models.ForeignKey(
        Person, null=True, blank=True, on_delete=models.PROTECT, related_name="tasks"
    )
    originating_department = models.ForeignKey(
        Department, null=True, blank=True, on_delete=models.PROTECT, related_name="tasks_sent"
    )
    assigned_department = models.ForeignKey(
        Department, on_delete=models.PROTECT, related_name="tasks_queue"
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="tasks_claimed",
    )
    content_type = models.ForeignKey(
        ContentType, null=True, blank=True, on_delete=models.SET_NULL
    )
    object_id = models.CharField(max_length=64, blank=True)
    related = GenericForeignKey("content_type", "object_id")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="tasks_created",
    )
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="tasks_completed",
    )
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["assigned_department", "status"]),
            models.Index(fields=["assigned_to", "status"]),
            models.Index(fields=["person", "status"]),
        ]

    def __str__(self):
        return f"[{self.assigned_department.code}] {self.title}"

    @property
    def is_overdue(self):
        from django.utils import timezone

        return (
            self.due_date is not None
            and self.status in (self.OPEN, self.IN_PROGRESS)
            and self.due_date < timezone.localdate()
        )


class TaskComment(TimeStampedModel):
    """The cross-department conversation that today happens in lost emails."""

    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    body = models.TextField()

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"Comment by {self.author} on task {self.task_id}"


class Notification(models.Model):
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="notifications", db_index=True,
    )
    title = models.CharField(max_length=200)
    body = models.TextField(blank=True)
    url = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["recipient", "read_at"])]

    def __str__(self):
        return f"To {self.recipient}: {self.title}"


class ChangeRequest(TimeStampedModel):
    """A proposed edit to data another department owns.

    APPLY_THEN_VERIFY domains: the edit is already live (the person at the
    counter saw it fixed); the owner verifies after the fact and can revert.
    HOLD_FOR_APPROVAL domains: nothing is written until the owner approves.
    """

    CREATE, UPDATE, DELETE = "CREATE", "UPDATE", "DELETE"
    ACTIONS = [(CREATE, "Create"), (UPDATE, "Update"), (DELETE, "Delete")]

    PENDING, APPROVED, REJECTED, CONFLICT, CANCELLED = (
        "PENDING", "APPROVED", "REJECTED", "CONFLICT", "CANCELLED",
    )
    STATUSES = [
        (PENDING, "Pending"), (APPROVED, "Approved"), (REJECTED, "Rejected"),
        (CONFLICT, "Conflict"), (CANCELLED, "Cancelled"),
    ]

    person = models.ForeignKey(
        Person, on_delete=models.PROTECT, related_name="change_requests", db_index=True
    )
    model_label = models.CharField(max_length=100)
    content_type = models.ForeignKey(
        ContentType, null=True, blank=True, on_delete=models.SET_NULL
    )
    object_id = models.CharField(max_length=64, blank=True)
    target = GenericForeignKey("content_type", "object_id")
    action = models.CharField(max_length=6, choices=ACTIONS, default=UPDATE)
    data_domain = models.CharField(max_length=20)
    proposed_changes = models.JSONField(default=dict, encoder=DjangoJSONEncoder)
    applied_immediately = models.BooleanField(default=False)
    status = models.CharField(max_length=10, choices=STATUSES, default=PENDING, db_index=True)
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="change_requests_submitted"
    )
    submitted_department = models.ForeignKey(
        Department, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    submitted_at = models.DateTimeField(auto_now_add=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="change_requests_reviewed",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.TextField(blank=True)
    reverted = models.BooleanField(default=False)

    class Meta:
        ordering = ["-submitted_at"]

    def __str__(self):
        return f"CR#{self.pk} {self.action} {self.model_label} for {self.person.display_name}"

    @property
    def field_changes(self):
        """[(field, old_display, new_display)] for templates."""
        rows = []
        for field, change in self.proposed_changes.items():
            rows.append((field, _display(change.get("old")), _display(change.get("new"))))
        return rows


def _display(value):
    if isinstance(value, dict) and "display" in value:
        return value["display"]
    if value in (None, ""):
        return "—"
    return value
