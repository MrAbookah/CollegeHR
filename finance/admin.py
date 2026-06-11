from django.contrib import admin

from finance.models import (DepartmentBudget, FiscalYear, GLAccount,
                            JournalEntry, JournalLine)

admin.site.register(FiscalYear)


@admin.register(GLAccount)
class GLAccountAdmin(admin.ModelAdmin):
    list_display = ("number", "name", "type", "is_active")
    list_filter = ("type",)


@admin.register(DepartmentBudget)
class DepartmentBudgetAdmin(admin.ModelAdmin):
    list_display = ("fiscal_year", "department", "gl_account", "amount")
    list_filter = ("fiscal_year", "department")


class LineInline(admin.TabularInline):
    model = JournalLine
    extra = 0


@admin.register(JournalEntry)
class JournalEntryAdmin(admin.ModelAdmin):
    list_display = ("entry_date", "description", "status")
    inlines = [LineInline]
