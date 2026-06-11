"""
Automatic field-level audit capture.

Models are registered in core.apps.CoreConfig.ready(). On every save of a
registered model we diff the old row against the new one and write an
immutable AuditLog entry attributed to the current request's user (or the
system, for service-initiated writes).
"""

import contextlib
import datetime
import threading
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.db.models.signals import post_delete, post_save, pre_save

from core.middleware import get_current_ip, get_current_user

_registry = set()
_EXCLUDED_FIELDS = {"created_at", "updated_at"}
_suppress = threading.local()


@contextlib.contextmanager
def suppressed():
    """Disable audit capture inside the block. Only for housekeeping that
    must not generate trail entries (e.g. seed --flush teardown)."""
    _suppress.on = True
    try:
        yield
    finally:
        _suppress.on = False


def _is_suppressed():
    return getattr(_suppress, "on", False)


def serialize_value(field, instance):
    """Canonical JSON-safe representation of a field value. The change-request
    engine reuses this so submit-time and review-time comparisons agree."""
    if field.is_relation:
        pk = getattr(instance, field.attname)
        if pk is None:
            return None
        related = getattr(instance, field.name, None)
        return {"pk": pk, "display": str(related) if related else str(pk)}
    value = getattr(instance, field.attname)
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (datetime.date, datetime.datetime, datetime.time, Decimal)):
        return str(value)
    return str(value)


def diff_instances(old, new):
    changes = {}
    for field in new._meta.concrete_fields:
        if field.primary_key or field.name in _EXCLUDED_FIELDS:
            continue
        if getattr(old, field.attname) != getattr(new, field.attname):
            changes[field.name] = {
                "old": serialize_value(field, old),
                "new": serialize_value(field, new),
            }
    return changes


def snapshot(instance):
    snap = {}
    for field in instance._meta.concrete_fields:
        if field.primary_key or field.name in _EXCLUDED_FIELDS:
            continue
        value = serialize_value(field, instance)
        if value not in (None, "", False):
            snap[field.name] = {"new": value}
    return snap


def _person_id_for(instance):
    from core.models import Person

    if isinstance(instance, Person):
        return instance.pk
    return getattr(instance, "person_id", None)


def log(action, instance=None, *, person=None, summary="", changes=None, actor=None):
    """Write one immutable audit entry. `actor` defaults to the current
    request user; pass actor=None from services for system-initiated writes
    only when no request is in flight."""
    from core.models import AuditLog

    entry = AuditLog(
        actor=actor if actor is not None else get_current_user(),
        action=action,
        changes=changes or {},
        summary=summary[:255],
        ip_address=get_current_ip(),
    )
    if instance is not None:
        entry.content_type = ContentType.objects.get_for_model(type(instance))
        entry.object_id = str(instance.pk)
        entry.person_id = person.pk if person is not None else _person_id_for(instance)
    elif person is not None:
        entry.person_id = person.pk
    entry.save()
    return entry


def _pre_save(sender, instance, **kwargs):
    if _is_suppressed():
        instance._audit_changes = None
        return
    if instance.pk:
        try:
            old = sender.objects.get(pk=instance.pk)
        except sender.DoesNotExist:
            instance._audit_changes = None
            return
        instance._audit_changes = diff_instances(old, instance)
    else:
        instance._audit_changes = None


def _post_save(sender, instance, created, **kwargs):
    if _is_suppressed():
        return
    label = sender._meta.verbose_name
    if created:
        log("CREATE", instance, summary=f"Created {label}: {instance}", changes=snapshot(instance))
    else:
        changes = getattr(instance, "_audit_changes", None)
        if changes:
            fields = ", ".join(changes)
            log("UPDATE", instance, summary=f"Updated {label} ({fields}): {instance}", changes=changes)


def _post_delete(sender, instance, **kwargs):
    if _is_suppressed():
        return
    log("DELETE", instance, summary=f"Deleted {sender._meta.verbose_name}: {instance}")


def register(*models):
    for model in models:
        if model in _registry:
            continue
        _registry.add(model)
        uid = f"audit-{model._meta.label_lower}"
        pre_save.connect(_pre_save, sender=model, dispatch_uid=f"{uid}-pre")
        post_save.connect(_post_save, sender=model, dispatch_uid=f"{uid}-post")
        post_delete.connect(_post_delete, sender=model, dispatch_uid=f"{uid}-del")
