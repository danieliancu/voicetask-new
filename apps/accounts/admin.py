from django.contrib import admin

from apps.accounts.models import UserPreference


@admin.register(UserPreference)
class UserPreferenceAdmin(admin.ModelAdmin):
    list_display = ("user", "language", "timezone", "brief_time", "notifications_enabled")
    list_filter = ("language", "notifications_enabled", "brief_audio_enabled")
    search_fields = ("user__username", "display_name")
