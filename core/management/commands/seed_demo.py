"""Seed 'Hilltop College' — a believable small college with multi-role
people, live cross-department queues, and an in-progress graduation cohort,
so every screen demonstrates something real.

    python manage.py seed_demo [--flush] [--seed 42]

Deterministic for a given --seed. Prints a login cheat-sheet when done.
"""

import datetime
import io
import random
from decimal import Decimal

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from core.bootstrap import bootstrap_reference_data, current_fiscal_year

PASSWORD = "demo1234"

# A one-page valid-enough PDF so document links open in a viewer.
MINI_PDF = (
    b"%PDF-1.1\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents 4 0 R>>endobj\n"
    b"4 0 obj<</Length 44>>stream\nBT /F1 18 Tf 72 720 Td (CollegeDB demo) Tj ET\nendstream endobj\n"
    b"trailer<</Root 1 0 R>>\n%%EOF\n"
)

DEMO_STAFF = [
    # username, first, last, dept, manager?
    ("registrar.rita", "Rita", "Vance", "REG", True),
    ("registrar.ray", "Ray", "Okafor", "REG", False),
    ("admissions.ana", "Ana", "Reyes", "ADM", True),
    ("admissions.al", "Al", "Burton", "ADM", False),
    ("finaid.fay", "Fay", "Nguyen", "FA", True),
    ("bursar.bob", "Bob", "Marsh", "BUR", True),
    ("hr.hank", "Hank", "Osei", "HR", True),
    ("finance.finn", "Finn", "Iqbal", "FIN", True),
    ("advancement.ava", "Ava", "Klein", "ADV", True),
    ("library.lee", "Lee", "Tanaka", "LIB", True),
]

SUBJECTS = [
    ("BIO", "Biology"), ("CHM", "Chemistry"), ("MTH", "Mathematics"),
    ("ENG", "English"), ("HIS", "History"), ("PSY", "Psychology"),
    ("BUS", "Business"), ("CSC", "Computer Science"), ("ART", "Art"),
    ("MUS", "Music"), ("PHL", "Philosophy"), ("SOC", "Sociology"),
]

PROGRAMS = [
    ("BIO-BS", "Biology", "BS", "BIO"),
    ("ENG-BA", "English", "BA", "ENG"),
    ("BUS-BA", "Business Administration", "BA", "BUS"),
    ("CSC-BS", "Computer Science", "BS", "CSC"),
    ("PSY-BA", "Psychology", "BA", "PSY"),
    ("HIS-BA", "History", "BA", "HIS"),
]


class Command(BaseCommand):
    help = "Seed the Hilltop College demo data set."

    def add_arguments(self, parser):
        parser.add_argument("--flush", action="store_true",
                            help="Delete existing app data first (keeps superusers).")
        parser.add_argument("--seed", type=int, default=42)

    @transaction.atomic
    def handle(self, *args, **options):
        from faker import Faker

        self.rng = random.Random(options["seed"])
        self.faker = Faker("en_US")
        Faker.seed(options["seed"])

        if options["flush"]:
            self._flush()

        self.depts = bootstrap_reference_data()
        self._terms_and_years()
        self._catalog()
        self._staff_and_faculty()
        self._students()
        self._admissions_pipeline()
        self._money()
        self._graduation_cohort()
        self._documents()
        self._workflow_extras()
        self._payroll_and_finance()
        self._gifts()
        self._print_cheatsheet()

    # ------------------------------------------------------------------ utils

    def _flush(self):
        from academics import models as ac
        from admissions import models as ad
        from advancement import models as av
        from core import models as co
        from documents import models as dm
        from finaid import models as fa
        from finance import models as fi
        from hr import models as hrm
        from student_accounts import models as sa
        from workflow import models as wf

        self.stdout.write("Flushing existing data…")
        from core import audit

        with audit.suppressed():
            for model in [
                wf.Notification, wf.TaskComment, wf.Task, wf.ChangeRequest, wf.Hold,
                dm.Document, ad.CommunicationLog, ad.ApplicationChecklistItem, ad.Application,
                ac.ClearanceItem, ac.GraduationApplication, ac.Enrollment, ac.StudentProgram,
                fa.Disbursement, fa.AidAward, sa.LedgerEntry,
                hrm.Paycheck, hrm.PayrollRun, hrm.EmploymentRecord, hrm.Position,
                av.Gift, av.Pledge, av.AlumniInfo,
                fi.JournalLine, fi.JournalEntry, fi.DepartmentBudget,
                ac.Section,
                co.StaffMembership, co.Affiliation, co.EmergencyContact, co.PersonAddress,
                co.AuditLog,
            ]:
                model.objects.all().delete()
            co.Person.objects.update(merged_into=None)
            co.Person.objects.all().delete()
            co.User.objects.filter(is_superuser=False).delete()

    def _person(self, first, last, *, email=None, dob=None, banner=None):
        from core.models import Person

        return Person.objects.create(
            first_name=first, last_name=last,
            primary_email=email or f"{first}.{last}{self.rng.randint(1, 999)}@example.com".lower(),
            primary_phone=self.faker.numerify("(555) ###-####"),
            date_of_birth=dob or self.faker.date_of_birth(minimum_age=17, maximum_age=70),
            ssn_last4=self.faker.numerify("####"),
            banner_id=banner,
        )

    def _address(self, person):
        from core.models import PersonAddress

        PersonAddress.objects.create(
            person=person, line1=self.faker.street_address(), city=self.faker.city(),
            state=self.faker.state_abbr(), postal_code=self.faker.postcode()[:5],
        )

    def _affiliate(self, person, type_, start=None, status="ACTIVE"):
        from core.models import Affiliation

        if status == "ACTIVE" and person.affiliations.filter(type=type_, status="ACTIVE").exists():
            return
        Affiliation.objects.create(
            person=person, type=type_, status=status,
            start_date=start or datetime.date(2024, 8, 26),
            end_date=None if status == "ACTIVE" else datetime.date(2025, 5, 15),
        )

    # ------------------------------------------------------------- reference

    def _terms_and_years(self):
        from academics.models import Term
        from finaid.models import AidYear
        from finance.models import FiscalYear

        def term(code, name, start, end, reg_open, reg_close, grades, current=False):
            t, _ = Term.objects.get_or_create(code=code, defaults=dict(
                name=name, start_date=start, end_date=end,
                registration_opens=reg_open, registration_closes=reg_close,
                grades_due=grades, is_current=current,
            ))
            return t

        d = datetime.date
        self.t_25fa = term("2025FA", "Fall 2025", d(2025, 8, 25), d(2025, 12, 12),
                           d(2025, 4, 1), d(2025, 9, 1), d(2025, 12, 19))
        self.t_26sp = term("2026SP", "Spring 2026", d(2026, 1, 12), d(2026, 5, 8),
                           d(2025, 11, 1), d(2026, 1, 23), d(2026, 5, 15))
        self.t_26fa = term("2026FA", "Fall 2026", d(2026, 8, 24), d(2026, 12, 11),
                           d(2026, 4, 1), d(2026, 9, 4), d(2026, 12, 18), current=True)
        self.terms_past = [self.t_25fa, self.t_26sp]

        for code, (s, e) in {"2025-26": (d(2025, 7, 1), d(2026, 6, 30)),
                             "2026-27": (d(2026, 7, 1), d(2027, 6, 30))}.items():
            AidYear.objects.get_or_create(code=code, defaults=dict(start_date=s, end_date=e))
        self.aid_years = {y.code: y for y in AidYear.objects.all()}

        fy_code, fy_start, fy_end = current_fiscal_year(datetime.date(2026, 6, 11))
        self.fy, _ = FiscalYear.objects.get_or_create(
            code=fy_code, defaults=dict(start_date=fy_start, end_date=fy_end))

    def _catalog(self):
        from academics.models import (Course, Program, ProgramRequirement,
                                      Section, Subject)

        self.subjects = {}
        for code, name in SUBJECTS:
            self.subjects[code], _ = Subject.objects.get_or_create(code=code, defaults={"name": name})

        self.courses = []
        titles = ["Introduction to", "Foundations of", "Topics in", "Advanced", "Seminar in"]
        for code, subject in self.subjects.items():
            for i, level in enumerate([101, 150, 210, 310, 410]):
                course, _ = Course.objects.get_or_create(
                    subject=subject, number=str(level),
                    defaults=dict(
                        title=f"{titles[i]} {subject.name}",
                        credits=Decimal("3.0"),
                        description=self.faker.paragraph(nb_sentences=2),
                    ),
                )
                self.courses.append(course)

        self.programs = []
        for code, name, degree, subj in PROGRAMS:
            program, created = Program.objects.get_or_create(code=code, defaults=dict(
                name=name, degree=degree, total_credits_required=Decimal("36.0")))
            self.programs.append(program)
            if created:
                major = ProgramRequirement.objects.create(
                    program=program, category="Major Core", credits_required=Decimal("12.0"), order=1)
                major.applicable_courses.set(
                    [c for c in self.courses if c.subject.code == subj])
                gened = ProgramRequirement.objects.create(
                    program=program, category="General Education", credits_required=Decimal("12.0"), order=2)
                gened.applicable_courses.set(
                    [c for c in self.courses if c.subject.code in ("ENG", "MTH", "HIS", "PHL") and c.number in ("101", "150")])
                ProgramRequirement.objects.create(
                    program=program, category="Electives", credits_required=Decimal("12.0"), order=3)

        # Sections come after faculty exist (instructors); stash the plan.
        self.section_slots = [("MWF", datetime.time(h)) for h in (8, 9, 10, 11, 13, 14, 15)] + \
                             [("TR", datetime.time(h)) for h in (8, 9, 11, 13, 14, 16)]
        self.Section = Section

    def _make_sections(self):
        self.sections = {t.pk: [] for t in [self.t_25fa, self.t_26sp, self.t_26fa]}
        for term in [self.t_25fa, self.t_26sp, self.t_26fa]:
            chosen = self.rng.sample(self.courses, 40)
            for course in chosen:
                days, start = self.rng.choice(self.section_slots)
                end = (datetime.datetime.combine(datetime.date.today(), start)
                       + datetime.timedelta(minutes=50 if days == "MWF" else 75)).time()
                section, _ = self.Section.objects.get_or_create(
                    course=course, term=term, section_number="01",
                    defaults=dict(
                        instructor=self.rng.choice(self.faculty),
                        capacity=self.rng.choice([18, 24, 30]),
                        days=days, start_time=start, end_time=end,
                        room=f"{self.rng.choice('ABC')}{self.rng.randint(100, 320)}",
                    ),
                )
                self.sections[term.pk].append(section)

    # ----------------------------------------------------------------- people

    def _staff_and_faculty(self):
        from core.models import StaffMembership, User
        from finance.models import GLAccount
        from hr.models import EmploymentRecord, Position

        gl_staff = GLAccount.objects.get(number="5010")
        gl_fac = GLAccount.objects.get(number="5000")
        self.users = {}
        self.staff_people = {}

        pos_counter = 100

        def employ(person, title, dept, gl, salary, faculty=False):
            nonlocal pos_counter
            pos_counter += 1
            position = Position.objects.create(
                position_number=f"P{pos_counter:04d}", title=title,
                department=dept, gl_account=gl, is_faculty=faculty,
            )
            EmploymentRecord.objects.create(
                person=person, position=position, hire_date=self.faker.date_between("-12y", "-1y"),
                salary=Decimal(salary), pay_basis="SALARY",
            )

        for username, first, last, dept_code, manager in DEMO_STAFF:
            user = User.objects.create_user(
                username=username, password=PASSWORD,
                first_name=first, last_name=last, email=f"{username}@hilltop.edu",
            )
            person = self._person(first, last, email=f"{username}@hilltop.edu")
            person.user = user
            person.save()
            self._address(person)
            self._affiliate(person, "EMPLOYEE", start=datetime.date(2019, 7, 1))
            StaffMembership.objects.create(
                person=person, department=self.depts[dept_code],
                role="MANAGER" if manager else "STAFF", start_date=datetime.date(2019, 7, 1),
            )
            employ(person, f"{self.depts[dept_code].name} {'Director' if manager else 'Specialist'}",
                   self.depts[dept_code], gl_staff, self.rng.randint(52, 88) * 1000)
            self.users[username] = user
            self.staff_people[username] = person

        # Faculty: people + users + employment, teach sections, advise students.
        self.faculty = []
        used = set()
        for i in range(20):
            first, last = self.faker.first_name(), self.faker.last_name()
            base = f"prof.{last.lower()}"
            username = base if base not in used else f"{base}{i}"
            used.add(username)
            user = User.objects.create_user(username=username, password=PASSWORD,
                                            first_name=first, last_name=last)
            person = self._person(first, last, email=f"{username}@hilltop.edu")
            person.user = user
            person.save()
            self._affiliate(person, "EMPLOYEE", start=datetime.date(2017, 8, 1))
            self._affiliate(person, "FACULTY", start=datetime.date(2017, 8, 1))
            employ(person, "Professor", self.depts["REG"], gl_fac,
                   self.rng.randint(61, 110) * 1000, faculty=True)
            self.faculty.append(person)

        self._make_sections()

    def _students(self):
        from academics.models import Enrollment, StudentProgram
        from academics.grades import GRADE_POINTS

        self.students = []
        grades = ["A", "A-", "B+", "B", "B", "B-", "C+", "C", "D", "F", "P"]

        # Named personas first (stable, memorable for the demo script).
        self.jordan = self._person("Jordan", "Rivers", email="jordan.rivers@hilltop.edu",
                                   dob=datetime.date(2004, 3, 14), banner="@00012345")
        self.sam = self._person("Sam", "Lee", email="sam.lee@hilltop.edu",
                                dob=datetime.date(2003, 11, 2), banner="@00012346")
        self.casey = self._person("Casey", "Fox", email="casey.fox@hilltop.edu",
                                  dob=datetime.date(2005, 6, 21))
        personas = [self.jordan, self.sam, self.casey]

        for person in personas:
            self._address(person)
            self._affiliate(person, "STUDENT")
            self.students.append(person)

        for _ in range(297):
            person = self._person(self.faker.first_name(), self.faker.last_name(),
                                  dob=self.faker.date_of_birth(minimum_age=17, maximum_age=26))
            self._address(person)
            self._affiliate(person, "STUDENT")
            self.students.append(person)

        # Declared programs + advisors.
        self.student_programs = {}
        for person in self.students:
            program = self.rng.choice(self.programs)
            sp = StudentProgram.objects.create(
                person=person, program=program, catalog_year="2024-25",
                declared_date=datetime.date(2024, 9, 3), advisor=self.rng.choice(self.faculty),
            )
            self.student_programs[person.pk] = sp

        # Enrollments: 4-5 courses per past term (graded), some current-term regs.
        taken = {}  # section pk -> count (manual capacity bookkeeping)

        def enroll(person, term, n_courses, graded):
            options = [s for s in self.sections[term.pk]
                       if taken.get(s.pk, 0) < s.capacity - 2]
            self.rng.shuffle(options)
            picked, used_courses = [], set()
            for s in options:
                if len(picked) >= n_courses:
                    break
                if s.course_id in used_courses:
                    continue
                used_courses.add(s.course_id)
                picked.append(s)
            for s in picked:
                taken[s.pk] = taken.get(s.pk, 0) + 1
                e = Enrollment.objects.create(person=person, section=s)
                if graded:
                    g = self.rng.choice(grades)
                    e.grade = g
                    e.grade_points = GRADE_POINTS.get(g)
                    e.status = Enrollment.COMPLETED if g != "W" else Enrollment.WITHDRAWN
                    e.save()

        for person in self.students:
            enroll(person, self.t_25fa, self.rng.randint(4, 5), graded=True)
            enroll(person, self.t_26sp, self.rng.randint(4, 5), graded=True)
            if self.rng.random() < 0.7 and person not in (self.sam,):
                enroll(person, self.t_26fa, self.rng.randint(3, 5), graded=False)

        # Multi-role people — the whole point of the person hub.
        self._multi_role()

    def _multi_role(self):
        from core.models import StaffMembership
        from finance.models import GLAccount
        from hr.models import EmploymentRecord, Position

        gl = GLAccount.objects.get(number="5010")

        # ~15 student workers (Jordan among them, in IT under HR's wing).
        student_workers = [self.jordan] + self.rng.sample(self.students[3:], 14)
        for i, person in enumerate(student_workers):
            self._affiliate(person, "EMPLOYEE", start=datetime.date(2025, 9, 1))
            position = Position.objects.create(
                position_number=f"S{i:04d}",
                title="Student Worker — " + self.rng.choice(
                    ["IT Helpdesk", "Library Desk", "Dining", "Campus Tours", "Mailroom"]),
                department=self.rng.choice([self.depts["LIB"], self.depts["HR"], self.depts["ADM"]]),
                gl_account=gl, fte=Decimal("0.25"),
            )
            EmploymentRecord.objects.create(
                person=person, position=position, hire_date=datetime.date(2025, 9, 8),
                salary=Decimal("15080"), pay_basis="HOURLY",
            )

        # ~30 standalone alumni (some donors), class of '05-'20.
        from advancement.models import AlumniInfo

        self.alumni = []
        for _ in range(30):
            person = self._person(self.faker.first_name(), self.faker.last_name(),
                                  dob=self.faker.date_of_birth(minimum_age=28, maximum_age=60))
            self._affiliate(person, "ALUMNI", start=self.faker.date_between("-20y", "-4y"))
            AlumniInfo.objects.create(
                person=person, class_year=self.rng.randint(2005, 2020),
                degree_received=f"{self.rng.choice(['B.A.', 'B.S.'])} {self.rng.choice(PROGRAMS)[1]}",
                employer=self.faker.company(), job_title=self.faker.job()[:100],
            )
            self.alumni.append(person)

        # A couple of staff are alumni too (hire your own grads).
        for username in ("registrar.ray", "admissions.al"):
            person = self.staff_people[username]
            self._affiliate(person, "ALUMNI", start=datetime.date(2015, 5, 20))
            AlumniInfo.objects.get_or_create(person=person, defaults=dict(
                class_year=2015, degree_received="B.A. English"))

    # ------------------------------------------------------------- admissions

    def _admissions_pipeline(self):
        from admissions.models import Application, CommunicationLog
        from admissions.services import build_checklist

        ana = self.users["admissions.ana"]
        stages = (
            [Application.INQUIRY] * 14 + [Application.APPLIED] * 12
            + [Application.IN_REVIEW] * 8 + [Application.ADMITTED] * 10
            + [Application.WAITLISTED] * 3 + [Application.DENIED] * 5
            + [Application.DEPOSITED] * 6 + [Application.WITHDRAWN] * 2
        )
        self.applicants = []

        # Avery Cole: the DEPOSITED persona ready to be ENROLLED live on stage.
        self.avery = self._person("Avery", "Cole", dob=datetime.date(2008, 2, 9),
                                  email="avery.cole@example.com")
        self._address(self.avery)
        self._affiliate(self.avery, "APPLICANT")
        avery_app = Application.objects.create(
            person=self.avery, term=self.t_26fa, program=self.programs[3],
            stage=Application.DEPOSITED, submitted_at=timezone.now() - datetime.timedelta(days=90),
            deposit_paid_at=timezone.now() - datetime.timedelta(days=14),
            high_school="Ridgeline High School", gpa_reported=Decimal("3.71"),
            counselor=ana,
        )
        build_checklist(avery_app)
        avery_app.checklist.update(status="RECEIVED", received_at=timezone.now())
        self.avery_app = avery_app

        for stage in stages:
            person = self._person(self.faker.first_name(), self.faker.last_name(),
                                  dob=self.faker.date_of_birth(minimum_age=17, maximum_age=22))
            self._affiliate(person, "APPLICANT")
            app = Application.objects.create(
                person=person, term=self.t_26fa, program=self.rng.choice(self.programs),
                stage=stage,
                submitted_at=None if stage == Application.INQUIRY else timezone.now()
                - datetime.timedelta(days=self.rng.randint(10, 120)),
                high_school=f"{self.faker.city()} High School",
                gpa_reported=Decimal(str(round(self.rng.uniform(2.2, 4.0), 2))),
                source=self.rng.choice([c for c, _ in Application.SOURCES]),
                counselor=ana,
            )
            if stage not in (Application.INQUIRY,):
                build_checklist(app)
                if stage in (Application.IN_REVIEW, Application.ADMITTED,
                             Application.DEPOSITED, Application.WAITLISTED, Application.DENIED):
                    app.checklist.update(status="RECEIVED", received_at=timezone.now())
                else:
                    # APPLIED: leave required items partially missing.
                    for item in app.checklist.all()[:1]:
                        item.status = "RECEIVED"
                        item.received_at = timezone.now()
                        item.save()
            CommunicationLog.objects.create(
                person=person, application=app, channel="EMAIL", direction="OUT",
                subject="Welcome to Hilltop — next steps",
                notes="Sent the standard inquiry packet.", logged_by=ana,
                occurred_at=timezone.now() - datetime.timedelta(days=self.rng.randint(1, 60)),
            )
            self.applicants.append(app)

    # ------------------------------------------------------------------ money

    def _money(self):
        from finaid.models import AidAward, AidProgram, Disbursement
        from student_accounts.models import ChargeCode, LedgerEntry
        from student_accounts.services import post_entry

        tuition = ChargeCode.objects.get(code="TUITION")
        fees = ChargeCode.objects.get(code="FEES")
        programs = {p.code: p for p in AidProgram.objects.all()}
        fay = self.users["finaid.fay"]
        bob = self.users["bursar.bob"]
        year = self.aid_years["2025-26"]

        # Sam Lee's graduation application must exist BEFORE his debt (the
        # hold would block a new application — that's the demo).
        self._sam_grad_app()

        delinquents = set(
            p.pk for p in self.rng.sample([s for s in self.students if s not in (self.sam, self.jordan, self.casey)], 12)
        )

        for person in self.students:
            aided = self.rng.random() < 0.6
            award_total = Decimal("0")
            if aided:
                for code, amount in [("PELL", 3700), ("INST_SCHOL", 2500), ("DIRECT_SUB", 1750)]:
                    if self.rng.random() < 0.7:
                        award = AidAward.objects.create(
                            person=person, aid_year=year, program=programs[code],
                            amount_offered=Decimal(amount), amount_accepted=Decimal(amount),
                            status=AidAward.ACCEPTED, responded_at=timezone.now(),
                        )
                        for term in self.terms_past:
                            disb_amount = Decimal(amount) / 2
                            entry = post_entry(
                                person, entry_type=LedgerEntry.AID_CREDIT,
                                amount=-disb_amount,
                                description=f"{award.program.name} disbursement ({term.code})",
                                term=term, posted_by=fay,
                                effective_date=term.start_date + datetime.timedelta(days=20),
                            )
                            Disbursement.objects.create(
                                award=award, term=term, amount=disb_amount,
                                status=Disbursement.DISBURSED,
                                disbursed_at=timezone.now(), ledger_entry=entry,
                            )
                            award_total += disb_amount

            charges = Decimal("0")
            for term in self.terms_past:
                for code, cc in [("TUITION", tuition), ("FEES", fees)]:
                    amount = cc.default_amount
                    post_entry(person, entry_type=LedgerEntry.CHARGE, amount=amount,
                               description=f"{cc.description} {term.code}", term=term,
                               charge_code=cc, posted_by=bob,
                               effective_date=term.start_date)
                    charges += amount

            balance_after_aid = charges - award_total
            if person.pk in delinquents:
                pay = balance_after_aid - Decimal(self.rng.randint(600, 2200))
            elif person == self.sam:
                pay = balance_after_aid - Decimal("1240")
            else:
                pay = balance_after_aid
            if pay > 0:
                post_entry(person, entry_type=LedgerEntry.PAYMENT, amount=-pay,
                           description="Payment — student portal", posted_by=bob,
                           effective_date=self.t_26sp.start_date + datetime.timedelta(days=30))

    def _sam_grad_app(self):
        """Sam's storyline: applied to graduate while in good standing, then
        the balance and a library fine appeared."""
        from academics.services import apply_for_graduation
        from workflow.models import HoldType
        from workflow.services import place_hold

        rita = self.users["registrar.rita"]
        self.sam_app = apply_for_graduation(
            self.sam, self.student_programs[self.sam.pk], self.t_26fa, rita)
        place_hold(
            self.sam, HoldType.objects.get(code="LIBRARY_FINE"),
            reason="Unreturned: 'Organic Chemistry, 4th ed.' + $15.00 fine",
            amount=Decimal("15.00"), actor=self.users["library.lee"],
        )

    # ------------------------------------------------------------- graduation

    def _graduation_cohort(self):
        from academics.models import ClearanceItem, GraduationApplication
        from academics.services import apply_for_graduation, clear_item
        from student_accounts.services import balance

        rita = self.users["registrar.rita"]
        bob = self.users["bursar.bob"]
        lee = self.users["library.lee"]
        fay = self.users["finaid.fay"]
        by_dept_user = {"REG": rita, "BUR": bob, "LIB": lee, "FA": fay}

        # 24 more candidates (Sam already applied) with zero/low balances.
        candidates = [
            s for s in self.students
            if s not in (self.sam, self.jordan, self.casey) and balance(s) <= 0
        ][:24]
        cleared_n = 8
        partial_n = 10
        for i, person in enumerate(candidates):
            try:
                app = apply_for_graduation(person, self.student_programs[person.pk],
                                           self.t_26fa, rita)
            except Exception:
                continue
            items = list(app.clearance_items.select_related("department"))
            if i < cleared_n:
                for item in items:
                    clear_item(item, by_dept_user[item.department.code], note="Seeded clear")
            elif i < cleared_n + partial_n:
                for item in self.rng.sample(items, k=max(1, len(items) - 2)):
                    clear_item(item, by_dept_user[item.department.code], note="Seeded clear")

        # Award two degrees so Advancement has fresh alumni.
        from academics.services import award_degree

        for app in GraduationApplication.objects.filter(
                status=GraduationApplication.CLEARED)[:2]:
            award_degree(app, rita)

    # -------------------------------------------------------------- documents

    def _documents(self):
        from admissions.models import Application
        from documents.models import DocumentType
        from documents.services import review_document, upload_document

        types = {t.code: t for t in DocumentType.objects.all()}
        ana = self.users["admissions.ana"]
        rita = self.users["registrar.rita"]
        hank = self.users["hr.hank"]
        reviewers = {"ADM": ana, "REG": rita, "HR": hank,
                     "FA": self.users["finaid.fay"], "ADV": self.users["advancement.ava"]}

        def make(person, code, uploader, verify=None):
            doc = upload_document(
                person=person, doc_type=types[code],
                file=ContentFile(MINI_PDF, name=f"{code.lower()}_{person.pk}.pdf"),
                uploaded_by=uploader,
            )
            if verify is not None:
                reviewer = reviewers[types[code].owning_department.code]
                review_document(doc, reviewer, verify=verify, note="Looks good." if verify else "Illegible scan.")
            return doc

        # Verified docs for the most advanced applicants.
        for app in Application.objects.filter(stage__in=["ADMITTED", "DEPOSITED"])[:10]:
            make(app.person, "HS_TRANSCRIPT", ana, verify=True)
            make(app.person, "GOVT_ID", ana, verify=True)
        # Avery's two, verified (checklist already marked received).
        make(self.avery, "HS_TRANSCRIPT", ana, verify=True)
        make(self.avery, "GOVT_ID", ana, verify=True)
        # A spread of pending items so review queues breathe.
        for app in Application.objects.filter(stage="APPLIED")[:6]:
            make(app.person, "HS_TRANSCRIPT", ana)  # pending in ADM queue
        for person in self.rng.sample(self.students, 3):
            make(person, "IMMUNIZATION", ana)       # pending in REG queue
        for person in self.rng.sample(self.students, 2):
            make(person, "FAFSA_SAR", rita)         # pending in FA queue
        make(self.jordan, "I9", rita)               # pending in HR queue
        # A rejected one for color.
        make(self.rng.choice(self.students), "GOVT_ID", ana, verify=False)

    # --------------------------------------------------------------- workflow

    def _workflow_extras(self):
        """Pending change requests (both policies) + referrals so every
        dashboard demonstrates the cross-department layer."""
        from core.models import DataDomain, Person
        from workflow.models import Task
        from workflow.services import (build_update_changes, create_task,
                                       submit_change_request)

        bob = self.users["bursar.bob"]
        fay = self.users["finaid.fay"]
        ana = self.users["admissions.ana"]
        rita = self.users["registrar.rita"]

        # APPLY_THEN_VERIFY: Bursar fixed addresses/phones at the counter —
        # live already, Registrar verifies. (Casey Fox is scripted in the demo,
        # so seed these on other students.)
        for person in self.rng.sample(self.students[3:], 5):
            original = Person.objects.get(pk=person.pk)
            person.primary_phone = self.faker.numerify("(555) ###-####")
            person.save()
            changes = build_update_changes(original, person, ["primary_phone"])
            submit_change_request(
                actor=bob, person=person, domain_code="BIOGRAPHIC",
                action="UPDATE", model_label="core.person", target=person,
                changes=changes, summary="Phone corrected at the bursar counter",
            )

        # HOLD_FOR_APPROVAL: FA proposes grade fixes; nothing applied yet.
        from academics.models import Enrollment

        for e in Enrollment.objects.filter(
                status=Enrollment.COMPLETED, grade="F",
                section__term=self.t_26sp)[:4]:
            submit_change_request(
                actor=fay, person=e.person, domain_code="ACADEMIC",
                action="UPDATE", model_label="academics.enrollment", target=e,
                changes={"grade": {"old": e.grade, "new": "C"}},
                summary="Instructor emailed a grade correction to the wrong office",
            )

        # Plain referrals between offices.
        referrals = [
            ("Student says aid award letter never arrived", ana, "FA", None),
            ("International applicant needs I-20 guidance", ana, "REG", None),
            ("Donor asking for 2025 giving receipt", self.users["advancement.ava"], "FIN", None),
            ("Employee W-2 address bounced", self.users["hr.hank"], "REG", self.jordan),
            ("Walk-in wants a payment plan", bob, "FA", self.casey),
        ]
        for title, creator, dept, person in referrals:
            create_task(
                title=title, task_type=Task.REFERRAL,
                assigned_department=self.depts[dept], person=person,
                originating_department=self.depts[
                    next(c for u, f, l, c, m in DEMO_STAFF if self.users[u] == creator)],
                description="Routed from the front desk — see person record for context.",
                created_by=creator,
                due_date=datetime.date(2026, 6, 18),
            )

        # One advising hold so registration-blocking is demoable beyond Sam.
        from workflow.models import HoldType
        from workflow.services import place_hold

        for person in self.rng.sample(self.students[3:], 3):
            place_hold(person, HoldType.objects.get(code="ADVISING"),
                       reason="Must meet advisor before 2026FA registration",
                       actor=rita)

    # ----------------------------------------------------- payroll & finance

    def _payroll_and_finance(self):
        from django.db.models import Sum

        from finance.models import (DepartmentBudget, GLAccount, JournalEntry,
                                    JournalLine)
        from hr.models import EmploymentRecord, Paycheck, PayrollRun

        finn = self.users["finance.finn"]

        records = list(EmploymentRecord.objects.filter(status="ACTIVE").select_related("person"))
        for month_start in [datetime.date(2026, 3, 1), datetime.date(2026, 4, 1), datetime.date(2026, 5, 1)]:
            month_end = (month_start.replace(day=28) + datetime.timedelta(days=4)).replace(day=1) - datetime.timedelta(days=1)
            run = PayrollRun.objects.create(
                period_start=month_start, period_end=month_end,
                pay_date=month_end, status=PayrollRun.POSTED,
            )
            for r in records:
                gross = (r.salary / 12).quantize(Decimal("0.01"))
                taxes = (gross * Decimal("0.22")).quantize(Decimal("0.01"))
                Paycheck.objects.create(payroll_run=run, person=r.person,
                                        gross=gross, taxes=taxes, net=gross - taxes)

        gl = {a.number: a for a in GLAccount.objects.all()}
        for dept in self.depts.values():
            for number, amount in [("5010", 280000), ("5200", 45000)]:
                DepartmentBudget.objects.get_or_create(
                    fiscal_year=self.fy, department=dept, gl_account=gl[number],
                    defaults={"amount": Decimal(amount)},
                )

        # A few posted JEs so budget-vs-actual isn't empty: monthly payroll.
        for month, label in [(3, "March"), (4, "April"), (5, "May")]:
            je = JournalEntry.objects.create(
                entry_date=datetime.date(2026, month, 28),
                description=f"{label} payroll", status=JournalEntry.DRAFT,
            )
            total = Decimal("0")
            for dept in self.depts.values():
                amount = Decimal(self.rng.randint(18, 30) * 1000)
                JournalLine.objects.create(entry=je, gl_account=gl["5010"],
                                           department=dept, debit=amount)
                total += amount
            JournalLine.objects.create(entry=je, gl_account=gl["1000"], credit=total)
            je.post(finn)

        # Tuition recognition JE.
        from student_accounts.models import LedgerEntry

        tuition_total = LedgerEntry.objects.filter(
            entry_type=LedgerEntry.CHARGE).aggregate(t=Sum("amount"))["t"] or Decimal("0")
        je = JournalEntry.objects.create(
            entry_date=datetime.date(2026, 5, 31),
            description="Student charges to revenue (YTD)", status=JournalEntry.DRAFT)
        JournalLine.objects.create(entry=je, gl_account=gl["1200"], debit=tuition_total)
        JournalLine.objects.create(entry=je, gl_account=gl["4000"], credit=tuition_total)
        je.post(finn)

    # ------------------------------------------------------------------ gifts

    def _gifts(self):
        from advancement.models import Designation, Pledge
        from advancement.services import record_gift

        ava = self.users["advancement.ava"]
        designations = list(Designation.objects.all())

        # Morgan Whitfield: the alumni donor who walks into Advancement after
        # getting married — SOP 1's demo persona. Reliable giving history so
        # Ava has a reason to have her at the desk.
        from advancement.models import AlumniInfo

        self.morgan = self._person("Morgan", "Whitfield",
                                   email="morgan.whitfield@example.com",
                                   dob=datetime.date(1990, 4, 17), banner="@00009876")
        self._address(self.morgan)
        self._affiliate(self.morgan, "ALUMNI", start=datetime.date(2012, 5, 19))
        AlumniInfo.objects.create(
            person=self.morgan, class_year=2012, degree_received="B.A. English",
            employer="Riverbend Publishing", job_title="Senior Editor",
        )
        scholar = Designation.objects.get(code="SCHOLAR")
        for year, amount in [(2022, 250), (2023, 250), (2024, 500), (2025, 500), (2026, 1000)]:
            record_gift(self.morgan, scholar, Decimal(amount), method="CARD",
                        gift_date=datetime.date(year, 5, 19), actor=ava)

        donors = self.rng.sample(self.alumni, 22) + [self.jordan, self.staff_people["registrar.ray"]]

        for person in donors:
            for _ in range(self.rng.randint(1, 6)):
                record_gift(
                    person, self.rng.choice(designations),
                    Decimal(self.rng.choice([25, 50, 100, 250, 500, 1000, 5000])),
                    method=self.rng.choice(["CHECK", "CARD", "STOCK", "CASH"]),
                    gift_date=self.faker.date_between("-5y", "today"),
                    actor=ava,
                )

        for person in self.rng.sample(donors, 6):
            pledge = Pledge.objects.create(
                person=person, designation=self.rng.choice(designations),
                total_amount=Decimal(self.rng.choice([1200, 2400, 6000])),
                start_date=datetime.date(2026, 1, 1),
                frequency="MONTHLY",
            )
            record_gift(person, pledge.designation, pledge.total_amount / 12,
                        method="CARD", gift_date=datetime.date(2026, 2, 1),
                        pledge=pledge, actor=ava)

    # ------------------------------------------------------------------ done

    def _print_cheatsheet(self):
        from core.models import Person
        from workflow.models import ChangeRequest, Hold, Task

        self.stdout.write(self.style.SUCCESS(
            "\n=== Hilltop College seeded ==========================================\n"))
        self.stdout.write(f"People: {Person.objects.count()}   "
                          f"Open tasks: {Task.objects.exclude(status='DONE').count()}   "
                          f"Active holds: {Hold.objects.filter(status='ACTIVE').count()}   "
                          f"Pending CRs: {ChangeRequest.objects.filter(status='PENDING').count()}")
        self.stdout.write("\nDemo logins (password for all: %s)" % PASSWORD)
        for username, first, last, dept, manager in DEMO_STAFF:
            self.stdout.write(f"  {username:<18} {first} {last:<10} — {dept}")
        self.stdout.write(
            "\nDemo personas:\n"
            "  Jordan Rivers    — student + employee + donor on one record\n"
            "  Sam Lee          — graduating senior blocked by a $1,240 bursar hold + library fine\n"
            "  Avery Cole      — DEPOSITED applicant, one click from enrollment\n"
            "  Casey Fox       — student whose address Bursar Bob fixes at the counter\n"
            "  Morgan Whitfield — alumni donor at the Advancement desk for a marriage\n"
            "                     name change (SOP 1: held until REG validates documents)\n")
