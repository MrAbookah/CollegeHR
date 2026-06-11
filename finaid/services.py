"""Financial aid services. The disbursement is the anti-Banner moment: the
aid credit lands on the student's bursar ledger inside the same transaction."""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from core.models import Department
from student_accounts.models import LedgerEntry
from student_accounts.services import post_entry
from workflow.services import notify_department

from .models import AidAward, Disbursement


def respond_to_award(award, accept, amount=None, actor=None):
    if award.status != AidAward.OFFERED:
        raise ValidationError("This award was already responded to.")
    if accept:
        award.status = AidAward.ACCEPTED
        award.amount_accepted = amount or award.amount_offered
    else:
        award.status = AidAward.DECLINED
        award.amount_accepted = None
    award.responded_at = timezone.now()
    award.save()
    return award


@transaction.atomic
def disburse(disbursement, actor=None):
    if disbursement.status == Disbursement.DISBURSED:
        raise ValidationError("Already disbursed.")
    if disbursement.award.status != AidAward.ACCEPTED:
        raise ValidationError("Only accepted awards can disburse.")
    entry = post_entry(
        disbursement.award.person,
        entry_type=LedgerEntry.AID_CREDIT,
        amount=-disbursement.amount,  # credit
        description=f"{disbursement.award.program.name} disbursement ({disbursement.term.code})",
        term=disbursement.term,
        posted_by=actor,
        source=disbursement,
    )
    disbursement.status = Disbursement.DISBURSED
    disbursement.disbursed_at = timezone.now()
    disbursement.ledger_entry = entry
    disbursement.save()
    notify_department(
        Department.objects.get(code="BUR"),
        f"Aid disbursed to {disbursement.award.person.display_name}: "
        f"${disbursement.amount} {disbursement.award.program.code} ({disbursement.term.code})",
        url=reverse("bursar_account", args=[disbursement.award.person_id]),
        exclude_user=actor,
    )
    return disbursement
