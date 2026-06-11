from django import template
from django.contrib.contenttypes.models import ContentType

register = template.Library()


@register.filter
def money(value):
    if value in (None, ""):
        return "—"
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return value
    sign = "-" if amount < 0 else ""
    return f"{sign}${abs(amount):,.2f}"


@register.filter
def pending_crs(obj):
    """PENDING change requests targeting this object — powers the
    'unverified change' badge without polluting every model with a flag."""
    from workflow.models import ChangeRequest

    if obj is None or obj.pk is None:
        return 0
    ct = ContentType.objects.get_for_model(type(obj))
    return ChangeRequest.objects.filter(
        content_type=ct, object_id=str(obj.pk), status=ChangeRequest.PENDING
    ).count()


@register.filter
def status_class(status):
    """Map model status codes to a badge color class."""
    good = {"ACTIVE", "CLEARED", "AWARDED", "VERIFIED", "APPROVED", "DONE", "POSTED",
            "ENROLLED", "ACCEPTED", "COMPLETED", "REGISTERED", "RECEIVED", "DISBURSED",
            "FULFILLED", "OPEN"}
    bad = {"REJECTED", "DENIED", "FLAGGED", "CONFLICT", "DEFAULTED", "TERMINATED",
           "WITHDRAWN", "MISSING", "CANCELLED"}
    warn = {"PENDING", "PENDING_REVIEW", "IN_REVIEW", "SUBMITTED", "HOLD", "OFFERED",
            "IN_PROGRESS", "WAITLISTED", "DRAFT", "ON_LEAVE", "SCHEDULED", "INQUIRY"}
    if status in good:
        return "badge-good"
    if status in bad:
        return "badge-bad"
    if status in warn:
        return "badge-warn"
    return "badge-muted"
