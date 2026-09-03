from django.urls import reverse

from apps.core import dates_ro
from apps.core.enums import ItemKind
from apps.scheduling.models import Appointment, Reminder
from apps.search.registry import SearchHit, SearchSource, register


class AppointmentSource(SearchSource):
    key = "programari"
    label = "Programări"
    icon = "calendar"
    search_fields = ("title", "description", "location")

    def queryset(self, user):
        return Appointment.objects.for_user(user)

    def order_field(self) -> str:
        return "-starts_at"

    def to_hit(self, obj: Appointment, *, score: float = 0.0) -> SearchHit:
        subtitle = (
            f"{dates_ro.relative_day_label(obj.starts_at)} • {dates_ro.format_time(obj.starts_at)}"
        )
        return SearchHit(
            kind=ItemKind.APPOINTMENT,
            pk=obj.pk,
            title=obj.title,
            subtitle=f"{subtitle}{' • ' + obj.location if obj.location else ''}",
            source_label="Google Calendar" if obj.is_external else "Programare",
            source_icon="calendar",
            color_token=obj.color_token,
            url=reverse("scheduling:detail", args=[obj.pk]),
            when=obj.starts_at,
            tab_label=dates_ro.short_tab_label(obj.starts_at),
            score=score,
        )


class ReminderSource(SearchSource):
    key = "alarme"
    label = "Alarme"
    icon = "bell"
    search_fields = ("title", "description")

    def queryset(self, user):
        return Reminder.objects.for_user(user)

    def order_field(self) -> str:
        return "-remind_at"

    def to_hit(self, obj: Reminder, *, score: float = 0.0) -> SearchHit:
        return SearchHit(
            kind=ItemKind.REMINDER,
            pk=obj.pk,
            title=obj.title,
            subtitle=(
                f"{dates_ro.relative_day_label(obj.remind_at)} • "
                f"{dates_ro.format_time(obj.remind_at)}"
            ),
            source_label="Alarmă",
            source_icon="bell",
            color_token=obj.color_token,
            url=reverse("scheduling:reminder_detail", args=[obj.pk]),
            when=obj.remind_at,
            tab_label=dates_ro.short_tab_label(obj.remind_at),
            score=score,
        )


register(AppointmentSource())
register(ReminderSource())
