from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin

from core import dedup
from core.models import (Affiliation, AuditLog, DataDomain, Department,
                         EmergencyContact, Person, PersonAddress,
                         StaffMembership, User)

admin.site.site_header = "CollegeDB administration"
admin.site.site_title = "CollegeDB admin"


@admin.register(User)
class CollegeUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (("SSO", {"fields": ("sso_subject",)}),)


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "is_active")


@admin.register(DataDomain)
class DataDomainAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "owner_department", "change_policy")
    list_filter = ("change_policy",)


class AffiliationInline(admin.TabularInline):
    model = Affiliation
    extra = 0


class AddressInline(admin.TabularInline):
    model = PersonAddress
    extra = 0


class MembershipInline(admin.TabularInline):
    model = StaffMembership
    fk_name = "person"
    extra = 0


@admin.register(Person)
class PersonAdmin(admin.ModelAdmin):
    list_display = ("college_id", "last_name", "first_name", "primary_email", "merged_into")
    search_fields = ("college_id", "last_name", "first_name", "primary_email", "banner_id")
    inlines = [AffiliationInline, AddressInline, MembershipInline]
    actions = ["merge_selected"]
    readonly_fields = ("college_id", "merged_into")

    @admin.action(description="Merge selected people (oldest record survives)")
    def merge_selected(self, request, queryset):
        people = list(queryset.order_by("pk"))
        if len(people) < 2:
            self.message_user(request, "Select at least two records to merge.", messages.ERROR)
            return
        survivor, *duplicates = people
        for dup in duplicates:
            dedup.merge(survivor, dup, request.user)
        self.message_user(
            request,
            f"Merged {len(duplicates)} record(s) into {survivor.college_id}.",
            messages.SUCCESS,
        )


@admin.register(EmergencyContact)
class EmergencyContactAdmin(admin.ModelAdmin):
    list_display = ("person", "name", "relationship", "phone")


@admin.register(StaffMembership)
class StaffMembershipAdmin(admin.ModelAdmin):
    list_display = ("person", "department", "role", "start_date", "end_date")
    list_filter = ("department",)


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    """Read-only: the audit trail is append-only even for superusers."""

    list_display = ("timestamp", "actor", "action", "person", "summary")
    list_filter = ("action",)
    search_fields = ("summary", "person__last_name", "person__college_id")
    date_hierarchy = "timestamp"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
