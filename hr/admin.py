from django.contrib import admin

from hr.models import EmploymentRecord, Paycheck, PayrollRun, Position


@admin.register(Position)
class PositionAdmin(admin.ModelAdmin):
    list_display = ("position_number", "title", "department", "gl_account", "is_faculty", "is_active")
    list_filter = ("department", "is_faculty")


@admin.register(EmploymentRecord)
class EmploymentRecordAdmin(admin.ModelAdmin):
    list_display = ("person", "position", "status", "hire_date")
    list_filter = ("status",)


class PaycheckInline(admin.TabularInline):
    model = Paycheck
    extra = 0


@admin.register(PayrollRun)
class PayrollRunAdmin(admin.ModelAdmin):
    list_display = ("period_start", "period_end", "pay_date", "status")
    inlines = [PaycheckInline]
