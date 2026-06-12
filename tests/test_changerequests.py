"""The killer feature end-to-end: B enters, A verifies — both policies,
approve/reject/revert/conflict."""

import pytest
from django.urls import reverse

from workflow.models import ChangeRequest, Notification, Task
from workflow.services import review_change, submit_change_request

pytestmark = pytest.mark.django_db


def _bio_edit(client, user, person, phone):
    client.force_login(user)
    return client.post(reverse("person_bio_edit", args=[person.pk]), {
        "first_name": person.first_name, "last_name": person.last_name,
        "middle_name": "", "preferred_name": "", "suffix": "",
        "date_of_birth": person.date_of_birth or "", "pronouns": "",
        "primary_email": person.primary_email, "primary_phone": phone,
    })


def test_apply_then_verify_full_cycle(client, rita, bob, student):
    # Bob (Bursar) fixes a phone — biographic is REG-owned, policy APPLY.
    resp = _bio_edit(client, bob, student, "(555) 111-2222")
    assert resp.status_code == 302

    student.refresh_from_db()
    assert student.primary_phone == "(555) 111-2222"  # live immediately

    cr = ChangeRequest.objects.get()
    assert cr.applied_immediately is True and cr.status == "PENDING"
    task = Task.objects.get(task_type=Task.VERIFY_CHANGE)
    assert task.assigned_department.code == "REG"
    assert Notification.objects.filter(recipient=rita).exists()

    # Rita approves: badge clears, task closes, Bob hears back.
    review_change(cr, rita, approve=True, note="confirmed with student")
    cr.refresh_from_db()
    task.refresh_from_db()
    assert cr.status == "APPROVED" and task.status == "DONE" and task.outcome == "APPROVED"
    assert Notification.objects.filter(recipient=bob, title__contains="approved").exists()


def test_reject_reverts_applied_change(client, rita, bob, student):
    student.primary_phone = "(555) 000-0000"
    student.save()
    _bio_edit(client, bob, student, "(555) 999-8888")
    cr = ChangeRequest.objects.get()

    review_change(cr, rita, approve=False, note="student says no")
    student.refresh_from_db()
    cr.refresh_from_db()
    assert student.primary_phone == "(555) 000-0000"  # reverted
    assert cr.status == "REJECTED" and cr.reverted is True
    assert Notification.objects.filter(recipient=bob, title__contains="rejected").exists()


def test_hold_for_approval_applies_only_on_approve(rita, bob, student, section):
    from academics.models import Enrollment

    e = Enrollment.objects.create(person=student, section=section)
    cr = submit_change_request(
        actor=bob, person=student, domain_code="ACADEMIC", action="UPDATE",
        model_label="academics.enrollment", target=e,
        changes={"grade": {"old": "", "new": "A"}},
    )
    e.refresh_from_db()
    assert e.grade == ""  # nothing applied yet

    review_change(cr, rita, approve=True)
    e.refresh_from_db()
    assert e.grade == "A"
    assert e.grade_points is not None  # post-apply hook derived the points
    assert e.status == Enrollment.COMPLETED


def test_conflict_guard_blocks_stale_apply(rita, bob, student, section):
    from academics.models import Enrollment

    e = Enrollment.objects.create(person=student, section=section)
    cr = submit_change_request(
        actor=bob, person=student, domain_code="ACADEMIC", action="UPDATE",
        model_label="academics.enrollment", target=e,
        changes={"grade": {"old": "", "new": "A"}},
    )
    # Someone else grades it in the meantime.
    e.grade = "B"
    e.save()

    review_change(cr, rita, approve=True)
    cr.refresh_from_db()
    e.refresh_from_db()
    assert cr.status == "CONFLICT"
    assert e.grade == "B"  # no silent clobber


def test_review_guards(rita, bob, fay, student):
    cr = submit_change_request(
        actor=bob, person=student, domain_code="BIOGRAPHIC", action="UPDATE",
        model_label="core.person", target=student,
        changes={"primary_phone": {"old": "", "new": "(555) 1"}},
    )
    from django.core.exceptions import PermissionDenied, ValidationError

    with pytest.raises(PermissionDenied):
        review_change(cr, fay, approve=True)   # FA doesn't own BIOGRAPHIC
    with pytest.raises(PermissionDenied):
        review_change(cr, bob, approve=True)   # can't review your own
    review_change(cr, rita, approve=True)
    with pytest.raises(ValidationError):
        review_change(cr, rita, approve=True)  # already resolved


def _bio_post(client, user, person, **overrides):
    data = {
        "first_name": person.first_name, "last_name": person.last_name,
        "middle_name": "", "preferred_name": "", "suffix": "",
        "date_of_birth": person.date_of_birth or "", "pronouns": "",
        "primary_email": person.primary_email, "primary_phone": person.primary_phone,
    }
    data.update(overrides)
    client.force_login(user)
    return client.post(reverse("person_bio_edit", args=[person.pk]), data)


def test_legal_name_change_held_until_registrar_validates(client, rita, student, ref):
    """SOP 1: Advancement takes a marriage name change at the desk. The name
    must NOT change until REG validates documentation — but REG is notified
    automatically with follow-up instructions."""
    from tests.conftest import make_staff

    ava = make_staff("ava", "ADV")
    resp = _bio_post(client, ava, student, last_name="Dent-Brennan")
    assert resp.status_code == 302

    student.refresh_from_db()
    assert student.last_name == "Dent"  # held: nothing applied yet

    cr = ChangeRequest.objects.get()
    assert cr.applied_immediately is False and cr.status == "PENDING"
    task = Task.objects.get(task_type=Task.VERIFY_CHANGE)
    assert task.assigned_department.code == "REG"
    assert "marriage certificate" in task.description
    assert Notification.objects.filter(recipient=rita).exists()

    # Registrar collects the documentation, then approves: name goes live.
    review_change(cr, rita, approve=True, note="Marriage certificate on file")
    student.refresh_from_db()
    assert student.last_name == "Dent-Brennan"
    # The paper trail survives on the record.
    from core.models import AuditLog

    assert AuditLog.objects.filter(action="VERIFY", person=student).exists()


def test_mixed_name_and_contact_edit_is_fully_held(client, rita, ref, student):
    from tests.conftest import make_staff

    ava = make_staff("ava2", "ADV")
    _bio_post(client, ava, student, last_name="Dent-Brennan",
              primary_phone="(555) 777-1111")
    student.refresh_from_db()
    # The name field forces the WHOLE edit to wait — no partial application.
    assert student.last_name == "Dent" and student.primary_phone != "(555) 777-1111"
    assert ChangeRequest.objects.get().applied_immediately is False


def test_preferred_name_still_applies_instantly(client, rita, ref, student):
    from tests.conftest import make_staff

    ava = make_staff("ava3", "ADV")
    _bio_post(client, ava, student, preferred_name="Dee")
    student.refresh_from_db()
    assert student.preferred_name == "Dee"  # not a legal-name field
    assert ChangeRequest.objects.get().applied_immediately is True


def test_create_action_applies_on_approve(rita, bob, student, ref):
    from decimal import Decimal

    from student_accounts.models import LedgerEntry
    from workflow.services import build_create_changes

    entry = LedgerEntry(person=student, entry_type="CHARGE",
                        amount=Decimal("100.00"), description="Proposed lab fee",
                        effective_date="2026-06-01")
    cr = submit_change_request(
        actor=rita, person=student, domain_code="STUDENT_ACCOUNT", action="CREATE",
        model_label="student_accounts.ledgerentry",
        changes=build_create_changes(entry),
    )
    assert LedgerEntry.objects.count() == 0
    review_change(cr, bob, approve=True)
    assert LedgerEntry.objects.count() == 1
    assert LedgerEntry.objects.get().description == "Proposed lab fee"
