from django.contrib import admin

from finaid.models import AidAward, AidProgram, AidYear, Disbursement

admin.site.register(AidYear)
admin.site.register(AidProgram)


class DisbursementInline(admin.TabularInline):
    model = Disbursement
    extra = 0


@admin.register(AidAward)
class AidAwardAdmin(admin.ModelAdmin):
    list_display = ("person", "program", "aid_year", "amount_offered", "status")
    list_filter = ("aid_year", "program", "status")
    inlines = [DisbursementInline]
