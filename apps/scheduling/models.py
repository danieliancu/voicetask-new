"""Programari si alarme."""

from __future__ import annotations

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse
from django.utils import timezone

from apps.core.enums import ColorToken, ItemKind, Source
from apps.core.models import OwnedSoftDeleteModel, TimeStampedModel
from apps.search.normalize import normalize


class Appointment(OwnedSoftDeleteModel, TimeStampedModel):
    cascade_relations = ("reminders",)

    title = models.CharField("titlu", max_length=200)
    description = models.TextField("descriere", blank=True)
    location = models.CharField("locație", max_length=200, blank=True)
    starts_at = models.DateTimeField("începe la", db_index=True)
    ends_at = models.DateTimeField("se termină la", null=True, blank=True)
    all_day = models.BooleanField("toată ziua", default=False)
    color = models.CharField(
        "culoare", max_length=10, choices=ColorToken.choices, default=ColorToken.VIOLET
    )
    icon = models.CharField("icon", max_length=40, default="calendar")
    source = models.CharField(
        "sursă", max_length=16, choices=Source.choices, default=Source.MANUAL, db_index=True
    )
    source_document = models.ForeignKey(
        "documents.ScannedDocument",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="appointments",
    )
    external_calendar_id = models.CharField(
        "id în calendarul extern", max_length=200, blank=True, db_index=True
    )
    external_synced_at = models.DateTimeField(null=True, blank=True, editable=False)
    match_text = models.TextField(editable=False, blank=True)

    class Meta:
        ordering = ["starts_at"]
        verbose_name = "Programare"
        verbose_name_plural = "Programări"
        indexes = [
            models.Index(fields=["owner", "starts_at"], name="appt_owner_start_idx"),
        ]
        constraints = [
            # Sincronizarea din Google Calendar trebuie sa fie idempotenta.
            models.UniqueConstraint(
                "owner",
                "external_calendar_id",
                condition=~models.Q(external_calendar_id=""),
                name="programare_externa_unica",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(ends_at__isnull=True)
                    | models.Q(ends_at__gte=models.F("starts_at"))
                ),
                name="programare_interval_valid",
            ),
        ]

    def __str__(self):
        return self.title

    def clean(self):
        if self.ends_at and self.starts_at and self.ends_at < self.starts_at:
            raise ValidationError({"ends_at": "Sfârșitul nu poate fi înaintea începutului."})

    def save(self, *args, **kwargs):
        self.match_text = normalize(f"{self.title} {self.description} {self.location}")
        if kwargs.get("update_fields") is not None:
            kwargs["update_fields"] = {*kwargs["update_fields"], "match_text"}
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("scheduling:detail", args=[self.pk])

    @property
    def kind(self) -> str:
        return ItemKind.APPOINTMENT

    @property
    def color_token(self) -> str:
        return self.color

    @property
    def is_external(self) -> bool:
        return bool(self.external_calendar_id)

    @property
    def duration(self) -> timedelta | None:
        return (self.ends_at - self.starts_at) if self.ends_at else None


class Reminder(OwnedSoftDeleteModel, TimeStampedModel):
    class Status(models.TextChoices):
        SCHEDULED = "scheduled", "Programată"
        SENT = "sent", "Trimisă"
        SNOOZED = "snoozed", "Amânată"
        DONE = "done", "Rezolvată"
        CANCELLED = "cancelled", "Anulată"

    title = models.CharField("titlu", max_length=200)
    description = models.TextField("descriere", blank=True)
    remind_at = models.DateTimeField("sună la", db_index=True)
    status = models.CharField(
        "stare", max_length=12, choices=Status.choices, default=Status.SCHEDULED, db_index=True
    )
    offset_minutes = models.PositiveIntegerField("decalaj față de eveniment", default=0)
    source = models.CharField(
        "sursă", max_length=16, choices=Source.choices, default=Source.MANUAL
    )

    appointment = models.ForeignKey(
        Appointment,
        verbose_name="programare",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="reminders",
    )
    note = models.ForeignKey(
        "notes.Note",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reminders",
    )
    document = models.ForeignKey(
        "documents.ScannedDocument",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reminders",
    )
    email_reference = models.ForeignKey(
        "integrations.EmailReference",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reminders",
    )

    notification_sent_at = models.DateTimeField(null=True, blank=True, editable=False)
    match_text = models.TextField(editable=False, blank=True)

    class Meta:
        ordering = ["remind_at"]
        verbose_name = "Alarmă"
        verbose_name_plural = "Alarme"
        indexes = [
            models.Index(fields=["owner", "remind_at"], name="reminder_owner_when_idx"),
            models.Index(fields=["status", "remind_at"], name="reminder_status_when_idx"),
        ]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        self.match_text = normalize(f"{self.title} {self.description}")
        if kwargs.get("update_fields") is not None:
            kwargs["update_fields"] = {*kwargs["update_fields"], "match_text"}
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("scheduling:reminder_detail", args=[self.pk])

    @property
    def kind(self) -> str:
        return ItemKind.REMINDER

    @property
    def color_token(self) -> str:
        return ColorToken.ORANGE if self.is_overdue else ColorToken.VIOLET

    @property
    def is_overdue(self) -> bool:
        return self.status == self.Status.SCHEDULED and self.remind_at < timezone.now()

    @property
    def related_object(self):
        return self.appointment or self.note or self.document or self.email_reference

    def snooze(self, minutes: int = 10) -> None:
        self.remind_at = timezone.now() + timedelta(minutes=minutes)
        self.status = self.Status.SNOOZED
        self.notification_sent_at = None
        self.save(update_fields=["remind_at", "status", "notification_sent_at", "updated_at"])
