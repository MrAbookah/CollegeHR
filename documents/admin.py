from django.contrib import admin

from documents.models import Document, DocumentType


@admin.register(DocumentType)
class DocumentTypeAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "owning_department", "retention_note")


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ("person", "doc_type", "status", "uploaded_by", "created_at")
    list_filter = ("status", "doc_type")
