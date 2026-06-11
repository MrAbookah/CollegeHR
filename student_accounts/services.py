"""Bursar services. Every posting runs the hold automation synchronously:
go past due and the registration hold appears; pay it off and the hold
releases itself (with an audit entry and a heads-up to the advisor)."""

from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.urls import reverse
from django.utils import timezone

from workflow.models import Hold, HoldType
from workflow.services import notify_user, place_hold, release_hold

HOLD_THRESHOLD = Decimal("500.00")


def balance(person):
    return person.ledger_entries.aggregate(total=Sum("amount"))["total"] or Decimal("0")


@transaction.atomic
def post_entry(person, *, entry_type, amount, description, effective_date=None,
               term=None, charge_code=None, posted_by=None, source=None):
    from .models import LedgerEntry

    kwargs = {}
    if source is not None:
        kwargs["source"] = source  # GenericFK: only set when present, else object_id nulls
    entry = LedgerEntry.objects.create(
        person=person,
        term=term,
        entry_type=entry_type,
        charge_code=charge_code,
        amount=amount,
        description=description,
        effective_date=effective_date or timezone.localdate(),
        posted_by=posted_by,
        **kwargs,
    )
    recalculate_account(person)
    return entry


def recalculate_account_for_entry(entry):
    """POST_APPLY hook: an approved change-request that created a ledger
    entry still triggers the hold automation."""
    recalculate_account(entry.person)


def recalculate_account(person):
    bal = balance(person)
    try:
        hold_type = HoldType.objects.get(code="BURSAR_BALANCE")
    except HoldType.DoesNotExist:
        return bal

    active = Hold.objects.filter(
        person=person, hold_type=hold_type, status=Hold.ACTIVE
    ).first()

    if bal > HOLD_THRESHOLD and not active:
        place_hold(
            person, hold_type,
            reason=f"Past-due balance ${bal}",
            amount=bal,
            system=True,
        )
    elif bal <= 0 and active:
        release_hold(active, note=f"Auto-released: balance ${bal}", system=True)
        _notify_advisor(person, hold_type)
    elif active and active.amount != bal and bal > 0:
        # Keep the displayed amount honest as the balance moves.
        active.amount = bal
        active.reason = f"Past-due balance ${bal}"
        active.save(update_fields=["amount", "reason", "updated_at"])
    return bal


def _notify_advisor(person, hold_type):
    from academics.models import StudentProgram

    sp = (
        StudentProgram.objects.filter(person=person, status=StudentProgram.ACTIVE)
        .select_related("advisor__user")
        .first()
    )
    if sp and sp.advisor and sp.advisor.user:
        notify_user(
            sp.advisor.user,
            f"{person.display_name}'s bursar hold was released — they can register now",
            url=reverse("person_detail", args=[person.pk]),
        )
