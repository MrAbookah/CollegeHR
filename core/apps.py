from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"

    def ready(self):
        from django.contrib.auth.signals import user_logged_in

        from core import audit

        # Person-data models whose every write belongs in the audit trail.
        # Workflow plumbing (Task, Notification, ChangeRequest) is excluded:
        # those rows ARE the record. Holds are audited explicitly with
        # HOLD_PLACE / HOLD_RELEASE actions in workflow.services.
        from core.models import (Affiliation, EmergencyContact, Person,
                                 PersonAddress, StaffMembership)

        audit.register(Person, PersonAddress, EmergencyContact, Affiliation, StaffMembership)

        from academics.models import (Enrollment, GraduationApplication,
                                      StudentProgram)
        from admissions.models import Application
        from advancement.models import Gift, Pledge
        from documents.models import Document
        from finaid.models import AidAward, Disbursement
        from hr.models import EmploymentRecord
        from student_accounts.models import LedgerEntry

        audit.register(
            Enrollment, StudentProgram, GraduationApplication, Application,
            LedgerEntry, AidAward, Disbursement, EmploymentRecord, Gift, Pledge,
            Document,
        )

        def _log_login(sender, request, user, **kwargs):
            person = getattr(user, "person", None)
            audit.log("LOGIN", actor=user, person=person, summary=f"{user.username} logged in")

        user_logged_in.connect(_log_login, dispatch_uid="core-login-audit")
