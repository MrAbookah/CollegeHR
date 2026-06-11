from django.contrib import admin

from student_accounts.models import ChargeCode, LedgerEntry


@admin.register(ChargeCode)
class ChargeCodeAdmin(admin.ModelAdmin):
    list_display = ("code", "description", "default_amount", "gl_account")


@admin.register(LedgerEntry)
class LedgerEntryAdmin(admin.ModelAdmin):
    list_display = ("person", "entry_type", "amount", "description", "effective_date")
    list_filter = ("entry_type", "term")
    search_fields = ("person__last_name", "description")
