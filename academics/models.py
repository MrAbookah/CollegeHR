"""Registrar domain: catalog, scheduling, registration, grades, programs,
and graduation. Owned by REG; all writes by other offices route through
change requests (HOLD_FOR_APPROVAL)."""

from django.conf import settings
from django.db import models

from core.models import Department, Person, TimeStampedModel


class Term(TimeStampedModel):
    code = models.CharField(max_length=10, unique=True)  # e.g. 2026FA
    name = models.CharField(max_length=50)
    start_date = models.DateField()
    end_date = models.DateField()
    registration_opens = models.DateField()
    registration_closes = models.DateField()
    grades_due = models.DateField()
    is_current = models.BooleanField(default=False)

    class Meta:
        ordering = ["-start_date"]

    def __str__(self):
        return self.name


class Subject(TimeStampedModel):
    """Academic discipline (BIO, MATH). Deliberately distinct from the
    administrative Department table."""

    code = models.CharField(max_length=6, unique=True)
    name = models.CharField(max_length=100)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} — {self.name}"


class Course(TimeStampedModel):
    subject = models.ForeignKey(Subject, on_delete=models.PROTECT, related_name="courses")
    number = models.CharField(max_length=4)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    credits = models.DecimalField(max_digits=3, decimal_places=1)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["subject__code", "number"]
        constraints = [
            models.UniqueConstraint(fields=["subject", "number"], name="uniq_course_code")
        ]

    def __str__(self):
        return f"{self.subject.code} {self.number}: {self.title}"

    @property
    def code(self):
        return f"{self.subject.code} {self.number}"


class Section(TimeStampedModel):
    OPEN, CLOSED, CANCELLED = "OPEN", "CLOSED", "CANCELLED"
    STATUSES = [(OPEN, "Open"), (CLOSED, "Closed"), (CANCELLED, "Cancelled")]

    course = models.ForeignKey(Course, on_delete=models.PROTECT, related_name="sections")
    term = models.ForeignKey(Term, on_delete=models.PROTECT, related_name="sections")
    section_number = models.CharField(max_length=3)
    instructor = models.ForeignKey(
        Person, null=True, blank=True, on_delete=models.PROTECT, related_name="sections_taught"
    )
    capacity = models.PositiveSmallIntegerField(default=30)
    days = models.CharField(max_length=7, blank=True, help_text="e.g. MWF or TR")
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)
    room = models.CharField(max_length=20, blank=True)
    status = models.CharField(max_length=10, choices=STATUSES, default=OPEN)

    class Meta:
        ordering = ["course__subject__code", "course__number", "section_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["course", "term", "section_number"], name="uniq_section"
            )
        ]

    def __str__(self):
        return f"{self.course.code}-{self.section_number} ({self.term.code})"

    @property
    def seats_taken(self):
        return self.enrollments.filter(status=Enrollment.REGISTERED).count()

    @property
    def seats_remaining(self):
        return max(self.capacity - self.seats_taken, 0)

    @property
    def schedule_display(self):
        if not self.days or not self.start_time:
            return "TBA"
        return f"{self.days} {self.start_time:%H:%M}–{self.end_time:%H:%M}"


class Enrollment(TimeStampedModel):
    data_domain = "ACADEMIC"

    REGISTERED, DROPPED, WITHDRAWN, COMPLETED = (
        "REGISTERED", "DROPPED", "WITHDRAWN", "COMPLETED",
    )
    STATUSES = [
        (REGISTERED, "Registered"), (DROPPED, "Dropped"),
        (WITHDRAWN, "Withdrawn"), (COMPLETED, "Completed"),
    ]

    person = models.ForeignKey(Person, on_delete=models.PROTECT, related_name="enrollments")
    section = models.ForeignKey(Section, on_delete=models.PROTECT, related_name="enrollments")
    status = models.CharField(max_length=10, choices=STATUSES, default=REGISTERED)
    registered_at = models.DateTimeField(auto_now_add=True)
    dropped_at = models.DateTimeField(null=True, blank=True)
    grade = models.CharField(max_length=3, blank=True)
    grade_points = models.DecimalField(max_digits=3, decimal_places=2, null=True, blank=True)
    graded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    graded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["person", "section"], name="uniq_enrollment")
        ]

    def __str__(self):
        return f"{self.person.display_name} in {self.section} [{self.status}]"


class Program(TimeStampedModel):
    BA, BS, AA, CERT = "BA", "BS", "AA", "CERT"
    DEGREES = [(BA, "B.A."), (BS, "B.S."), (AA, "A.A."), (CERT, "Certificate")]

    code = models.CharField(max_length=12, unique=True)
    name = models.CharField(max_length=120)
    degree = models.CharField(max_length=6, choices=DEGREES)
    total_credits_required = models.DecimalField(max_digits=4, decimal_places=1)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return f"{self.name} ({self.get_degree_display()})"


class ProgramRequirement(TimeStampedModel):
    program = models.ForeignKey(Program, on_delete=models.CASCADE, related_name="requirements")
    category = models.CharField(max_length=50)  # "Major Core", "Gen Ed", "Electives"
    credits_required = models.DecimalField(max_digits=4, decimal_places=1)
    # Blank = any course counts (electives).
    applicable_courses = models.ManyToManyField(Course, blank=True)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order"]

    def __str__(self):
        return f"{self.program.code}: {self.category} ({self.credits_required} cr)"


class StudentProgram(TimeStampedModel):
    ACTIVE, COMPLETED, WITHDRAWN = "ACTIVE", "COMPLETED", "WITHDRAWN"
    STATUSES = [(ACTIVE, "Active"), (COMPLETED, "Completed"), (WITHDRAWN, "Withdrawn")]

    person = models.ForeignKey(Person, on_delete=models.PROTECT, related_name="student_programs")
    program = models.ForeignKey(Program, on_delete=models.PROTECT, related_name="students")
    catalog_year = models.CharField(max_length=9)  # "2024-25"
    status = models.CharField(max_length=10, choices=STATUSES, default=ACTIVE)
    declared_date = models.DateField()
    advisor = models.ForeignKey(
        Person, null=True, blank=True, on_delete=models.SET_NULL, related_name="advisees"
    )

    def __str__(self):
        return f"{self.person.display_name} — {self.program.code} ({self.status})"


class GraduationApplication(TimeStampedModel):
    """The cross-department showcase: submitting one fans clearance items
    out to every office that has a say."""

    SUBMITTED, IN_REVIEW, CLEARED, AWARDED, DENIED = (
        "SUBMITTED", "IN_REVIEW", "CLEARED", "AWARDED", "DENIED",
    )
    STATUSES = [
        (SUBMITTED, "Submitted"), (IN_REVIEW, "In review"), (CLEARED, "Cleared"),
        (AWARDED, "Awarded"), (DENIED, "Denied"),
    ]

    person = models.ForeignKey(Person, on_delete=models.PROTECT, related_name="graduation_applications")
    student_program = models.ForeignKey(StudentProgram, on_delete=models.PROTECT, related_name="graduation_applications")
    term = models.ForeignKey(Term, on_delete=models.PROTECT, related_name="graduation_applications")
    status = models.CharField(max_length=10, choices=STATUSES, default=SUBMITTED, db_index=True)
    submitted_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-submitted_at"]

    def __str__(self):
        return f"{self.person.display_name} — {self.student_program.program.code} ({self.term.code})"


class ClearanceItem(TimeStampedModel):
    PENDING, CLEARED, FLAGGED = "PENDING", "CLEARED", "FLAGGED"
    STATUSES = [(PENDING, "Pending"), (CLEARED, "Cleared"), (FLAGGED, "Flagged")]

    application = models.ForeignKey(
        GraduationApplication, on_delete=models.CASCADE, related_name="clearance_items"
    )
    department = models.ForeignKey(Department, on_delete=models.PROTECT, related_name="+")
    item = models.CharField(max_length=100)
    status = models.CharField(max_length=10, choices=STATUSES, default=PENDING)
    cleared_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    cleared_at = models.DateTimeField(null=True, blank=True)
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["department__code"]

    def __str__(self):
        return f"[{self.department.code}] {self.item}: {self.status}"
