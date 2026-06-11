"""Duplicate-person prevention: scoring, the search-token gate, and merge."""

import datetime

import pytest

from core import dedup
from core.models import Affiliation, Person

pytestmark = pytest.mark.django_db


def test_exact_email_is_definite(student):
    matches = dedup.find_candidates("Totally", "Different",
                                    email="stu.dent@example.com")
    assert matches and matches[0].person == student
    assert matches[0].score == dedup.DEFINITE


def test_ssn4_plus_dob_is_definite(student):
    matches = dedup.find_candidates("X", "Y", date_of_birth=datetime.date(2004, 5, 1),
                                    ssn_last4="1234")
    assert matches and matches[0].person == student


def test_similar_name_same_dob_is_strong(student):
    matches = dedup.find_candidates("Stu", "Dentt",
                                    date_of_birth=datetime.date(2004, 5, 1))
    assert matches and matches[0].person == student
    assert matches[0].score >= dedup.STRONG


def test_search_token_roundtrip():
    token = dedup.issue_search_token()
    assert dedup.validate_search_token(token) is True
    assert dedup.validate_search_token(token + "tamper") is False
    assert dedup.validate_search_token("") is False


def test_create_view_requires_token_and_interstitial(client, rita, student):
    client.force_login(rita)
    # No token: bounced back to search.
    resp = client.get("/people/new/")
    assert resp.status_code == 302

    token = dedup.issue_search_token()
    data = {
        "search_token": token,
        "first_name": "Stu", "last_name": "Dent",
        "date_of_birth": "2004-05-01", "primary_email": "stu.dent@example.com",
        "middle_name": "", "preferred_name": "", "suffix": "", "ssn_last4": "",
        "pronouns": "", "primary_phone": "", "initial_affiliation": "",
    }
    resp = client.post("/people/new/", data)
    assert b"may already exist" in resp.content  # interstitial

    # Force without justification: rejected.
    resp = client.post("/people/new/", {**data, "force": "1"})
    assert b"may already exist" in resp.content
    assert Person.objects.filter(first_name="Stu").count() == 1

    # Force with justification: created + OVERRIDE audited.
    resp = client.post("/people/new/", {**data, "force": "1", "justification": "twins, ID checked"})
    assert resp.status_code == 302
    assert Person.objects.filter(first_name="Stu").count() == 2
    from core.models import AuditLog

    assert AuditLog.objects.filter(action="OVERRIDE",
                                   summary__contains="twins").exists()


def test_merge_moves_children_and_redirects(client, rita, student, section):
    from academics.models import Enrollment

    dup = Person.objects.create(first_name="Stu", last_name="Dent2",
                                primary_email="dup@example.com")
    Affiliation.objects.create(person=dup, type=Affiliation.STUDENT,
                               start_date=datetime.date(2024, 8, 26))
    Enrollment.objects.create(person=dup, section=section)

    dedup.merge(student, dup, rita)
    dup.refresh_from_db()
    assert dup.merged_into == student
    assert Enrollment.objects.filter(person=student).count() == 1
    # Duplicate's active STUDENT affiliation collided -> deactivated, moved.
    assert student.affiliations.filter(type="STUDENT", status="ACTIVE").count() == 1

    client.force_login(rita)
    resp = client.get(f"/people/{dup.pk}/")
    assert resp.status_code == 302 and resp.url == f"/people/{student.pk}/"
