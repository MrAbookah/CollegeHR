from django.contrib import admin

from advancement.models import AlumniInfo, Designation, Gift, Pledge

admin.site.register(Designation)


@admin.register(Gift)
class GiftAdmin(admin.ModelAdmin):
    list_display = ("person", "amount", "designation", "gift_date", "receipt_number")
    list_filter = ("designation", "method")
    search_fields = ("person__last_name", "receipt_number")


@admin.register(Pledge)
class PledgeAdmin(admin.ModelAdmin):
    list_display = ("person", "designation", "total_amount", "status")


@admin.register(AlumniInfo)
class AlumniInfoAdmin(admin.ModelAdmin):
    list_display = ("person", "class_year", "degree_received", "do_not_solicit")
