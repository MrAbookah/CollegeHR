"""
The person hub: one Person row per human being, forever.

This is Banner's PIDM/SPRIDEN idea done deliberately: every affiliation a
person ever holds (applicant, student, employee, faculty, alumni, donor)
hangs off the same row, so every department sees the same human. Domain
detail (enrollments, paychecks, gifts...) lives in the domain apps, keyed by
a plain FK to Person — never by subclassing, which is how silos form.
"""

from django.contrib.auth.models import AbstractUser
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.db.models import Q


class User(AbstractUser):
    # Reserved column for the future SSO integration: the IdP subject claim
    # maps here so usernames can stay human-friendly.
    sso_subject = models.CharField(max_length=255, blank=True)


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Department(TimeStampedModel):
    code = models.CharField(max_length=10, unique=True)
    name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return self.name


class DataDomain(TimeStampedModel):
    """Governance table: which department owns a slice of data, and what
    happens when somebody else edits it."""

    APPLY_THEN_VERIFY = "APPLY_THEN_VERIFY"
    HOLD_FOR_APPROVAL = "HOLD_FOR_APPROVAL"
    CHANGE_POLICIES = [
        (APPLY_THEN_VERIFY, "Apply immediately, owner verifies after"),
        (HOLD_FOR_APPROVAL, "Hold until owner approves"),
    ]

    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=100)
    owner_department = models.ForeignKey(
        Department, on_delete=models.PROTECT, related_name="owned_domains"
    )
    description = models.TextField(blank=True)
    change_policy = models.CharField(
        max_length=20, choices=CHANGE_POLICIES, default=HOLD_FOR_APPROVAL
    )

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        from core import permissions

        permissions.clear_domain_cache()


class Person(TimeStampedModel):
    college_id = models.CharField(max_length=9, unique=True, blank=True, db_index=True)
    banner_id = models.CharField(
        max_length=20, unique=True, blank=True, null=True,
        help_text="Legacy Ellucian ID, used as the natural key for imports.",
    )
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    middle_name = models.CharField(max_length=100, blank=True)
    preferred_name = models.CharField(max_length=100, blank=True)
    suffix = models.CharField(max_length=20, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    # Only the last four digits are ever stored; the full SSN is deliberately
    # out of scope for this system.
    ssn_last4 = models.CharField(max_length=4, blank=True)
    pronouns = models.CharField(max_length=40, blank=True)
    primary_email = models.EmailField(blank=True, db_index=True)
    primary_phone = models.CharField(max_length=20, blank=True)
    # FERPA directory-information suppression.
    directory_optout = models.BooleanField(default=False)
    deceased = models.BooleanField(default=False)
    deceased_date = models.DateField(null=True, blank=True)
    # Dedup repair: the losing duplicate points at the survivor and every
    # view redirects there.
    merged_into = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="merged_from"
    )
    user = models.OneToOneField(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="person"
    )
    created_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["last_name", "first_name"]
        verbose_name_plural = "people"

    def __str__(self):
        return f"{self.display_name} ({self.college_id})"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.college_id:
            self.college_id = f"C{self.pk:08d}"
            # queryset update: bypasses signals so the audit log doesn't get
            # a noise UPDATE entry for the ID assignment
            type(self).objects.filter(pk=self.pk).update(college_id=self.college_id)

    @property
    def display_name(self):
        first = self.preferred_name or self.first_name
        return f"{first} {self.last_name}"

    @property
    def full_legal_name(self):
        parts = [self.first_name, self.middle_name, self.last_name, self.suffix]
        return " ".join(p for p in parts if p)

    def active_affiliations(self):
        return self.affiliations.filter(status=Affiliation.ACTIVE)

    def active_holds(self):
        return self.holds.filter(status="ACTIVE").select_related(
            "hold_type", "hold_type__owning_department"
        )


class PersonAddress(TimeStampedModel):
    HOME, MAILING, WORK, BILLING = "HOME", "MAILING", "WORK", "BILLING"
    TYPES = [(HOME, "Home"), (MAILING, "Mailing"), (WORK, "Work"), (BILLING, "Billing")]

    person = models.ForeignKey(Person, on_delete=models.PROTECT, related_name="addresses")
    type = models.CharField(max_length=10, choices=TYPES, default=HOME)
    line1 = models.CharField(max_length=120)
    line2 = models.CharField(max_length=120, blank=True)
    city = models.CharField(max_length=80)
    state = models.CharField(max_length=2)
    postal_code = models.CharField(max_length=10)
    country = models.CharField(max_length=2, default="US")
    is_primary = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name_plural = "person addresses"

    def __str__(self):
        return f"{self.get_type_display()}: {self.line1}, {self.city} {self.state}"


class EmergencyContact(TimeStampedModel):
    person = models.ForeignKey(Person, on_delete=models.PROTECT, related_name="emergency_contacts")
    name = models.CharField(max_length=120)
    relationship = models.CharField(max_length=50)
    phone = models.CharField(max_length=20)
    email = models.EmailField(blank=True)
    priority = models.PositiveSmallIntegerField(default=1)

    class Meta:
        ordering = ["priority"]

    def __str__(self):
        return f"{self.name} ({self.relationship})"


class Affiliation(TimeStampedModel):
    """A person's relationship to the college. People accumulate these over a
    lifetime and can hold several at once — that's the whole point."""

    APPLICANT, STUDENT, EMPLOYEE, FACULTY = "APPLICANT", "STUDENT", "EMPLOYEE", "FACULTY"
    ALUMNI, DONOR, RETIREE = "ALUMNI", "DONOR", "RETIREE"
    TYPES = [
        (APPLICANT, "Applicant"), (STUDENT, "Student"), (EMPLOYEE, "Employee"),
        (FACULTY, "Faculty"), (ALUMNI, "Alumni"), (DONOR, "Donor"), (RETIREE, "Retiree"),
    ]
    ACTIVE, INACTIVE, PENDING = "ACTIVE", "INACTIVE", "PENDING"
    STATUSES = [(ACTIVE, "Active"), (INACTIVE, "Inactive"), (PENDING, "Pending")]

    person = models.ForeignKey(Person, on_delete=models.PROTECT, related_name="affiliations")
    type = models.CharField(max_length=10, choices=TYPES)
    status = models.CharField(max_length=10, choices=STATUSES, default=ACTIVE)
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["type"]
        constraints = [
            models.UniqueConstraint(
                fields=["person", "type"],
                condition=Q(status="ACTIVE"),
                name="uniq_active_affiliation_per_type",
            )
        ]

    def __str__(self):
        return f"{self.person.display_name}: {self.get_type_display()} ({self.status})"


class StaffMembership(TimeStampedModel):
    """Which office(s) a staff/faculty member works in. Drives every
    department-scoped permission in the system."""

    STAFF, MANAGER = "STAFF", "MANAGER"
    ROLES = [(STAFF, "Staff"), (MANAGER, "Manager")]

    person = models.ForeignKey(Person, on_delete=models.PROTECT, related_name="staff_memberships")
    department = models.ForeignKey(Department, on_delete=models.PROTECT, related_name="members")
    role = models.CharField(max_length=10, choices=ROLES, default=STAFF)
    is_primary = models.BooleanField(default=True)
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)

    def __str__(self):
        return f"{self.person.display_name} — {self.department.code} ({self.role})"

    @property
    def is_current(self):
        return self.end_date is None


class AuditLog(models.Model):
    """Append-only, FERPA-grade trail. Every create/update/delete on audited
    models lands here automatically (core/audit.py); sensitive reads and
    workflow verdicts are written explicitly."""

    CREATE, UPDATE, DELETE, VIEW = "CREATE", "UPDATE", "DELETE", "VIEW"
    LOGIN, VERIFY, REJECT = "LOGIN", "VERIFY", "REJECT"
    HOLD_PLACE, HOLD_RELEASE = "HOLD_PLACE", "HOLD_RELEASE"
    MERGE, EXPORT, OVERRIDE = "MERGE", "EXPORT", "OVERRIDE"
    ACTIONS = [
        (CREATE, "Create"), (UPDATE, "Update"), (DELETE, "Delete"), (VIEW, "View"),
        (LOGIN, "Login"), (VERIFY, "Verify"), (REJECT, "Reject"),
        (HOLD_PLACE, "Hold placed"), (HOLD_RELEASE, "Hold released"),
        (MERGE, "Merge"), (EXPORT, "Export"), (OVERRIDE, "Override"),
    ]

    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    actor = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="audit_entries"
    )  # null = the system itself
    action = models.CharField(max_length=12, choices=ACTIONS)
    content_type = models.ForeignKey(
        "contenttypes.ContentType", null=True, blank=True, on_delete=models.SET_NULL
    )
    object_id = models.CharField(max_length=64, blank=True)
    # Denormalized so "everything that touched this student" is one query —
    # the FERPA disclosure report.
    person = models.ForeignKey(
        Person, null=True, blank=True, on_delete=models.PROTECT, related_name="audit_entries"
    )
    changes = models.JSONField(default=dict, blank=True, encoder=DjangoJSONEncoder)
    summary = models.CharField(max_length=255, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ["-timestamp"]
        indexes = [models.Index(fields=["person", "-timestamp"])]

    def __str__(self):
        return f"{self.timestamp:%Y-%m-%d %H:%M} {self.action} {self.summary}"

    def save(self, *args, **kwargs):
        # Application-level immutability; production deploys should also
        # REVOKE UPDATE, DELETE on this table in Postgres.
        if self.pk is not None:
            raise RuntimeError("AuditLog entries are immutable")
        super().save(*args, **kwargs)
