"""
Duplicate-person prevention — the cure for Banner's duplicate-PIDM disease.

Staff must search before they can create (the create form carries a signed
token proving a search ran), and the create flow shows scored candidates
before allowing a forced create with justification.
"""

from dataclasses import dataclass, field

from django.core import signing
from django.db import connection

from core.models import Person

DEFINITE, STRONG, WEAK = 1.0, 0.8, 0.5
INTERSTITIAL_THRESHOLD = 0.5
_TOKEN_SALT = "person-search"
_TOKEN_MAX_AGE = 30 * 60  # seconds


@dataclass
class ScoredMatch:
    person: Person
    score: float
    reasons: list = field(default_factory=list)


def issue_search_token():
    return signing.TimestampSigner(salt=_TOKEN_SALT).sign("searched")


def validate_search_token(token):
    try:
        signing.TimestampSigner(salt=_TOKEN_SALT).unsign(token, max_age=_TOKEN_MAX_AGE)
        return True
    except (signing.BadSignature, signing.SignatureExpired):
        return False


def find_candidates(first_name, last_name, date_of_birth=None, email=None,
                    ssn_last4=None, exclude_pk=None):
    """Score possible duplicates. Exact email or SSN4+DOB are definite;
    fuzzy name + same DOB is strong; fuzzy name alone is weak."""
    base = Person.objects.filter(merged_into__isnull=True)
    if exclude_pk:
        base = base.exclude(pk=exclude_pk)

    matches = {}

    def add(person, score, reason):
        m = matches.setdefault(person.pk, ScoredMatch(person=person, score=0.0))
        m.score = max(m.score, score)
        if reason not in m.reasons:
            m.reasons.append(reason)

    if email:
        for p in base.filter(primary_email__iexact=email):
            add(p, DEFINITE, "same email address")
    if ssn_last4 and date_of_birth:
        for p in base.filter(ssn_last4=ssn_last4, date_of_birth=date_of_birth):
            add(p, DEFINITE, "same SSN last-4 and date of birth")

    if first_name and last_name:
        if connection.vendor == "postgresql":
            from django.contrib.postgres.search import TrigramSimilarity

            similar = (
                base.annotate(
                    lsim=TrigramSimilarity("last_name", last_name),
                    fsim=TrigramSimilarity("first_name", first_name),
                )
                .filter(lsim__gte=0.4)
                .order_by("-lsim")[:10]
            )
            for p in similar:
                name_score = (p.lsim + p.fsim) / 2
                if date_of_birth and p.date_of_birth == date_of_birth and name_score >= 0.4:
                    add(p, STRONG, "similar name and same date of birth")
                elif name_score >= 0.5:
                    add(p, WEAK, "similar name")
        else:
            # SQLite fallback: substring matching only.
            for p in base.filter(last_name__icontains=last_name[:4])[:20]:
                if date_of_birth and p.date_of_birth == date_of_birth:
                    add(p, STRONG, "similar name and same date of birth")
                elif p.first_name.lower().startswith(first_name[:3].lower()):
                    add(p, WEAK, "similar name")

    return sorted(matches.values(), key=lambda m: -m.score)


def search_people(query, limit=25):
    """Global person search: ID, email, or fuzzy name."""
    query = (query or "").strip()
    if not query:
        return Person.objects.none()
    base = Person.objects.filter(merged_into__isnull=True)
    if query.upper().startswith("C") and query[1:].isdigit():
        return base.filter(college_id__iexact=query)
    if "@" in query:
        return base.filter(primary_email__icontains=query)[:limit]
    if connection.vendor == "postgresql":
        from django.contrib.postgres.search import TrigramSimilarity
        from django.db.models import Q, Value
        from django.db.models.functions import Concat

        return (
            base.annotate(
                full=Concat("first_name", Value(" "), "last_name"),
            )
            .annotate(sim=TrigramSimilarity("full", query))
            .filter(Q(sim__gte=0.25) | Q(last_name__icontains=query)
                    | Q(first_name__icontains=query) | Q(preferred_name__icontains=query))
            .order_by("-sim")[:limit]
        )
    from django.db.models import Q

    return base.filter(
        Q(last_name__icontains=query) | Q(first_name__icontains=query)
        | Q(preferred_name__icontains=query)
    )[:limit]


def merge(survivor, duplicate, actor):
    """Repoint everything from `duplicate` onto `survivor` and mark the
    duplicate merged. Affiliations that would collide with an active one on
    the survivor are deactivated instead of moved."""
    from django.db import transaction

    from core import audit
    from core.models import Affiliation

    if duplicate.pk == survivor.pk:
        raise ValueError("Cannot merge a person into themselves")
    if duplicate.merged_into_id:
        raise ValueError("This record was already merged")

    with transaction.atomic():
        for aff in duplicate.affiliations.all():
            collision = survivor.affiliations.filter(
                type=aff.type, status=Affiliation.ACTIVE
            ).exists()
            if collision and aff.status == Affiliation.ACTIVE:
                aff.status = Affiliation.INACTIVE
            aff.person = survivor
            aff.save()

        for rel in Person._meta.related_objects:
            accessor_model = rel.related_model
            field_name = rel.field.name
            if accessor_model is Person and field_name == "merged_into":
                continue
            if accessor_model is Affiliation:
                continue  # handled above
            if rel.one_to_one:
                if getattr(survivor, rel.get_accessor_name(), None) is None:
                    accessor_model.objects.filter(**{field_name: duplicate}).update(
                        **{field_name: survivor}
                    )
                continue
            accessor_model.objects.filter(**{field_name: duplicate}).update(
                **{field_name: survivor}
            )

        duplicate.merged_into = survivor
        duplicate.save()
        audit.log(
            "MERGE", survivor, actor=actor,
            summary=f"Merged duplicate {duplicate.college_id} into {survivor.college_id}",
        )
        audit.log(
            "MERGE", duplicate, person=duplicate, actor=actor,
            summary=f"Record merged into {survivor.college_id}",
        )
