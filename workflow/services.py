"""
Workflow engine services. All cross-department behavior funnels through
here: task creation and fan-out, hold placement/release with owner-only
guards, hold-based blocking, and the change-request submit/review cycle.
Everything is synchronous and transactional — no brokers, no signals.
"""

from django.apps import apps
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.module_loading import import_string

from core import audit, permissions
from core.audit import serialize_value
from core.models import DataDomain, Department
from workflow.models import ChangeRequest, Hold, HoldType, Notification, Task

# model label -> dotted path called with the saved object after a change
# request is approved and applied, so domain side effects still run
# (ledger posting re-runs hold automation; grade edits recompute points).
POST_APPLY_HOOKS = {
    "student_accounts.ledgerentry": "student_accounts.services.recalculate_account_for_entry",
    "academics.enrollment": "academics.services.apply_grade_fields",
}


# --- Notifications ---------------------------------------------------------

def notify_user(user, title, url="", body=""):
    if user is None:
        return None
    return Notification.objects.create(recipient=user, title=title, url=url, body=body)


def notify_department(department, title, url="", body="", exclude_user=None):
    from core.models import User

    users = User.objects.filter(
        person__staff_memberships__department=department,
        person__staff_memberships__end_date__isnull=True,
        is_active=True,
    ).distinct()
    if exclude_user is not None and exclude_user.pk:
        users = users.exclude(pk=exclude_user.pk)
    Notification.objects.bulk_create(
        [Notification(recipient=u, title=title, url=url, body=body) for u in users]
    )


def mark_read(notification):
    if notification.read_at is None:
        notification.read_at = timezone.now()
        notification.save(update_fields=["read_at"])


# --- Tasks -----------------------------------------------------------------

def create_task(title, task_type, assigned_department, *, person=None,
                originating_department=None, related=None, description="",
                priority=Task.NORMAL, due_date=None, created_by=None, notify=True):
    kwargs = {}
    if related is not None:
        kwargs["related"] = related  # GenericFK: only set when present, else object_id nulls
    task = Task.objects.create(
        title=title,
        description=description,
        task_type=task_type,
        priority=priority,
        due_date=due_date,
        person=person,
        originating_department=originating_department,
        assigned_department=assigned_department,
        created_by=created_by,
        **kwargs,
    )
    if notify:
        origin = f" (from {originating_department.name})" if originating_department else ""
        notify_department(
            assigned_department,
            f"New {task.get_task_type_display().lower()}: {title}{origin}",
            url=reverse("task_detail", args=[task.pk]),
            exclude_user=created_by,
        )
    return task


def claim_task(task, user):
    if not permissions.is_member_of(user, task.assigned_department.code):
        raise PermissionDenied("Only members of the assigned department can claim this task.")
    task.assigned_to = user
    task.status = Task.IN_PROGRESS
    task.save(update_fields=["assigned_to", "status", "updated_at"])
    return task


def complete_task(task, user, outcome=Task.COMPLETED, notify_creator=True):
    if not permissions.is_member_of(user, task.assigned_department.code):
        raise PermissionDenied("Only members of the assigned department can complete this task.")
    task.status = Task.DONE
    task.outcome = outcome
    task.completed_by = user
    task.completed_at = timezone.now()
    task.save(update_fields=["status", "outcome", "completed_by", "completed_at", "updated_at"])
    if notify_creator and task.created_by and task.created_by != user:
        notify_user(
            task.created_by,
            f"Task completed: {task.title}",
            url=reverse("task_detail", args=[task.pk]),
        )
    return task


def _close_task_for(related_obj, outcome, user):
    ct = ContentType.objects.get_for_model(type(related_obj))
    task = Task.objects.filter(
        content_type=ct, object_id=str(related_obj.pk)
    ).exclude(status__in=[Task.DONE, Task.CANCELLED]).first()
    if task:
        task.status = Task.DONE
        task.outcome = outcome
        task.completed_by = user
        task.completed_at = timezone.now()
        task.save(update_fields=["status", "outcome", "completed_by", "completed_at", "updated_at"])
    return task


# --- Holds -----------------------------------------------------------------

def place_hold(person, hold_type, *, reason, amount=None, actor=None, system=False):
    """Place a hold. `system=True` bypasses the department guard for
    automated placement (e.g. past-due balances)."""
    if not system and not permissions.can_place_hold(actor, hold_type):
        raise PermissionDenied(
            f"Only {hold_type.owning_department.name} can place {hold_type.name} holds."
        )
    existing = Hold.objects.filter(
        person=person, hold_type=hold_type, status=Hold.ACTIVE
    ).first()
    if existing:
        return existing
    hold = Hold.objects.create(
        person=person, hold_type=hold_type, reason=reason, amount=amount,
        placed_by=None if system else actor,
    )
    audit.log(
        "HOLD_PLACE", hold, person=person,
        actor=None if system else actor,
        summary=f"{hold_type.name} hold placed: {reason}"[:255],
    )
    return hold


def release_hold(hold, *, actor=None, note="", system=False):
    if not system and not permissions.can_release_hold(actor, hold):
        raise PermissionDenied(
            f"Only {hold.hold_type.owning_department.name} can release this hold."
        )
    if hold.status == Hold.RELEASED:
        return hold
    hold.status = Hold.RELEASED
    hold.released_by = None if system else actor
    hold.released_at = timezone.now()
    hold.release_note = note[:255]
    hold.save(update_fields=["status", "released_by", "released_at", "release_note", "updated_at"])
    audit.log(
        "HOLD_RELEASE", hold, person=hold.person,
        actor=None if system else actor,
        summary=f"{hold.hold_type.name} hold released. {note}"[:255],
    )
    return hold


def check_blocks(person, action):
    """Active holds blocking `action` ('registration' | 'transcript' |
    'graduation'). Single enforcement point for the whole system."""
    flag = {
        "registration": "blocks_registration",
        "transcript": "blocks_transcript",
        "graduation": "blocks_graduation",
    }[action]
    return list(
        Hold.objects.filter(person=person, status=Hold.ACTIVE, **{f"hold_type__{flag}": True})
        .select_related("hold_type", "hold_type__owning_department")
    )


class BlockedByHold(Exception):
    def __init__(self, holds, action):
        self.holds = holds
        self.action = action
        names = "; ".join(
            f"{h.hold_type.name} ({h.hold_type.owning_department.name})" for h in holds
        )
        super().__init__(f"Blocked from {action} by: {names}")


def require_no_blocks(person, action):
    holds = check_blocks(person, action)
    if holds:
        raise BlockedByHold(holds, action)


# --- Change requests -------------------------------------------------------

def build_update_changes(original, modified, field_names):
    """Diff two in-memory instances over `field_names` using the same
    serializer as the audit log, so review-time comparisons agree."""
    changes = {}
    for name in field_names:
        field = type(modified)._meta.get_field(name)
        old_val = serialize_value(field, original)
        new_val = serialize_value(field, modified)
        if old_val != new_val:
            changes[name] = {"old": old_val, "new": new_val}
    return changes


def build_create_changes(instance):
    """Snapshot every concrete field of an unsaved instance (including FKs a
    view set programmatically) so review-time apply can rebuild it whole."""
    changes = {}
    for field in type(instance)._meta.concrete_fields:
        if field.primary_key or field.name in ("created_at", "updated_at"):
            continue
        changes[field.name] = {"new": serialize_value(field, instance)}
    return changes


def submit_change_request(*, actor, person, domain_code, action, model_label,
                          target=None, changes, summary=""):
    """Record a proposed cross-domain change and open a verification task in
    the owning department's queue. Caller decides (per the domain policy)
    whether the underlying save already happened."""
    domain = DataDomain.objects.select_related("owner_department").get(code=domain_code)
    submitted_dept = None
    membership_codes = permissions.user_dept_codes(actor)
    if membership_codes:
        submitted_dept = Department.objects.filter(code__in=membership_codes).first()

    applied = domain.change_policy == DataDomain.APPLY_THEN_VERIFY

    target_kwargs = {}
    if target is not None:
        target_kwargs["target"] = target  # GenericFK: only set when present
    cr = ChangeRequest.objects.create(
        person=person,
        model_label=model_label,
        **target_kwargs,
        action=action,
        data_domain=domain_code,
        proposed_changes=changes,
        applied_immediately=applied,
        submitted_by=actor,
        submitted_department=submitted_dept,
    )
    model_name = apps.get_model(model_label)._meta.verbose_name
    what = summary or f"{cr.get_action_display()} {model_name}"
    flavor = "already applied — needs verification" if applied else "awaiting approval"
    create_task(
        title=f"Verify: {what} for {person.display_name}",
        task_type=Task.VERIFY_CHANGE,
        assigned_department=domain.owner_department,
        person=person,
        originating_department=submitted_dept,
        related=cr,
        description=(
            f"{actor.get_full_name() or actor.username} "
            f"({submitted_dept.name if submitted_dept else 'no department'}) submitted a change "
            f"({flavor}). Review the field-by-field diff and approve or reject."
        ),
        created_by=actor,
    )
    return cr


def _apply_field(obj, field, stored_value):
    if field.is_relation:
        setattr(obj, field.attname, stored_value["pk"] if stored_value else None)
    else:
        setattr(obj, field.name, field.to_python(stored_value))


def _current_matches(obj, field, stored_value):
    current = serialize_value(field, obj)
    if isinstance(current, dict) or isinstance(stored_value, dict):
        cur_pk = current.get("pk") if isinstance(current, dict) else current
        old_pk = stored_value.get("pk") if isinstance(stored_value, dict) else stored_value
        return cur_pk == old_pk
    return current == stored_value


@transaction.atomic
def review_change(cr, reviewer, *, approve, note=""):
    """The owning department's verdict on a change request."""
    if cr.status != ChangeRequest.PENDING:
        raise ValidationError("This change request was already resolved.")
    if not permissions.can_edit_domain(reviewer, cr.data_domain):
        raise PermissionDenied("Only the owning department can review this change.")
    if reviewer == cr.submitted_by and not reviewer.is_superuser:
        raise PermissionDenied("You cannot review your own change request.")

    model = apps.get_model(cr.model_label)
    cr.reviewed_by = reviewer
    cr.reviewed_at = timezone.now()
    cr.review_note = note

    if approve:
        if cr.applied_immediately:
            cr.status = ChangeRequest.APPROVED  # data already live; just sign off
        elif cr.action == ChangeRequest.UPDATE:
            obj = cr.target
            if obj is None:
                cr.status = ChangeRequest.CONFLICT
                cr.review_note = (note + " [Target record no longer exists]").strip()
            else:
                conflicts = [
                    name for name, change in cr.proposed_changes.items()
                    if not _current_matches(obj, model._meta.get_field(name), change.get("old"))
                ]
                if conflicts:
                    cr.status = ChangeRequest.CONFLICT
                    cr.review_note = (
                        note + f" [Conflict: {', '.join(conflicts)} changed since submission]"
                    ).strip()
                else:
                    for name, change in cr.proposed_changes.items():
                        _apply_field(obj, model._meta.get_field(name), change.get("new"))
                    obj.full_clean()
                    obj.save()
                    cr.status = ChangeRequest.APPROVED
                    hook = POST_APPLY_HOOKS.get(cr.model_label)
                    if hook:
                        import_string(hook)(obj)
        elif cr.action == ChangeRequest.CREATE:
            obj = model()
            for name, change in cr.proposed_changes.items():
                _apply_field(obj, model._meta.get_field(name), change.get("new"))
            obj.full_clean()
            obj.save()
            cr.content_type = ContentType.objects.get_for_model(model)
            cr.object_id = str(obj.pk)
            cr.status = ChangeRequest.APPROVED
            hook = POST_APPLY_HOOKS.get(cr.model_label)
            if hook:
                import_string(hook)(obj)
        elif cr.action == ChangeRequest.DELETE:
            if cr.target is not None:
                cr.target.delete()
            cr.status = ChangeRequest.APPROVED
    else:
        if cr.applied_immediately and cr.action == ChangeRequest.UPDATE:
            # Revert the already-applied edit — unless someone changed the
            # field again since, in which case flag instead of clobbering.
            obj = cr.target
            if obj is not None:
                conflicts = [
                    name for name, change in cr.proposed_changes.items()
                    if not _current_matches(obj, model._meta.get_field(name), change.get("new"))
                ]
                if conflicts:
                    cr.status = ChangeRequest.CONFLICT
                    cr.review_note = (
                        note + f" [Could not auto-revert: {', '.join(conflicts)} changed again]"
                    ).strip()
                else:
                    for name, change in cr.proposed_changes.items():
                        _apply_field(obj, model._meta.get_field(name), change.get("old"))
                    obj.full_clean()
                    obj.save()
                    cr.reverted = True
                    cr.status = ChangeRequest.REJECTED
            else:
                cr.status = ChangeRequest.REJECTED
        else:
            cr.status = ChangeRequest.REJECTED

    cr.save()

    verdict = "VERIFY" if cr.status == ChangeRequest.APPROVED else "REJECT"
    audit.log(
        verdict, cr, person=cr.person, actor=reviewer,
        summary=f"CR#{cr.pk} {cr.status.lower()} ({cr.data_domain}): {note}"[:255],
    )
    outcome = Task.APPROVED if cr.status == ChangeRequest.APPROVED else Task.REJECTED
    _close_task_for(cr, outcome, reviewer)

    status_text = {
        ChangeRequest.APPROVED: "approved",
        ChangeRequest.REJECTED: "rejected" + (" and reverted" if cr.reverted else ""),
        ChangeRequest.CONFLICT: "flagged as a conflict",
    }[cr.status]
    notify_user(
        cr.submitted_by,
        f"Your change for {cr.person.display_name} was {status_text}",
        url=reverse("change_detail", args=[cr.pk]),
        body=note,
    )
    return cr
