from django.contrib import admin

from apps.core.admin import SoftDeleteAdmin
from apps.documents.models import ScannedDocument


@admin.register(ScannedDocument)
class ScannedDocumentAdmin(SoftDeleteAdmin):
    list_display = (
        "__str__",
        "owner",
        "document_type",
        "processing_status",
        "ocr_confidence",
        "created_at",
    )
    list_filter = ("document_type", "processing_status")
    search_fields = ("title",)
    readonly_fields = (
        "deleted_at",
        "extracted_text",
        "extracted_data",
        "image_sha256",
        "ocr_provider",
    )
    date_hierarchy = "created_at"
