"""Capturi vocale si schitele de intentie generate din ele."""

from __future__ import annotations

import uuid
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.files import upload_to_voice
from apps.core.models import OwnedModel, OwnedSoftDeleteModel, TimeStampedModel


class VoiceCapture(OwnedSoftDeleteModel, TimeStampedModel):
    """O inregistrare trimisa de browser. Fisierul audio se sterge dupa 7 zile."""

    class Status(models.TextChoices):
        PENDING = "pending", "În așteptare"
        TRANSCRIBING = "transcribing", "Se transcrie"
        PARSING = "parsing", "Se interpretează"
        READY = "ready", "Gata"
        FAILED = "failed", "Eșuat"

    uid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    audio = models.FileField("înregistrare", upload_to=upload_to_voice, blank=True)
    content_type = models.CharField(max_length=60, blank=True)
    duration_ms = models.PositiveIntegerField(default=0)
    transcript = models.TextField("transcriere", blank=True)
    transcript_confidence = models.FloatField(default=0.0)
    status = models.CharField(max_length=14, choices=Status.choices, default=Status.PENDING)
    error = models.CharField(max_length=300, blank=True)
    #: "create" sau "edit" — decide ce intentii sunt acceptate.
    mode = models.CharField(max_length=10, default="create")

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Captură vocală"
        verbose_name_plural = "Capturi vocale"

    def __str__(self):
        return f"Captură {self.uid}"


class IntentDraft(OwnedModel, TimeStampedModel):
    """Rezultatul interpretarii, editabil, inainte de a deveni un obiect real.

    Nimic nu se salveaza in aplicatie pana cand utilizatorul nu confirma schita.
    """

    class Status(models.TextChoices):
        DRAFT = "draft", "Schiță"
        NEEDS_CLARIFICATION = "clarify", "Necesită clarificare"
        CONFIRMED = "confirmed", "Confirmată"
        DISCARDED = "discarded", "Abandonată"

    uid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    capture = models.ForeignKey(
        VoiceCapture, on_delete=models.SET_NULL, null=True, blank=True, related_name="drafts"
    )
    intent = models.CharField(max_length=24, db_index=True)
    #: Payloadul validat de schema Pydantic.
    payload = models.JSONField(default=dict)
    confidence = models.FloatField(default=0.0)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT)
    clarification_question = models.CharField(max_length=300, blank=True)
    #: Candidatii pentru update_item / delete_item: [{"kind": ..., "pk": ..., "title": ...}]
    candidates = models.JSONField(default=list, blank=True)
    target_kind = models.CharField(max_length=20, blank=True)
    target_id = models.PositiveIntegerField(null=True, blank=True)
    source_text = models.TextField(blank=True)
    result_kind = models.CharField(max_length=20, blank=True)
    result_id = models.PositiveIntegerField(null=True, blank=True)
    expires_at = models.DateTimeField(db_index=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Schiță"
        verbose_name_plural = "Schițe"

    def __str__(self):
        return f"{self.intent} · {self.get_status_display()}"

    def save(self, *args, **kwargs):
        if not self.expires_at:
            self.expires_at = timezone.now() + timedelta(minutes=settings.DRAFT_TTL_MINUTES)
        super().save(*args, **kwargs)

    @property
    def is_expired(self) -> bool:
        return self.expires_at <= timezone.now()

    @property
    def is_open(self) -> bool:
        return self.status in {self.Status.DRAFT, self.Status.NEEDS_CLARIFICATION}
