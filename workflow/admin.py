from django.contrib import admin

from workflow.models import (ChangeRequest, Hold, HoldType, Notification,
                             Task, TaskComment)


@admin.register(HoldType)
class HoldTypeAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "owning_department",
                    "blocks_registration", "blocks_transcript", "blocks_graduation")


@admin.register(Hold)
class HoldAdmin(admin.ModelAdmin):
    list_display = ("person", "hold_type", "status", "amount", "placed_at")
    list_filter = ("status", "hold_type")
    search_fields = ("person__last_name", "person__college_id")


class CommentInline(admin.TabularInline):
    model = TaskComment
    extra = 0


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ("title", "task_type", "assigned_department", "status", "person", "created_at")
    list_filter = ("status", "task_type", "assigned_department")
    search_fields = ("title", "person__last_name")
    inlines = [CommentInline]


@admin.register(ChangeRequest)
class ChangeRequestAdmin(admin.ModelAdmin):
    list_display = ("pk", "person", "model_label", "action", "data_domain",
                    "status", "submitted_by", "submitted_at")
    list_filter = ("status", "data_domain")


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("recipient", "title", "created_at", "read_at")
