"""Notite, categorii si elemente de checklist."""

from __future__ import annotations

from django.db import models
from django.db.models.functions import Lower
from django.urls import reverse

from apps.core.enums import ColorToken, ItemKind, Source
from apps.core.models import OwnedSoftDeleteModel, SoftDeleteModel, TimeStampedModel
from apps.search.normalize import normalize


class NoteCategory(OwnedSoftDeleteModel, TimeStampedModel):
    name = models.CharField("nume", max_length=60)
    slug = models.SlugField("identificator", max_length=60)
    color = models.CharField(
        "culoare", max_length=10, choices=ColorToken.choices, default=ColorToken.VIOLET
    )
    icon = models.CharField("icon", max_length=40, default="note")
    position = models.PositiveSmallIntegerField("ordine", default=0)

    class Meta:
        ordering = ["position", "name"]
        verbose_name = "Categorie"
        verbose_name_plural = "Categorii"
        constraints = [
            # Numele se poate refolosi dupa ce categoria a ajuns in cos.
            models.UniqueConstraint(
                Lower("slug"),
                "owner",
                condition=models.Q(deleted_at__isnull=True),
                name="categorie_unica_pe_utilizator",
            )
        ]

    def __str__(self):
        return self.name


class Note(OwnedSoftDeleteModel, TimeStampedModel):
    cascade_relations = ("items",)

    title = models.CharField("titlu", max_length=200)
    content = models.TextField("conținut", blank=True)
    category = models.ForeignKey(
        NoteCategory,
        verbose_name="categorie",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="notes",
    )
    is_pinned = models.BooleanField("fixată", default=False, db_index=True)
    source = models.CharField(
        "sursă", max_length=16, choices=Source.choices, default=Source.MANUAL, db_index=True
    )
    source_document = models.ForeignKey(
        "documents.ScannedDocument",
        verbose_name="document sursă",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="notes",
    )
    #: Copie fara diacritice si cu litere mici, pentru cautarea pe SQLite.
    match_text = models.TextField(editable=False, blank=True, db_index=False)

    class Meta:
        ordering = ["-is_pinned", "-updated_at"]
        verbose_name = "Notiță"
        verbose_name_plural = "Notițe"
        indexes = [
            models.Index(fields=["owner", "-updated_at"], name="note_owner_updated_idx"),
            models.Index(fields=["owner", "is_pinned"], name="note_owner_pinned_idx"),
        ]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        self.match_text = normalize(f"{self.title} {self.content}")
        if kwargs.get("update_fields") is not None:
            kwargs["update_fields"] = {*kwargs["update_fields"], "match_text"}
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("notes:detail", args=[self.pk])

    @property
    def kind(self) -> str:
        return ItemKind.NOTE

    @property
    def color_token(self) -> str:
        return self.category.color if self.category else ColorToken.VIOLET

    @property
    def preview(self) -> str:
        text = " ".join(self.content.split())
        return text[:120] + ("…" if len(text) > 120 else "")


class ChecklistItem(SoftDeleteModel, TimeStampedModel):
    """Un rand bifabil dintr-o notita de tip listă."""

    note = models.ForeignKey(Note, on_delete=models.CASCADE, related_name="items")
    text = models.CharField("text", max_length=200)
    is_done = models.BooleanField("bifat", default=False)
    position = models.PositiveSmallIntegerField("ordine", default=0)

    class Meta:
        ordering = ["position", "pk"]
        verbose_name = "Element de listă"
        verbose_name_plural = "Elemente de listă"

    def __str__(self):
        return self.text
