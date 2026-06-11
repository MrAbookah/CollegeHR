"""The permission matrix: who can see, edit, and propose what."""

import pytest

from core import permissions

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("fixture,domain,expected", [
    ("rita", "EMPLOYMENT", False),   # employment is HR-only reading
    ("hank", "EMPLOYMENT", True),
    ("rita", "STUDENT_ACCOUNT", True),   # REG is a permitted reader
    ("ana", "STUDENT_ACCOUNT", False),
    ("ana", "BIOGRAPHIC", True),     # unrestricted domains: any staff
    ("bob", "ACADEMIC", True),
])
def test_can_view_domain(request, fixture, domain, expected):
    user = request.getfixturevalue(fixture)
    assert permissions.can_view_domain(user, domain) is expected


def test_only_owner_edits_others_propose(rita, bob):
    assert permissions.can_edit_domain(rita, "BIOGRAPHIC") is True
    assert permissions.can_edit_domain(bob, "BIOGRAPHIC") is False
    assert permissions.can_propose(bob, "BIOGRAPHIC") is True


def test_salary_field_sensitivity(rita, hank):
    assert permissions.can_see_field(hank, "hr.employmentrecord", "salary") is True
    assert permissions.can_see_field(rita, "hr.employmentrecord", "salary") is False


def test_hold_guards(rita, bob, student):
    from workflow.models import HoldType
    from workflow.services import place_hold, release_hold
    from django.core.exceptions import PermissionDenied

    bursar_hold = HoldType.objects.get(code="BURSAR_BALANCE")
    with pytest.raises(PermissionDenied):
        place_hold(student, bursar_hold, reason="x", actor=rita)
    hold = place_hold(student, bursar_hold, reason="x", actor=bob)
    with pytest.raises(PermissionDenied):
        release_hold(hold, actor=rita)
    release_hold(hold, actor=bob, note="paid")
    hold.refresh_from_db()
    assert hold.status == "RELEASED"


def test_anonymous_is_not_staff(ref):
    from django.contrib.auth.models import AnonymousUser

    assert permissions.is_staff_member(AnonymousUser()) is False
    assert permissions.user_dept_codes(AnonymousUser()) == set()
