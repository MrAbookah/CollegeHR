"""Graduation clearance: the multi-department fan-out and the alumni hook."""

import datetime
from decimal import Decimal

import pytest

from academics import services as reg
from academics.models import (ClearanceItem, GraduationApplication, Program,
                              StudentProgram)
from workflow.models import HoldType, Notification, Task
from workflow.services import BlockedByHold, place_hold

pytestmark = pytest.mark.django_db


@pytest.fixture
def candidate(student, rita, term):
    program = Program.objects.create(code="BIO-BS", name="Biology", degree="BS",
                                     total_credits_required=Decimal("36.0"))
    sp = StudentProgram.objects.create(
        person=student, program=program, catalog_year="2024-25",
        declared_date=datetime.date(2024, 9, 1),
    )
    return student, sp


def test_fanout_creates_items_and_tasks(candidate, rita, term):
    person, sp = candidate
    app = reg.apply_for_graduation(person, sp, term, rita)
    codes = set(app.clearance_items.values_list("department__code", flat=True))
    assert codes == {"REG", "BUR", "LIB"}  # no loans -> no FA item
    assert Task.objects.filter(task_type=Task.GRADUATION_CLEARANCE).count() == 3
    assert app.status == GraduationApplication.IN_REVIEW


def test_loan_adds_fa_clearance(candidate, rita, term, ref):
    from finaid.models import AidAward, AidProgram, AidYear

    person, sp = candidate
    year = AidYear.objects.create(code="2025-26", start_date=datetime.date(2025, 7, 1),
                                  end_date=datetime.date(2026, 6, 30))
    AidAward.objects.create(
        person=person, aid_year=year,
        program=AidProgram.objects.get(code="DIRECT_SUB"),
        amount_offered=Decimal("1750"), amount_accepted=Decimal("1750"),
        status=AidAward.ACCEPTED,
    )
    app = reg.apply_for_graduation(person, sp, term, rita)
    codes = set(app.clearance_items.values_list("department__code", flat=True))
    assert "FA" in codes


def test_graduation_blocked_by_hold(candidate, rita, lee, term):
    person, sp = candidate
    place_hold(person, HoldType.objects.get(code="LIBRARY_FINE"),
               reason="unreturned book", actor=lee)
    with pytest.raises(BlockedByHold):
        reg.apply_for_graduation(person, sp, term, rita)


def test_clearing_all_items_then_award(candidate, rita, bob, lee, term):
    from tests.conftest import make_staff

    ava = make_staff("ava", "ADV")  # someone must be home in Advancement
    person, sp = candidate
    app = reg.apply_for_graduation(person, sp, term, rita)
    by_code = {i.department.code: i for i in app.clearance_items.all()}
    users = {"REG": rita, "BUR": bob, "LIB": lee}

    reg.clear_item(by_code["BUR"], bob, note="zero balance")
    app.refresh_from_db()
    assert app.status == GraduationApplication.IN_REVIEW  # not yet

    # Wrong-department guard.
    from django.core.exceptions import PermissionDenied

    with pytest.raises(PermissionDenied):
        reg.clear_item(by_code["LIB"], bob)

    reg.clear_item(by_code["LIB"], lee)
    reg.clear_item(by_code["REG"], rita)
    app.refresh_from_db()
    assert app.status == GraduationApplication.CLEARED
    assert Notification.objects.filter(title__contains="ready to award").exists()
    # Each office's task closed itself when its item cleared.
    assert not Task.objects.filter(task_type=Task.GRADUATION_CLEARANCE)\
        .exclude(status=Task.DONE).exists()

    reg.award_degree(app, rita)
    app.refresh_from_db()
    sp.refresh_from_db()
    person.refresh_from_db()
    assert app.status == GraduationApplication.AWARDED
    assert sp.status == StudentProgram.COMPLETED
    assert person.affiliations.filter(type="ALUMNI", status="ACTIVE").exists()
    assert not person.affiliations.filter(type="STUDENT", status="ACTIVE").exists()
    assert hasattr(person, "alumni_info")
    assert Notification.objects.filter(recipient=ava, title__contains="New alumni").exists()


def test_award_requires_cleared_and_registrar(candidate, rita, bob, term):
    person, sp = candidate
    app = reg.apply_for_graduation(person, sp, term, rita)
    from django.core.exceptions import PermissionDenied, ValidationError

    with pytest.raises(ValidationError):
        reg.award_degree(app, rita)  # not cleared yet
    app.status = GraduationApplication.CLEARED
    app.save()
    with pytest.raises(PermissionDenied):
        reg.award_degree(app, bob)  # bursar can't award degrees
