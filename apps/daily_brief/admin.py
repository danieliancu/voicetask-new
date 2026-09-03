from django.contrib import admin

from apps.daily_brief.models import BriefQuestion, DailyBrief


@admin.register(DailyBrief)
class DailyBriefAdmin(admin.ModelAdmin):
    list_display = ("date", "owner", "status", "generated_at", "polish_rejected_reason")
    list_filter = ("status", "date")
    readonly_fields = ("source_hash", "snapshot", "generated_text", "polished_text")
    date_hierarchy = "date"


@admin.register(BriefQuestion)
class BriefQuestionAdmin(admin.ModelAdmin):
    list_display = ("question", "owner", "answered_from", "created_at")
    readonly_fields = ("question", "answer")
