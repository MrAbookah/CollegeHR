"""Registration guards + the hold lifecycle, including bursar automation."""

import datetime
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from academics import services as reg
from workflow.models import Hold, HoldType
from workflow.services import BlockedByHold, place_hold

pytestmark = pytest.mark.django_db


def test_register_happy_path_and_duplicates(rita, student, section):
    e = reg.register(student, section, rita)
    assert e.status == "REGISTERED"
    assert section.seats_taken == 1
    with pytest.raises(ValidationError, match="Already registered"):
        reg.register(student, section, rita)


def test_capacity_guard(rita, student, section, ref):
    from core.models import Person

    for i in range(2):
        other = Person.objects.create(first_name=f"P{i}", last_name="Cap")
        reg.register(other, section, rita)
    with pytest.raises(ValidationError, match="full"):
        reg.register(student, section, rita)


def test_time_conflict_guard(rita, student, section, term):
    from academics.models import Course, Section, Subject

    subject = Subject.objects.create(code="CHM", name="Chemistry")
    course = Course.objects.create(subject=subject, number="101",
                                   title="Intro Chem", credits=Decimal("3.0"))
    clash = Section.objects.create(
        course=course, term=term, section_number="01", capacity=10,
        days="WF", start_time=datetime.time(9, 30), end_time=datetime.time(10, 20),
    )
    reg.register(student, section, rita)
    with pytest.raises(ValidationError, match="Time conflict"):
        reg.register(student, clash, rita)


def test_registration_window_guard(rita, student, ref):
    from academics.models import Course, Section, Subject, Term

    closed = Term.objects.create(
        code="2025SP", name="Spring 2025",
        start_date=datetime.date(2025, 1, 13), end_date=datetime.date(2025, 5, 9),
        registration_opens=datetime.date(2024, 11, 1),
        registration_closes=datetime.date(2025, 1, 24),
        grades_due=datetime.date(2025, 5, 16),
    )
    subject = Subject.objects.create(code="MTH", name="Math")
    course = Course.objects.create(subject=subject, number="101", title="Algebra",
                                   credits=Decimal("3.0"))
    section = Section.objects.create(course=course, term=closed, section_number="01")
    with pytest.raises(ValidationError, match="not open"):
        reg.register(student, section, rita)


def test_hold_blocks_registration_until_released(rita, student, section):
    advising = HoldType.objects.get(code="ADVISING")
    hold = place_hold(student, advising, reason="see your advisor", actor=rita)
    with pytest.raises(BlockedByHold) as exc:
        reg.register(student, section, rita)
    assert "Advising" in str(exc.value)

    from workflow.services import release_hold

    release_hold(hold, actor=rita, note="met advisor")
    assert reg.register(student, section, rita).status == "REGISTERED"


def test_bursar_automation_places_and_releases_hold(bob, student, ref):
    from student_accounts.models import LedgerEntry
    from student_accounts.services import post_entry

    post_entry(student, entry_type=LedgerEntry.CHARGE, amount=Decimal("800.00"),
               description="Tuition", posted_by=bob)
    hold = Hold.objects.get(person=student, hold_type__code="BURSAR_BALANCE")
    assert hold.status == "ACTIVE" and hold.placed_by is None  # system actor

    post_entry(student, entry_type=LedgerEntry.PAYMENT, amount=Decimal("-800.00"),
               description="Paid in full", posted_by=bob)
    hold.refresh_from_db()
    assert hold.status == "RELEASED"
    assert "Auto-released" in hold.release_note


def test_advisor_notified_on_auto_release(bob, rita, student, ref):
    from academics.models import Program, StudentProgram
    from core.models import Person
    from student_accounts.models import LedgerEntry
    from student_accounts.services import post_entry
    from workflow.models import Notification

    advisor = Person.objects.get(user=rita)
    program = Program.objects.create(code="BIO-BS", name="Biology", degree="BS",
                                     total_credits_required=Decimal("36.0"))
    StudentProgram.objects.create(person=student, program=program,
                                  catalog_year="2024-25",
                                  declared_date=datetime.date(2024, 9, 1),
                                  advisor=advisor)
    post_entry(student, entry_type=LedgerEntry.CHARGE, amount=Decimal("600.00"),
               description="Tuition", posted_by=bob)
    post_entry(student, entry_type=LedgerEntry.PAYMENT, amount=Decimal("-600.00"),
               description="Payment", posted_by=bob)
    assert Notification.objects.filter(recipient=rita,
                                       title__contains="hold was released").exists()


def test_transcript_blocked_by_hold(client, bob, rita, student, ref):
    hold_type = HoldType.objects.get(code="BURSAR_BALANCE")  # blocks transcript
    place_hold(student, hold_type, reason="owes money", actor=bob)
    client.force_login(rita)
    resp = client.get(f"/academics/transcript/{student.pk}/")
    assert b"blocked by an active hold" in resp.content
