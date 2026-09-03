"""Rezumatul zilei si intrebarile puse despre el."""

from __future__ import annotations

from django.db import models

from apps.core.files import upload_to_brief_audio
from apps.core.models import OwnedModel, TimeStampedModel


class DailyBrief(OwnedModel, TimeStampedModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Se generează"
        READY = "ready", "Gata"
        FAILED = "failed", "Eșuat"

    date = models.DateField("ziua", db_index=True)
    #: Textul determinist, construit exclusiv din baza de date.
    generated_text = models.TextField("text", blank=True)
    #: Varianta reformulata de AI, validata sa nu introduca informatii noi.
    polished_text = models.TextField("text reformulat", blank=True)
    polish_rejected_reason = models.CharField(max_length=200, blank=True)
    audio_file = models.FileField("audio", upload_to=upload_to_brief_audio, blank=True)
    audio_duration_ms = models.PositiveIntegerField(default=0)
    #: Amprenta datelor din care s-a construit rezumatul; se regenereaza doar cand se schimba.
    source_hash = models.CharField(max_length=64, db_index=True)
    snapshot = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    generated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-date"]
        verbose_name = "Rezumat zilnic"
        verbose_name_plural = "Rezumate zilnice"
        constraints = [
            models.UniqueConstraint("owner", "date", name="un_rezumat_pe_zi")
        ]

    def __str__(self):
        return f"Rezumat {self.date:%d.%m.%Y}"

    @property
    def text(self) -> str:
        """Textul afisat: reformularea validata daca exista, altfel cel determinist."""
        return self.polished_text or self.generated_text

    @property
    def counts(self) -> dict[str, int]:
        return self.snapshot.get("counts", {})

    @property
    def has_content(self) -> bool:
        """Ziua are ceva de rezumat: o programare, o alarmă, un document sau un email.

        Cand este False nu generam audio si nu afisam butonul de redare — nu ar
        avea ce sa redea.
        """
        return any(self.counts.values())


class BriefQuestion(OwnedModel, TimeStampedModel):
    """„Întreabă despre ziua mea" — raspunsul se construieste tot din date reale."""

    brief = models.ForeignKey(DailyBrief, on_delete=models.CASCADE, related_name="questions")
    question = models.CharField(max_length=300)
    answer = models.TextField(blank=True)
    answered_from = models.CharField(max_length=20, default="deterministic")

    class Meta:
        ordering = ["created_at"]
        verbose_name = "Întrebare despre zi"
        verbose_name_plural = "Întrebări despre zi"

    def __str__(self):
        return self.question
