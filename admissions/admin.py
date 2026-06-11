from django.contrib import admin

from admissions.models import (Application, ApplicationChecklistItem,
                               CommunicationLog)


class ChecklistInline(admin.TabularInline):
    model = ApplicationChecklistItem
    extra = 0


@admin.register(Application)
class ApplicationAdmin(admin.ModelAdmin):
    list_display = ("person", "program", "term", "stage", "source")
    list_filter = ("stage", "term", "source")
    search_fields = ("person__last_name",)
    inlines = [ChecklistInline]


@admin.register(CommunicationLog)
class CommunicationLogAdmin(admin.ModelAdmin):
    list_display = ("person", "channel", "direction", "subject", "occurred_at")
