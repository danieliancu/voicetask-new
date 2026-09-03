"""Cautari recente."""

from __future__ import annotations

from django.db import models
from django.utils import timezone

from apps.core.models import OwnedModel, TimeStampedModel
from apps.search.normalize import normalize


class RecentSearch(OwnedModel, TimeStampedModel):
    query = models.CharField("căutare", max_length=200)
    normalized = models.CharField(max_length=200, editable=False, db_index=True)
    hit_count = models.PositiveIntegerField(default=1)
    last_used_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-last_used_at"]
        verbose_name = "Căutare recentă"
        verbose_name_plural = "Căutări recente"
        constraints = [
            models.UniqueConstraint("owner", "normalized", name="cautare_recenta_unica")
        ]

    def __str__(self):
        return self.query

    @classmethod
    def record(cls, user, query: str) -> None:
        """Aceeasi cautare nu creeaza randuri noi, doar isi actualizeaza contorul."""
        text = (query or "").strip()
        if len(text) < 2:
            return
        key = normalize(text)
        obj, created = cls.objects.get_or_create(
            owner=user, normalized=key, defaults={"query": text}
        )
        if not created:
            cls.objects.filter(pk=obj.pk).update(
                query=text, hit_count=models.F("hit_count") + 1, last_used_at=timezone.now()
            )
