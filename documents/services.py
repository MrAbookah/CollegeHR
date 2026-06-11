"""Document services: every upload opens a review task in the owning
department's queue; verification auto-completes any admissions checklist
item waiting on that document type."""

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from core import audit, permissions
from workflow.models import Task
from workflow.services import create_task, notify_user

from .models import Document


@transaction.atomic
def upload_document(*, person, doc_type, file, uploaded_by, related=None,
                    source=Document.UPLOAD):
    kwargs = {}
    if related is not None:
        kwargs["related"] = related  # GenericFK: only set when present, else object_id nulls
    doc = Document.objects.create(
        person=person,
        doc_type=doc_type,
        file=file,
        original_filename=getattr(file, "name", "upload"),
        content_type_header=getattr(file, "content_type", "") or "",
        size=getattr(file, "size", 0) or 0,
        source=source,
        uploaded_by=uploaded_by,
        **kwargs,
    )
    origin_codes = permissions.user_dept_codes(uploaded_by)
    from core.models import Department

    origin = Department.objects.filter(code__in=origin_codes).first()
    create_task(
        title=f"Review document: {doc_type.name} — {person.display_name}",
        task_type=Task.REVIEW_DOCUMENT,
        assigned_department=doc_type.owning_department,
        person=person,
        originating_department=origin,
        related=doc,
        created_by=uploaded_by,
    )
    return doc


@transaction.atomic
def review_document(doc, reviewer, *, verify, note=""):
    if not permissions.is_member_of(reviewer, doc.doc_type.owning_department.code):
        raise PermissionDenied(
            f"Only {doc.doc_type.owning_department.name} can review {doc.doc_type.name} documents."
        )
    if doc.status != Document.PENDING_REVIEW:
        raise ValidationError("This document was already reviewed.")
    doc.status = Document.VERIFIED if verify else Document.REJECTED
    doc.reviewed_by = reviewer
    doc.reviewed_at = timezone.now()
    doc.review_note = note[:255]
    doc.save()

    from workflow.services import _close_task_for

    _close_task_for(doc, Task.APPROVED if verify else Task.REJECTED, reviewer)

    if verify:
        _complete_checklist_items(doc)
    if doc.uploaded_by and doc.uploaded_by != reviewer:
        verdict = "verified" if verify else "rejected"
        notify_user(
            doc.uploaded_by,
            f"Document {verdict}: {doc.doc_type.name} for {doc.person.display_name}",
            url=f"/documents/{doc.pk}/",
            body=note,
        )
    return doc


def _complete_checklist_items(doc):
    from admissions.models import ApplicationChecklistItem

    items = ApplicationChecklistItem.objects.filter(
        application__person=doc.person,
        doc_type=doc.doc_type,
        status=ApplicationChecklistItem.MISSING,
    )
    for item in items:
        item.status = ApplicationChecklistItem.RECEIVED
        item.document = doc
        item.received_at = timezone.now()
        item.save()


def log_document_view(doc, user):
    audit.log(
        "VIEW", doc, person=doc.person, actor=user,
        summary=f"Opened document {doc.doc_type.name} ({doc.original_filename})",
    )
