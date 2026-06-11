import datetime
from decimal import Decimal

import pytest

from core.bootstrap import bootstrap_reference_data
from core.models import Affiliation, Person, StaffMembership, User
from core.permissions import clear_domain_cache


@pytest.fixture(autouse=True)
def _clear_permission_cache():
    clear_domain_cache()
    yield
    clear_domain_cache()


@pytest.fixture
def ref(db):
    """Reference data: departments, domains, hold types, doc types, etc."""
    return bootstrap_reference_data()


def make_staff(username, dept_code, *, first="Test", last=None):
    user = User.objects.create_user(username=username, password="x", first_name=first,
                                    last_name=last or username.title())
    person = Person.objects.create(first_name=first, last_name=last or username.title(),
                                   primary_email=f"{username}@hilltop.edu", user=user)
    Affiliation.objects.create(person=person, type=Affiliation.EMPLOYEE,
                               start_date=datetime.date(2020, 1, 1))
    from core.models import Department

    StaffMembership.objects.create(
        person=person, department=Department.objects.get(code=dept_code),
        start_date=datetime.date(2020, 1, 1),
    )
    return user


@pytest.fixture
def rita(ref):
    return make_staff("rita", "REG")


@pytest.fixture
def bob(ref):
    return make_staff("bob", "BUR")


@pytest.fixture
def hank(ref):
    return make_staff("hank", "HR")


@pytest.fixture
def fay(ref):
    return make_staff("fay", "FA")


@pytest.fixture
def ana(ref):
    return make_staff("ana", "ADM")


@pytest.fixture
def lee(ref):
    return make_staff("lee", "LIB")


@pytest.fixture
def student(ref):
    person = Person.objects.create(
        first_name="Stu", last_name="Dent", primary_email="stu.dent@example.com",
        date_of_birth=datetime.date(2004, 5, 1), ssn_last4="1234",
    )
    Affiliation.objects.create(person=person, type=Affiliation.STUDENT,
                               start_date=datetime.date(2024, 8, 26))
    return person


@pytest.fixture
def term(db):
    """A term whose registration window is open today."""
    from academics.models import Term
    from django.utils import timezone

    today = timezone.localdate()
    return Term.objects.create(
        code="2026FA", name="Fall 2026",
        start_date=today + datetime.timedelta(days=60),
        end_date=today + datetime.timedelta(days=170),
        registration_opens=today - datetime.timedelta(days=30),
        registration_closes=today + datetime.timedelta(days=30),
        grades_due=today + datetime.timedelta(days=180),
        is_current=True,
    )


@pytest.fixture
def section(term, ref):
    from academics.models import Course, Section, Subject

    subject = Subject.objects.create(code="BIO", name="Biology")
    course = Course.objects.create(subject=subject, number="101",
                                   title="Intro Biology", credits=Decimal("3.0"))
    return Section.objects.create(
        course=course, term=term, section_number="01", capacity=2,
        days="MWF", start_time=datetime.time(9), end_time=datetime.time(9, 50),
    )
