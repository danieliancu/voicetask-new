"""Documente fotografiate si datele extrase din ele prin OCR."""

from __future__ import annotations

from django.db import models
from django.urls import reverse

from apps.core.enums import ColorToken, ItemKind
from apps.core.files import upload_to_processed, upload_to_scans
from apps.core.models import OwnedSoftDeleteModel, TimeStampedModel
from apps.search.normalize import normalize


class ScannedDocument(OwnedSoftDeleteModel, TimeStampedModel):
    class DocumentType(models.TextChoices):
        INVOICE = "invoice", "Factură"
        INVITATION = "invitation", "Invitație"
        LETTER = "letter", "Scrisoare"
        RECEIPT = "receipt", "Bon / chitanță"
        MEDICAL = "medical", "Document medical"
        OTHER = "other", "Alt document"

    class Status(models.TextChoices):
        PENDING = "pending", "În așteptare"
        PROCESSING = "processing", "Se procesează"
        READY = "ready", "Gata de verificat"
        CONFIRMED = "confirmed", "Confirmat"
        FAILED = "failed", "Eșuat"

    original_image = models.ImageField("fotografie", upload_to=upload_to_scans)
    processed_image = models.ImageField(
        "imagine procesată", upload_to=upload_to_processed, blank=True
    )
    image_sha256 = models.CharField(max_length=64, blank=True, db_index=True, editable=False)

    title = models.CharField("titlu", max_length=200, blank=True)
    document_type = models.CharField(
        "tip", max_length=20, choices=DocumentType.choices, default=DocumentType.OTHER
    )
    extracted_text = models.TextField("text recunoscut", blank=True)
    #: Campurile structurate: {"due_date": {"value": "2026-09-06", "confidence": 0.8}, ...}
    extracted_data = models.JSONField("date extrase", default=dict, blank=True)
    ocr_confidence = models.FloatField("încredere OCR", default=0.0)
    ocr_provider = models.CharField(max_length=60, blank=True, editable=False)
    processing_status = models.CharField(
        "stare", max_length=12, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    processing_error = models.CharField(max_length=300, blank=True)
    confirmed_at = models.DateTimeField(null=True, blank=True, editable=False)
    match_text = models.TextField(editable=False, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Document scanat"
        verbose_name_plural = "Documente scanate"
        indexes = [
            models.Index(fields=["owner", "-created_at"], name="doc_owner_created_idx"),
        ]

    def __str__(self):
        return self.title or f"Document #{self.pk}"

    def save(self, *args, **kwargs):
        self.match_text = normalize(f"{self.title} {self.extracted_text}")
        if kwargs.get("update_fields") is not None:
            kwargs["update_fields"] = {*kwargs["update_fields"], "match_text"}
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("documents:detail", args=[self.pk])

    @property
    def kind(self) -> str:
        return ItemKind.DOCUMENT

    @property
    def color_token(self) -> str:
        return {
            self.DocumentType.INVOICE: ColorToken.BLUE,
            self.DocumentType.INVITATION: ColorToken.ORANGE,
            self.DocumentType.MEDICAL: ColorToken.MINT,
        }.get(self.document_type, ColorToken.VIOLET)

    @property
    def is_processing(self) -> bool:
        return self.processing_status in {self.Status.PENDING, self.Status.PROCESSING}

    def field(self, name: str):
        """Valoarea unui camp extras, fara scorul de incredere."""
        entry = (self.extracted_data or {}).get(name)
        return entry.get("value") if isinstance(entry, dict) else entry

    def confidence(self, name: str) -> float:
        entry = (self.extracted_data or {}).get(name)
        return float(entry.get("confidence", 0.0)) if isinstance(entry, dict) else 0.0
