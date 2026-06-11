# CollegeDB

An in-house college ERP/SIS that replaces **Ellucian (Banner/Colleague)** and
**Perceptive Content** — and overlaps **Slate** — for a small college. One
database usable by every department, with the layer the incumbents are
missing built in: **cross-department workflow** (tasks, verifications, holds,
notifications) on top of a single person record.

## Why this exists

Every department touches the same humans, but legacy campus systems keep
them in silos: re-keyed data, "call the registrar" hold phone-tag, shadow
spreadsheets, and lost emails. Ellucian sells the fix as a separate add-on
("Ellucian Workflow"). Here it is the spine of the system.

### The core ideas

1. **One Person row per human, forever** (Banner's PIDM done deliberately).
   A person can be applicant + student + employee + alumni + donor at once —
   roles stack as affiliations on the same record. Search-before-create with
   fuzzy matching (pg_trgm) prevents Banner's duplicate-PIDM disease; staff
   can force-create only with an audited justification, and admins can merge.
2. **Data governance in software, not in a binder.** Every data domain
   (biographic, academic, money, employment…) has an *owning department*
   (`DataDomain` table). Owners edit directly. Everyone else's edit becomes a
   **ChangeRequest** under one of two policies:
   - `APPLY_THEN_VERIFY` (biographic): the fix goes live immediately — the
     student at your counter sees it done — and the owning office gets a
     verification task. Reject = automatic revert.
   - `HOLD_FOR_APPROVAL` (grades, money, employment): nothing changes until
     the owner approves. Stale approvals are caught by a conflict guard.
3. **Holds are the cross-department blocking layer.** Bursar balance blocks
   registration/transcript/graduation; library fines block graduation; only
   the *owning* department can release its hold — and balance holds
   place/release **themselves** the moment the ledger moves.
4. **Lifecycle hooks kill re-keying.** Enrolling an admit creates the student
   affiliation + program and routes an advisor task to the Registrar and a
   heads-up to Financial Aid. Awarding a degree creates the alumni record and
   tells Advancement. A first gift creates the donor badge. An aid
   disbursement posts to the bursar ledger in the same transaction.
5. **FERPA is built in.** Append-only audit log of every create/update/delete
   *and* every sensitive read (360 tabs, transcript, salary, document opens),
   field-level sensitivity (salary is HR-only even for departments that can
   read employment), directory-information opt-out banners.
6. **GL segments tie out.** Position control, Banner-style: a Position links
   its **department** and the **GL account** that funds it; a person fills
   the position. Charge codes map to revenue accounts; budgets are
   department × GL; journal lines carry both. Money traces person → position
   → department → GL.

## Stack

Django 5.2 LTS · PostgreSQL 16 (pg_trgm) · server-rendered templates +
~70 lines of vanilla JS · no build step, no broker, no background workers.
Local password auth now; the SSO swap point is documented in
`collegedb/settings.py` (custom User model with an `sso_subject` column is
already in place).

## Run it

```bash
# 1. PostgreSQL (either a local server or docker)
docker compose up -d            # postgres:16 on localhost:5432
# 2. Python deps
pip install -r requirements-dev.txt
# 3. Migrate + seed the demo college
python manage.py migrate
python manage.py seed_demo --flush
# 4. Go
python manage.py runserver
```

No Postgres handy? `DB_FALLBACK_SQLITE=1 python manage.py …` boots on SQLite
(duplicate detection degrades to substring matching).

### Demo logins (password: `demo1234`)

| Login | Office |
|---|---|
| `registrar.rita` | Registrar (owns biographic + academic data) |
| `bursar.bob` | Student Accounts |
| `admissions.ana` | Admissions |
| `finaid.fay` | Financial Aid |
| `hr.hank` | Human Resources |
| `finance.finn` | Finance |
| `advancement.ava` | Advancement |
| `library.lee` | Library |

Django admin (reference data, audit browser, person merge):
`python manage.py createsuperuser`.

### The 10-minute demo script

1. **One person, many hats** — as `registrar.rita`, search *Jordan Rivers*:
   one record wearing Student + Employee + Donor badges; tab through
   Academics, Employment, Advancement; the Activity tab is the FERPA trail.
2. **Duplicate prevention** — try creating "Jordan Riverz" with the same DOB:
   the interstitial catches it; force-create demands a justification that
   lands in the audit log.
3. **B enters, A verifies** — as `bursar.bob`, edit *Casey Fox*'s address
   (Registrar-owned, apply-then-verify): it saves instantly and flashes
   "sent to REG to verify". As `rita`, the bell shows the task; open it, see
   the old→new diff, Approve — or Reject and watch it revert.
4. **Held changes** — as `bob`, try a grade change: nothing applies until
   `rita` approves (and a conflicting later edit flips it to CONFLICT
   instead of clobbering).
5. **Holds that release themselves** — as `rita`, register *Sam Lee*:
   blocked, banner names the $1,240 bursar hold. As `bob`, post a $1,240
   payment: the hold auto-releases (audited as system), Sam's advisor gets a
   note. Re-register Sam: it works.
6. **Graduation clearance board** — `/academics/graduation/`: rows =
   candidates, columns = offices. Clear BUR as `bob`, LIB as `lee`, REG as
   `rita`, then Award: Sam flips to alum, Advancement is notified, a gift
   recorded by `ava` adds the Donor badge. Applicant → student → alum →
   donor, one row.
7. **Admissions to everywhere** — as `ana`, move *Avery Cole* from DEPOSITED
   to ENROLLED: student affiliation + program appear, Registrar gets an
   "assign advisor" task, FA gets a heads-up.
8. **Documents (Perceptive replacement)** — upload an HS transcript: a
   review task lands in the owning office's queue; verifying it
   auto-completes the matching admissions checklist item.
9. **Field-level FERPA** — Jordan's salary: visible to `hr.hank` (and the
   *view* is audit-logged), masked as ••• for `finance.finn`, invisible
   department-wide to everyone else.
10. **/reports** — shared definitions for headcount, enrollment, A/R aging,
    giving. One truth.

## Tests

```bash
pytest        # 52 tests: permission matrix, dedup, change-request engine,
              # registration guards, hold automation, graduation fan-out,
              # lifecycle hooks, FERPA view logging
```

## Project layout

```
core/              Person hub, affiliations, departments, DataDomain governance,
                   audit trail, dedup/merge, permission choke point
workflow/          Task, Notification, Hold, ChangeRequest + services (the spine)
documents/         Capture → owning-office review queue → checklist linkage
academics/         Terms, catalog, sections, registration, grades, transcripts,
                   programs, degree audit, graduation clearance
admissions/        Pipeline (inquiry→enrolled), checklists, communications log
finaid/            Aid years/programs/awards, disbursement → ledger
student_accounts/  Bursar ledger, balance automation → holds
hr/                Positions (dept + GL funding), employment, payroll
finance/           GL accounts, department budgets, balanced journal entries
advancement/       Gifts, pledges, designations, alumni records
```

## Migrating off Banner (the path)

`Person.banner_id` and stable natural keys (`Term.code`, `Subject.code` +
course number, charge/hold/document codes) exist from day one. The intended
import pattern is a `BaseCsvImporter` + `manage.py import_csv <kind> <path>
--dry-run` per Banner export (SPRIDEN→Person, SGBSTDN→affiliations,
SSBSECT→sections, SFRSTCR→enrollments, TBRACCD→ledger, RPRAWRD→awards),
upserting on those keys with per-row error reports. Importers are not built
yet — the schema is shaped so they're cheap.

## Production notes

- Set `SECRET_KEY`, `DEBUG=0`, `ALLOWED_HOSTS`, and a managed `DATABASE_URL`.
- `REVOKE UPDATE, DELETE ON core_auditlog FROM app_role;` — the audit table
  is append-only at the application layer; enforce it in Postgres too.
- Swap `MEDIA_ROOT` for object storage before real documents arrive.
- SSO: add an OIDC/SAML backend, map the IdP subject to `User.sso_subject`.
