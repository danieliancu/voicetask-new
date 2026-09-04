"""Preferintele utilizatorului."""

from __future__ import annotations

import zoneinfo
from datetime import time

from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel

TIMEZONE_CHOICES = [(name, name) for name in sorted(zoneinfo.available_timezones()) if "/" in name]


class UserPreference(TimeStampedModel):
    class Language(models.TextChoices):
        RO = "ro", "Română"
        EN = "en", "English"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="preferences"
    )
    display_name = models.CharField("nume afișat", max_length=80, blank=True)
    language = models.CharField(
        "limbă", max_length=5, choices=Language.choices, default=Language.RO
    )
    timezone = models.CharField(
        "fus orar", max_length=64, default="Europe/Bucharest", choices=TIMEZONE_CHOICES
    )
    brief_time = models.TimeField("ora rezumatului", default=time(7, 30))
    brief_audio_enabled = models.BooleanField("rezumat audio", default=True)
    brief_polish_enabled = models.BooleanField("îmbunătățire AI a textului", default=False)
    notifications_enabled = models.BooleanField("notificări", default=True)
    default_reminder_offset = models.PositiveIntegerField(
        "decalaj implicit al alarmei (minute)", default=30
    )

    class Meta:
        verbose_name = "Preferință"
        verbose_name_plural = "Preferințe"

    def __str__(self):
        return f"Preferințe · {self.user}"

    @property
    def tzinfo(self) -> zoneinfo.ZoneInfo:
        try:
            return zoneinfo.ZoneInfo(self.timezone)
        except (zoneinfo.ZoneInfoNotFoundError, ValueError):
            # `ValueError` acopera valorile goale sau malformate: preferinta este
            # citita la fiecare comanda vocala si nu are voie sa arunce acolo.
            return zoneinfo.ZoneInfo("Europe/Bucharest")

    @property
    def greeting_name(self) -> str:
        return self.display_name or self.user.first_name or self.user.get_username()

    @classmethod
    def for_user(cls, user) -> UserPreference:
        prefs, _ = cls.objects.get_or_create(user=user)
        return prefs
