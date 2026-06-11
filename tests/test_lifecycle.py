"""Cross-silo lifecycle hooks: enroll, documents, gifts, disbursements."""

import datetime
from decimal import Decimal

import pytest
from django.core.files.base import ContentFile
from django.utils import timezone

from core.models import Affiliation

pytestmark = pytest.mark.django_db


@pytest.fixture
def application(ana, term, ref):
    from academics.models import Program
    from admissions.models import Application
    from core.models import Person

    person = Person.objects.create(first_name="App", last_name="Licant",
                                   primary_email="app@example.com")
    Affiliation.objects.create(person=person, type=Affiliation.APPLICANT,
                               start_date=timezone.localdate())
    program = Program.objects.create(code="CSC-BS", name="Computer Science",
                                     degree="BS", total_credits_required=Decimal("36"))
    return Application.objects.create(person=person, term=term, program=program,
                                      stage=Application.INQUIRY)


def test_stage_machine_and_checklist(ana, application):
    from admissions import services
    from admissions.models import Application
    from django.core.exceptions import ValidationError

    services.change_stage(application, Application.APPLIED, ana)
    assert application.checklist.count() == 3  # default template

    # Can't go to review with required items missing.
    with pytest.raises(ValidationError, match="Checklist incomplete"):
        services.change_stage(application, Application.IN_REVIEW, ana)

    application.checklist.update(status="RECEIVED")
    services.change_stage(application, Application.IN_REVIEW, ana)

    # Illegal jump.
    with pytest.raises(ValidationError, match="Cannot move"):
        services.change_stage(application, Application.DEPOSITED, ana)


def test_enroll_lifecycle_hook(ana, rita, fay, application):
    from admissions import services
    from admissions.models import Application
    from workflow.models import Notification, Task

    for stage in (Application.APPLIED,):
        services.change_stage(application, stage, ana)
    application.checklist.update(status="RECEIVED")
    for stage in (Application.IN_REVIEW, Application.ADMITTED, Application.DEPOSITED,
                  Application.ENROLLED):
        services.change_stage(application, stage, ana)

    person = application.person
    assert person.affiliations.filter(type="STUDENT", status="ACTIVE").exists()
    assert not person.affiliations.filter(type="APPLICANT", status="ACTIVE").exists()
    assert person.student_programs.filter(program=application.program).exists()
    advisor_task = Task.objects.get(task_type=Task.REFERRAL)
    assert advisor_task.assigned_department.code == "REG"
    assert Notification.objects.filter(recipient=fay, title__contains="enrolled").exists()


def test_non_admissions_cannot_move_pipeline(rita, application):
    from admissions import services
    from admissions.models import Application
    from django.core.exceptions import PermissionDenied

    with pytest.raises(PermissionDenied):
        services.change_stage(application, Application.APPLIED, rita)


def test_document_upload_review_flips_checklist(ana, rita, application):
    from admissions import services as adm
    from admissions.models import Application
    from documents.models import DocumentType
    from documents.services import review_document, upload_document
    from workflow.models import Task

    adm.change_stage(application, Application.APPLIED, ana)
    item = application.checklist.get(doc_type__code="HS_TRANSCRIPT")
    assert item.status == "MISSING"

    doc = upload_document(
        person=application.person,
        doc_type=DocumentType.objects.get(code="HS_TRANSCRIPT"),
        file=ContentFile(b"%PDF-1.1 demo", name="transcript.pdf"),
        uploaded_by=rita,
    )
    task = Task.objects.get(task_type=Task.REVIEW_DOCUMENT)
    assert task.assigned_department.code == "ADM"  # HS transcripts belong to ADM

    # Only the owning department can review.
    from django.core.exceptions import PermissionDenied

    with pytest.raises(PermissionDenied):
        review_document(doc, rita, verify=True)

    review_document(doc, ana, verify=True, note="ok")
    item.refresh_from_db()
    task.refresh_from_db()
    assert item.status == "RECEIVED" and item.document == doc
    assert task.status == Task.DONE


def test_first_gift_creates_donor_badge(ref, student):
    from advancement.models import Designation
    from advancement.services import record_gift

    gift = record_gift(student, Designation.objects.get(code="ANNUAL"),
                       Decimal("100.00"))
    assert gift.receipt_number.startswith("R")
    assert student.affiliations.filter(type="DONOR", status="ACTIVE").exists()


def test_disbursement_posts_to_ledger(fay, bob, student, term, ref):
    from finaid.models import AidAward, AidProgram, AidYear, Disbursement
    from finaid.services import disburse
    from student_accounts.services import balance, post_entry
    from student_accounts.models import LedgerEntry

    post_entry(student, entry_type=LedgerEntry.CHARGE, amount=Decimal("700.00"),
               description="Tuition", posted_by=bob)
    assert balance(student) == Decimal("700.00")

    year = AidYear.objects.create(code="2026-27", start_date=datetime.date(2026, 7, 1),
                                  end_date=datetime.date(2027, 6, 30))
    award = AidAward.objects.create(
        person=student, aid_year=year, program=AidProgram.objects.get(code="PELL"),
        amount_offered=Decimal("700"), amount_accepted=Decimal("700"),
        status=AidAward.ACCEPTED,
    )
    d = Disbursement.objects.create(award=award, term=term, amount=Decimal("700"))
    disburse(d, fay)
    d.refresh_from_db()
    assert d.status == Disbursement.DISBURSED and d.ledger_entry is not None
    assert balance(student) == Decimal("0.00")
    # And the hold automation saw the credit: the earlier charge's hold released.
    from workflow.models import Hold

    assert not Hold.objects.filter(person=student, status="ACTIVE").exists()
