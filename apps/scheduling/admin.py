from django.contrib import admin

from apps.core.admin import SoftDeleteAdmin
from apps.scheduling.models import Appointment, Reminder


@admin.register(Appointment)
class AppointmentAdmin(SoftDeleteAdmin):
    list_display = ("title", "owner", "starts_at", "location", "source", "external_calendar_id")
    list_filter = ("source", "color")
    search_fields = ("title", "description", "location")
    date_hierarchy = "starts_at"


@admin.register(Reminder)
class ReminderAdmin(SoftDeleteAdmin):
    list_display = ("title", "owner", "remind_at", "status", "notification_sent_at")
    list_filter = ("status", "source")
    search_fields = ("title", "description")
    date_hierarchy = "remind_at"
