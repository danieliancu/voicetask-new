from datetime import timedelta

from django import forms
from django.utils import timezone

from apps.core.mixins import UserFormKwargMixin
from apps.scheduling.models import Appointment, Reminder

REMINDER_OFFSETS = (
    (0, "La momentul evenimentului"),
    (10, "Cu 10 minute înainte"),
    (30, "Cu 30 de minute înainte"),
    (60, "Cu o oră înainte"),
    (1440, "Cu o zi înainte"),
    (2880, "Cu două zile înainte"),
)


class AppointmentForm(UserFormKwargMixin, forms.ModelForm):
    reminder_offset = forms.TypedChoiceField(
        label="Alarmă",
        choices=(("", "Fără alarmă"), *REMINDER_OFFSETS),
        coerce=int,
        empty_value=None,
        required=False,
    )

    class Meta:
        model = Appointment
        fields = ("title", "description", "location", "starts_at", "ends_at", "all_day", "color")
        widgets = {
            "starts_at": forms.DateTimeInput(
                attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"
            ),
            "ends_at": forms.DateTimeInput(
                attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"
            ),
            "description": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["starts_at"].input_formats = ["%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M"]
        self.fields["ends_at"].input_formats = ["%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M"]
        if self.instance.pk:
            existing = self.instance.reminders.filter(
                status=Reminder.Status.SCHEDULED
            ).order_by("remind_at").first()
            if existing:
                self.fields["reminder_offset"].initial = existing.offset_minutes

    def clean(self):
        data = super().clean()
        starts_at, ends_at = data.get("starts_at"), data.get("ends_at")
        if starts_at and ends_at and ends_at < starts_at:
            self.add_error("ends_at", "Sfârșitul nu poate fi înaintea începutului.")
        return data


class ReminderForm(UserFormKwargMixin, forms.ModelForm):
    class Meta:
        model = Reminder
        fields = ("title", "description", "remind_at", "appointment", "status")
        widgets = {
            "remind_at": forms.DateTimeInput(
                attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"
            ),
            "description": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["remind_at"].input_formats = ["%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M"]

    def limit_querysets(self) -> None:
        if self.user is not None:
            self.fields["appointment"].queryset = Appointment.objects.for_user(self.user).filter(
                starts_at__gte=timezone.now() - timedelta(days=30)
            )
        self.fields["appointment"].empty_label = "Fără programare"
        self.fields["appointment"].required = False
