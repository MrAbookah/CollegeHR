"""
Export the person roster to CSV for downstream systems — keyed on the
institutional ID (college_id).

This is the upstream half of the integration with a compliance overlay such as
CampusComply: the SIS owns identity and records and *feeds the roster out*;
the overlay subscribes by ID. Run on a schedule (nightly) in production.

    python manage.py export_roster --out roster.csv
"""
import csv

from django.core.management.base import BaseCommand

from core.models import Affiliation, Person

# CollegeDB affiliation type -> downstream constituency code. Types without a
# clean downstream equivalent (APPLICANT, RETIREE) are intentionally omitted.
CONSTITUENCY_MAP = {
    "STUDENT": "STUDENT", "EMPLOYEE": "EMPLOYEE", "FACULTY": "FACULTY",
    "ALUMNI": "ALUMNI", "DONOR": "DONOR",
}
# Offices whose staff routinely touch education records (drives FERPA training
# downstream). Best-effort derivation; the overlay can refine it.
RECORD_ACCESS_DEPTS = {"REG", "FA"}


class Command(BaseCommand):
    help = "Export the person roster to CSV (keyed on college_id) for downstream systems."

    def add_arguments(self, parser):
        parser.add_argument("--out", default="roster.csv", help="Output CSV path.")

    def handle(self, *args, **options):
        people = (
            Person.objects.filter(merged_into__isnull=True)
            .prefetch_related("affiliations", "staff_memberships__department")
            .order_by("college_id")
        )
        count = 0
        with open(options["out"], "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow([
                "school_id", "first_name", "last_name", "email",
                "constituencies", "is_international", "has_record_access", "status",
            ])
            for p in people:
                cons = sorted({
                    CONSTITUENCY_MAP[a.type]
                    for a in p.affiliations.all()
                    if a.status == Affiliation.ACTIVE and a.type in CONSTITUENCY_MAP
                })
                record_access = any(
                    m.end_date is None and m.department.code in RECORD_ACCESS_DEPTS
                    for m in p.staff_memberships.all()
                )
                writer.writerow([
                    p.college_id, p.first_name, p.last_name, p.primary_email,
                    ";".join(cons), "false",
                    "true" if record_access else "false",
                    "INACTIVE" if p.deceased else "ACTIVE",
                ])
                count += 1
        self.stdout.write(self.style.SUCCESS(f"Exported {count} people to {options['out']}"))
