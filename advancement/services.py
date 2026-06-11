"""Advancement services: gifts create donors, graduations create alumni."""

from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from core.models import Affiliation, Department
from workflow.services import notify_department

from .models import AlumniInfo, Gift, Pledge


@transaction.atomic
def record_gift(person, designation, amount, *, method=Gift.CHECK, gift_date=None,
                pledge=None, actor=None):
    gift = Gift.objects.create(
        person=person,
        designation=designation,
        amount=amount,
        method=method,
        gift_date=gift_date or timezone.localdate(),
        pledge=pledge,
    )
    if not gift.receipt_number:
        gift.receipt_number = f"R{gift.pk:08d}"
        Gift.objects.filter(pk=gift.pk).update(receipt_number=gift.receipt_number)

    Affiliation.objects.get_or_create(
        person=person, type=Affiliation.DONOR, status=Affiliation.ACTIVE,
        defaults={"start_date": gift.gift_date},
    )

    if pledge and pledge.fulfilled_amount >= pledge.total_amount:
        pledge.status = Pledge.FULFILLED
        pledge.save()
    return gift


def make_alumni(person, *, class_year, degree, actor=None):
    """Called when a degree is awarded. One person row goes applicant →
    student → alumnus without anyone re-keying anything."""
    Affiliation.objects.get_or_create(
        person=person, type=Affiliation.ALUMNI, status=Affiliation.ACTIVE,
        defaults={"start_date": timezone.localdate()},
    )
    AlumniInfo.objects.get_or_create(
        person=person,
        defaults={"class_year": class_year, "degree_received": degree},
    )
    notify_department(
        Department.objects.get(code="ADV"),
        f"New alumni: {person.display_name} ({degree}, class of {class_year})",
        url=reverse("person_detail", args=[person.pk]),
        exclude_user=actor,
    )
