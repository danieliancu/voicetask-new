from django.contrib import admin

from apps.assistant.models import IntentDraft, VoiceCapture
from apps.core.admin import SoftDeleteAdmin


@admin.register(VoiceCapture)
class VoiceCaptureAdmin(SoftDeleteAdmin):
    list_display = ("uid", "owner", "status", "duration_ms", "created_at")
    list_filter = ("status", "mode")
    readonly_fields = ("deleted_at", "uid", "transcript", "transcript_confidence")


@admin.register(IntentDraft)
class IntentDraftAdmin(admin.ModelAdmin):
    list_display = ("uid", "owner", "intent", "status", "confidence", "expires_at")
    list_filter = ("intent", "status")
    readonly_fields = ("uid", "payload", "candidates", "source_text")
