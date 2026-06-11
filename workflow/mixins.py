"""
View mixins that make data governance automatic.

A domain edit view declares two things — its form and its `data_domain` —
and GovernedFormMixin routes the save: owners write directly; everyone else
generates a ChangeRequest per the domain's policy, with the verification
task and notifications fanned out to the owning department.
"""

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseRedirect

from core import permissions
from core.models import DataDomain, Person
from workflow.models import ChangeRequest
from workflow.services import (build_create_changes, build_update_changes,
                               submit_change_request)


class StaffRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return permissions.is_staff_member(self.request.user)


class GovernedFormMixin:
    data_domain = None  # subclasses must set, e.g. "BIOGRAPHIC"

    def user_owns_domain(self):
        """Hook: subclasses may extend (e.g. instructors own their own
        section's grades even though REG owns ACADEMIC)."""
        return permissions.can_edit_domain(self.request.user, self.data_domain)

    def get_governed_person(self, form):
        instance = form.instance
        if isinstance(instance, Person):
            return instance
        return instance.person

    def form_valid(self, form):
        assert self.data_domain, "GovernedFormMixin requires data_domain"
        user = self.request.user

        if self.user_owns_domain():
            self.object = form.save()
            messages.success(self.request, "Saved.")
            return HttpResponseRedirect(self.get_success_url())

        if not permissions.can_propose(user, self.data_domain):
            raise PermissionDenied("You do not have access to change this data.")

        is_create = form.instance.pk is None
        if is_create:
            changes = build_create_changes(form.instance)
            action = ChangeRequest.CREATE
        else:
            original = type(form.instance).objects.get(pk=form.instance.pk)
            changes = build_update_changes(original, form.instance, form.changed_data)
            action = ChangeRequest.UPDATE
            if not changes:
                messages.info(self.request, "No changes detected.")
                return HttpResponseRedirect(self.get_success_url())

        person = self.get_governed_person(form)
        policy = permissions.domain_policy(self.data_domain)
        applied = policy == DataDomain.APPLY_THEN_VERIFY
        if applied:
            self.object = form.save()  # live immediately; owner verifies after

        submit_change_request(
            actor=user,
            person=person,
            domain_code=self.data_domain,
            action=action,
            model_label=form.instance._meta.label_lower,
            target=form.instance if (applied or not is_create) else None,
            changes=changes,
        )

        owner = permissions.domain_owner_code(self.data_domain) or "the owning department"
        if applied:
            messages.success(
                self.request,
                f"Saved — and sent to {owner} to verify, since they own this data.",
            )
        else:
            messages.warning(
                self.request,
                f"Change submitted for approval. Nothing is updated until {owner} approves it.",
            )
        return HttpResponseRedirect(self.get_success_url())
