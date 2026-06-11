"""Reference data every installation needs: departments, data domains,
hold types, document types, charge codes, aid programs, designations, and
the chart of accounts. Shared by `seed_demo` and the test suite so both run
against the same governance configuration."""

import datetime

from core.models import DataDomain, Department

DEPARTMENTS = [
    ("ADM", "Admissions"),
    ("REG", "Registrar"),
    ("FA", "Financial Aid"),
    ("BUR", "Student Accounts (Bursar)"),
    ("HR", "Human Resources"),
    ("FIN", "Finance"),
    ("ADV", "Advancement"),
    ("LIB", "Library"),
]

# (code, name, owner dept, change policy)
DATA_DOMAINS = [
    ("BIOGRAPHIC", "Biographic & contact", "REG", DataDomain.APPLY_THEN_VERIFY),
    ("ADMISSIONS", "Admissions", "ADM", DataDomain.HOLD_FOR_APPROVAL),
    ("ACADEMIC", "Academic records", "REG", DataDomain.HOLD_FOR_APPROVAL),
    ("FINANCIAL_AID", "Financial aid", "FA", DataDomain.HOLD_FOR_APPROVAL),
    ("STUDENT_ACCOUNT", "Student accounts", "BUR", DataDomain.HOLD_FOR_APPROVAL),
    ("EMPLOYMENT", "Employment & payroll", "HR", DataDomain.HOLD_FOR_APPROVAL),
    ("FINANCE", "General ledger", "FIN", DataDomain.HOLD_FOR_APPROVAL),
    ("ADVANCEMENT", "Gifts & alumni", "ADV", DataDomain.HOLD_FOR_APPROVAL),
    ("DOCUMENT", "Documents", "REG", DataDomain.HOLD_FOR_APPROVAL),
]

# (code, name, owner dept, blocks_registration, blocks_transcript, blocks_graduation)
HOLD_TYPES = [
    ("BURSAR_BALANCE", "Past-due balance", "BUR", True, True, True),
    ("LIBRARY_FINE", "Library fine / unreturned materials", "LIB", False, False, True),
    ("ADVISING", "Advising required", "REG", True, False, False),
    ("IMMUNIZATION", "Immunization records missing", "REG", True, False, False),
    ("ADMISSIONS_DOCS", "Admissions documents outstanding", "ADM", True, False, False),
    ("DISCIPLINE", "Student conduct", "REG", True, True, True),
]

# (code, name, owner dept, retention note)
DOCUMENT_TYPES = [
    ("HS_TRANSCRIPT", "High school transcript", "ADM", "Retain 5 years after last attendance"),
    ("COLLEGE_TRANSCRIPT", "College transcript", "REG", "Permanent"),
    ("GOVT_ID", "Government ID", "REG", "Retain while affiliated"),
    ("RECOMMENDATION", "Recommendation letter", "ADM", "Retain 2 years after decision"),
    ("IMMUNIZATION", "Immunization record", "REG", "Retain 7 years"),
    ("FAFSA_SAR", "FAFSA student aid report", "FA", "Retain 3 years after aid year"),
    ("TAX_FORM", "Tax form", "FA", "Retain 3 years after aid year"),
    ("I9", "Form I-9", "HR", "Retain 3 years after hire or 1 year after separation"),
    ("GIFT_AGREEMENT", "Gift agreement", "ADV", "Permanent"),
]

# (code, description, default amount, GL account number)
CHARGE_CODES = [
    ("TUITION", "Tuition", "6250.00", "4000"),
    ("FEES", "Student activity fees", "425.00", "4010"),
    ("HOUSING", "Housing", "3100.00", "4020"),
    ("MEAL", "Meal plan", "2200.00", "4030"),
    ("LIBFINE", "Library fine", None, "4040"),
    ("PARKING", "Parking fine", None, "4040"),
]

# (code, name, source, aid type)
AID_PROGRAMS = [
    ("PELL", "Federal Pell Grant", "FEDERAL", "GRANT"),
    ("SEOG", "Federal SEOG", "FEDERAL", "GRANT"),
    ("STATE_GRANT", "State Grant", "STATE", "GRANT"),
    ("INST_SCHOL", "Hilltop Merit Scholarship", "INSTITUTIONAL", "SCHOLARSHIP"),
    ("DIRECT_SUB", "Direct Subsidized Loan", "FEDERAL", "LOAN"),
    ("WORKSTUDY", "Federal Work-Study", "FEDERAL", "WORKSTUDY"),
]

DESIGNATIONS = [
    ("ANNUAL", "Annual Fund"),
    ("SCHOLAR", "Scholarship Endowment"),
    ("LIBRARY", "Library Renovation"),
    ("ATHLETICS", "Athletics"),
]

# (number, name, type)
GL_ACCOUNTS = [
    ("1000", "Operating cash", "ASSET"),
    ("1200", "Student receivables", "ASSET"),
    ("2000", "Accounts payable", "LIABILITY"),
    ("3000", "Net assets", "NET_ASSET"),
    ("4000", "Tuition revenue", "REVENUE"),
    ("4010", "Fee revenue", "REVENUE"),
    ("4020", "Housing revenue", "REVENUE"),
    ("4030", "Dining revenue", "REVENUE"),
    ("4040", "Fines & other revenue", "REVENUE"),
    ("4100", "Gift revenue", "REVENUE"),
    ("5000", "Faculty salaries", "EXPENSE"),
    ("5010", "Staff salaries", "EXPENSE"),
    ("5100", "Benefits", "EXPENSE"),
    ("5200", "Supplies & services", "EXPENSE"),
    ("5300", "Institutional aid expense", "EXPENSE"),
]


def bootstrap_reference_data():
    """Idempotent: get_or_create everything. Returns dict of departments."""
    from decimal import Decimal

    from advancement.models import Designation
    from documents.models import DocumentType
    from finaid.models import AidProgram
    from finance.models import GLAccount
    from student_accounts.models import ChargeCode
    from workflow.models import HoldType

    depts = {}
    for code, name in DEPARTMENTS:
        depts[code], _ = Department.objects.get_or_create(code=code, defaults={"name": name})

    for code, name, owner, policy in DATA_DOMAINS:
        DataDomain.objects.get_or_create(
            code=code,
            defaults={"name": name, "owner_department": depts[owner], "change_policy": policy},
        )

    for code, name, owner, b_reg, b_tra, b_gra in HOLD_TYPES:
        HoldType.objects.get_or_create(
            code=code,
            defaults={
                "name": name, "owning_department": depts[owner],
                "blocks_registration": b_reg, "blocks_transcript": b_tra,
                "blocks_graduation": b_gra,
            },
        )

    for code, name, owner, retention in DOCUMENT_TYPES:
        DocumentType.objects.get_or_create(
            code=code,
            defaults={"name": name, "owning_department": depts[owner], "retention_note": retention},
        )

    gl = {}
    for number, name, gl_type in GL_ACCOUNTS:
        gl[number], _ = GLAccount.objects.get_or_create(
            number=number, defaults={"name": name, "type": gl_type}
        )

    for code, desc, amount, gl_number in CHARGE_CODES:
        ChargeCode.objects.get_or_create(
            code=code,
            defaults={
                "description": desc,
                "default_amount": Decimal(amount) if amount else None,
                "gl_account": gl[gl_number],
            },
        )

    for code, name, source, aid_type in AID_PROGRAMS:
        AidProgram.objects.get_or_create(
            code=code, defaults={"name": name, "source": source, "aid_type": aid_type}
        )

    for code, name in DESIGNATIONS:
        Designation.objects.get_or_create(code=code, defaults={"name": name})

    # Clear the permission layer's domain cache: tests and seeds may have
    # created domains after something already queried them.
    from core import permissions

    permissions.clear_domain_cache()
    return depts


def current_fiscal_year(today=None):
    today = today or datetime.date.today()
    start_year = today.year if today.month >= 7 else today.year - 1
    return f"FY{start_year + 1}", datetime.date(start_year, 7, 1), datetime.date(start_year + 1, 6, 30)
