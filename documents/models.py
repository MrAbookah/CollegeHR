"""Perceptive Content replacement: documents captured against the person
record and routed through the owning department's review queue."""

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from core.models import Department, Person, TimeStampedModel


class DocumentType(TimeStampedModel):
    code = models.CharField(max_length=30, unique=True)
    name = models.CharField(max_length=100)
    owning_department = models.ForeignKey(
        Department, on_delete=models.PROTECT, related_name="document_types"
    )
    data_domain = models.CharField(max_length=20, default="DOCUMENT")
    retention_note = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return self.name


class Document(TimeStampedModel):
    data_domain = "DOCUMENT"

    PENDING_REVIEW, VERIFIED, REJECTED = "PENDING_REVIEW", "VERIFIED", "REJECTED"
    STATUSES = [
        (PENDING_REVIEW, "Pending review"), (VERIFIED, "Verified"), (REJECTED, "Rejected"),
    ]
    UPLOAD, SCAN, EMAIL = "UPLOAD", "SCAN", "EMAIL"
    SOURCES = [(UPLOAD, "Upload"), (SCAN, "Scan"), (EMAIL, "Email")]

    person = models.ForeignKey(Person, on_delete=models.PROTECT, related_name="documents")
    doc_type = models.ForeignKey(DocumentType, on_delete=models.PROTECT, related_name="documents")
    file = models.FileField(upload_to="documents/%Y/%m/")
    original_filename = models.CharField(max_length=255)
    content_type_header = models.CharField(max_length=100, blank=True)
    size = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=15, choices=STATUSES, default=PENDING_REVIEW, db_index=True)
    source = models.CharField(max_length=10, choices=SOURCES, default=UPLOAD)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="documents_uploaded",
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.CharField(max_length=255, blank=True)
    # Optional link to the business object this document supports
    # (an admissions Application, a GraduationApplication, ...).
    content_type = models.ForeignKey(ContentType, null=True, blank=True, on_delete=models.SET_NULL)
    object_id = models.CharField(max_length=64, blank=True)
    related = GenericForeignKey("content_type", "object_id")

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.doc_type.name} for {self.person.display_name} [{self.status}]"
