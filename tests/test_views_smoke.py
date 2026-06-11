"""View-level checks: auth gates, FERPA audit logging, field masking."""

import datetime
from decimal import Decimal

import pytest

from core.models import AuditLog

pytestmark = pytest.mark.django_db


def test_anonymous_redirected_to_login(client, ref):
    for url in ["/", "/tasks/", "/people/search/", "/holds/", "/reports/"]:
        resp = client.get(url)
        assert resp.status_code == 302 and "/login/" in resp.url


def test_dashboard_renders_for_staff(client, rita):
    client.force_login(rita)
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"queue" in resp.content


def test_person_tab_logs_ferpa_view(client, rita, student):
    client.force_login(rita)
    resp = client.get(f"/people/{student.pk}/tab/academics/")
    assert resp.status_code == 200
    assert AuditLog.objects.filter(action="VIEW", person=student,
                                   summary__contains="academics").exists()
    # Overview tab is not domain-restricted and not view-logged.
    AuditLog.objects.all().delete()
    client.get(f"/people/{student.pk}/tab/overview/")
    assert not AuditLog.objects.filter(action="VIEW").exists()


def test_restricted_tab_blocked_for_wrong_department(client, ana, student):
    client.force_login(ana)  # Admissions can't read student accounts
    resp = client.get(f"/people/{student.pk}/tab/account/")
    assert b"send the owning office a referral" in resp.content.lower()


def _employ(person_user_owner, student, ref):
    from finance.models import GLAccount
    from hr.models import EmploymentRecord, Position

    position = Position.objects.create(
        position_number="P9999", title="Test Job", department=ref["HR"],
        gl_account=GLAccount.objects.get(number="5010"),
    )
    return EmploymentRecord.objects.create(
        person=student, position=position, hire_date=datetime.date(2025, 1, 6),
        salary=Decimal("61234.00"),
    )


def test_salary_masked_outside_hr(client, rita, hank, student, ref):
    _employ(hank, student, ref)

    client.force_login(hank)
    resp = client.get(f"/hr/employees/{student.pk}/")
    assert b"61,234" in resp.content
    assert AuditLog.objects.filter(action="VIEW", person=student,
                                   summary__contains="salary").exists()

    client.force_login(rita)
    resp = client.get(f"/hr/employees/{student.pk}/")
    assert resp.status_code == 403  # REG can't read EMPLOYMENT at all

    # Finance can read the record but the salary renders masked.
    from tests.conftest import make_staff

    finn = make_staff("finn", "FIN")
    client.force_login(finn)
    resp = client.get(f"/hr/employees/{student.pk}/")
    assert resp.status_code == 200
    assert b"61,234" not in resp.content
    assert "•••".encode() in resp.content


def test_salary_field_absent_from_non_hr_form(rita, hank, student, ref):
    from hr.forms import EmploymentRecordForm

    record = _employ(hank, student, ref)
    assert "salary" in EmploymentRecordForm(instance=record, user=hank).fields
    assert "salary" not in EmploymentRecordForm(instance=record, user=rita).fields


def test_governed_post_by_non_owner_creates_cr_not_save(client, bob, student, section, rita):
    from academics.models import Enrollment
    from workflow.models import ChangeRequest

    e = Enrollment.objects.create(person=student, section=section)
    client.force_login(bob)
    resp = client.post(f"/academics/grade-change/{e.pk}/", {"grade": "A"})
    assert resp.status_code == 302
    e.refresh_from_db()
    assert e.grade == ""  # HOLD_FOR_APPROVAL: nothing changed
    assert ChangeRequest.objects.filter(status="PENDING",
                                        data_domain="ACADEMIC").exists()


def test_instructor_can_grade_own_section(client, rita, student, section, ref):
    from tests.conftest import make_staff

    teacher = make_staff("prof", "REG")  # membership irrelevant; instructor matters
    from core.models import Person

    section.instructor = Person.objects.get(user=teacher)
    section.save()
    from academics.services import enter_grade
    from academics.models import Enrollment

    e = Enrollment.objects.create(person=student, section=section)
    enter_grade(e, "B+", teacher)
    e.refresh_from_db()
    assert e.grade == "B+" and e.status == Enrollment.COMPLETED


def test_reports_page(client, rita):
    client.force_login(rita)
    resp = client.get("/reports/")
    assert resp.status_code == 200
    assert b"Headcount" in resp.content


def test_notification_bell_partial(client, rita):
    client.force_login(rita)
    resp = client.get("/notifications/bell/")
    assert resp.status_code == 200


def test_document_open_logs_view(client, ana, student, ref):
    from django.core.files.base import ContentFile

    from documents.models import DocumentType
    from documents.services import upload_document

    doc = upload_document(
        person=student, doc_type=DocumentType.objects.get(code="HS_TRANSCRIPT"),
        file=ContentFile(b"%PDF-1.1 x", name="t.pdf"), uploaded_by=ana,
    )
    client.force_login(ana)
    resp = client.get(f"/documents/{doc.pk}/file/")
    assert resp.status_code == 200
    assert AuditLog.objects.filter(action="VIEW", person=student,
                                   summary__contains="Opened document").exists()
