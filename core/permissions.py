"""
The single permission choke point.

Every view, form, and template asks these functions; nothing checks Django
groups directly. Rules are data-driven where departments should manage them
(DataDomain rows) and code-level where changes deserve code review
(read restrictions, field sensitivity).
"""

from functools import lru_cache

# Domains readable only by these departments (all other domains are readable
# by any staff member — that's the point of a shared hub).
RESTRICTED_READERS = {
    # Finance reads employment for budgeting, but the salary field stays
    # HR-only (SENSITIVE_FIELDS below) — they see the position, not the number.
    "EMPLOYMENT": {"HR", "FIN"},
    "FINANCE": {"FIN"},
    "STUDENT_ACCOUNT": {"BUR", "FA", "REG"},
    "FINANCIAL_AID": {"FA", "BUR", "REG"},
}

# model label -> {field: departments allowed to see it}
SENSITIVE_FIELDS = {
    "hr.employmentrecord": {"salary": {"HR"}},
    "core.person": {"ssn_last4": {"REG", "HR", "FA"}},
}

# Fields that are NEVER applied ahead of owner verification, even inside an
# APPLY_THEN_VERIFY domain. A legal name lives on transcripts, diplomas, and
# federal aid records — it changes only after the owning office validates
# documentation. (Contact info at the front desk stays instant.)
HELD_FIELDS = {
    "core.person": {"first_name", "last_name", "middle_name", "suffix"},
}

# Guidance attached to the verification task when held fields are touched.
HELD_FIELD_NOTES = {
    "core.person": (
        "Legal name change: contact the person, collect supporting "
        "documentation (e.g., marriage certificate or court order), upload it "
        "to their Documents, and only then approve. The record keeps the old "
        "name until approval; the full history stays in the audit trail."
    ),
}


def held_fields_for(model_label, changed_fields):
    """The subset of changed fields that must wait for owner approval."""
    return HELD_FIELDS.get(model_label, set()) & set(changed_fields)


@lru_cache(maxsize=None)
def _domain_owner(domain_code):
    from core.models import DataDomain

    try:
        domain = DataDomain.objects.select_related("owner_department").get(code=domain_code)
    except DataDomain.DoesNotExist:
        return None
    return domain.owner_department.code


@lru_cache(maxsize=None)
def _domain_policy(domain_code):
    from core.models import DataDomain

    try:
        return DataDomain.objects.get(code=domain_code).change_policy
    except DataDomain.DoesNotExist:
        return DataDomain.HOLD_FOR_APPROVAL


def clear_domain_cache():
    _domain_owner.cache_clear()
    _domain_policy.cache_clear()


def user_dept_codes(user):
    """Active department memberships, cached per request on the user object."""
    if not getattr(user, "is_authenticated", False):
        return set()
    cached = getattr(user, "_dept_codes", None)
    if cached is None:
        from core.models import StaffMembership

        cached = set(
            StaffMembership.objects.filter(
                person__user=user, end_date__isnull=True, department__is_active=True
            ).values_list("department__code", flat=True)
        )
        user._dept_codes = cached
    return cached


def is_staff_member(user):
    return bool(user_dept_codes(user)) or getattr(user, "is_superuser", False)


def can_view_domain(user, domain_code):
    if getattr(user, "is_superuser", False):
        return True
    depts = user_dept_codes(user)
    if not depts:
        return False
    restricted = RESTRICTED_READERS.get(domain_code)
    if restricted is None:
        return True
    return bool(depts & restricted) or _domain_owner(domain_code) in depts


def can_edit_domain(user, domain_code):
    if getattr(user, "is_superuser", False):
        return True
    return _domain_owner(domain_code) in user_dept_codes(user)


def can_propose(user, domain_code):
    # Any staff member may propose a change to any domain — this is what
    # makes "the other office does the data entry" possible at all.
    return is_staff_member(user)


def domain_policy(domain_code):
    return _domain_policy(domain_code)


def domain_owner_code(domain_code):
    return _domain_owner(domain_code)


def can_see_field(user, model_label, field_name):
    rules = SENSITIVE_FIELDS.get(model_label, {})
    allowed = rules.get(field_name)
    if allowed is None:
        return True
    if getattr(user, "is_superuser", False):
        return True
    return bool(user_dept_codes(user) & allowed)


def can_place_hold(user, hold_type):
    if getattr(user, "is_superuser", False):
        return True
    return hold_type.owning_department.code in user_dept_codes(user)


def can_release_hold(user, hold):
    return can_place_hold(user, hold.hold_type)


def is_member_of(user, department_code):
    if getattr(user, "is_superuser", False):
        return True
    return department_code in user_dept_codes(user)


def sync_department_groups(person):
    """Mirror active staff memberships into Django groups named dept:<CODE>.
    Groups exist only for admin-site convenience; enforcement happens here."""
    from django.contrib.auth.models import Group

    if not person.user:
        return
    wanted = {
        f"dept:{code}"
        for code in person.staff_memberships.filter(end_date__isnull=True).values_list(
            "department__code", flat=True
        )
    }
    current = set(person.user.groups.values_list("name", flat=True))
    for name in wanted - current:
        group, _ = Group.objects.get_or_create(name=name)
        person.user.groups.add(group)
    for name in current - wanted:
        if name.startswith("dept:"):
            person.user.groups.remove(Group.objects.get(name=name))
