"""Notificari in aplicatie, livrari si abonamente push."""

from __future__ import annotations

from django.db import models

from apps.core.enums import ColorToken
from apps.core.models import OwnedModel, TimeStampedModel


class Notification(OwnedModel, TimeStampedModel):
    class Channel(models.TextChoices):
        IN_APP = "in_app", "În aplicație"
        PUSH = "push", "Notificare în browser"

    class Kind(models.TextChoices):
        REMINDER = "reminder", "Alarmă"
        FOLLOW_UP = "follow_up", "Urmărire email"
        DOCUMENT = "document", "Document"
        BRIEF = "brief", "Rezumat zilnic"
        SYSTEM = "system", "Sistem"

    kind = models.CharField(max_length=16, choices=Kind.choices, default=Kind.SYSTEM)
    title = models.CharField(max_length=200)
    body = models.CharField(max_length=400, blank=True)
    url = models.CharField(max_length=300, blank=True)
    #: Cheia de deduplicare: acelasi eveniment nu produce niciodata doua notificari.
    dedup_key = models.CharField(max_length=120, db_index=True)
    reminder = models.ForeignKey(
        "scheduling.Reminder",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="notifications",
    )
    read_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Notificare"
        verbose_name_plural = "Notificări"
        constraints = [
            models.UniqueConstraint("owner", "dedup_key", name="notificare_unica")
        ]

    def __str__(self):
        return self.title

    @property
    def is_read(self) -> bool:
        return self.read_at is not None

    @property
    def color_token(self) -> str:
        return {
            self.Kind.REMINDER: ColorToken.VIOLET,
            self.Kind.FOLLOW_UP: ColorToken.BLUE,
            self.Kind.DOCUMENT: ColorToken.ORANGE,
            self.Kind.BRIEF: ColorToken.MINT,
        }.get(self.kind, ColorToken.VIOLET)


class PushSubscription(OwnedModel, TimeStampedModel):
    """Un abonament Web Push activ. Existenta lui este conditia pentru a spune „push activ"."""

    endpoint = models.URLField(max_length=500)
    p256dh = models.CharField(max_length=200)
    auth = models.CharField(max_length=100)
    user_agent = models.CharField(max_length=200, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    failure_count = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = "Abonament push"
        verbose_name_plural = "Abonamente push"
        constraints = [
            models.UniqueConstraint("owner", "endpoint", name="abonament_push_unic")
        ]

    def __str__(self):
        return f"{self.owner} · {self.endpoint[:40]}…"

    def as_subscription_info(self) -> dict:
        return {"endpoint": self.endpoint, "keys": {"p256dh": self.p256dh, "auth": self.auth}}


class NotificationDelivery(TimeStampedModel):
    """O incercare de livrare. Constrangerea impiedica trimiterea de doua ori."""

    class Result(models.TextChoices):
        SENT = "sent", "Trimisă"
        SKIPPED = "skipped", "Ignorată"
        FAILED = "failed", "Eșuată"

    notification = models.ForeignKey(
        Notification, on_delete=models.CASCADE, related_name="deliveries"
    )
    channel = models.CharField(max_length=10, choices=Notification.Channel.choices)
    subscription = models.ForeignKey(
        PushSubscription,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="deliveries",
    )
    result = models.CharField(max_length=10, choices=Result.choices)
    detail = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Livrare notificare"
        verbose_name_plural = "Livrări notificări"
        constraints = [
            # NULL-urile sunt distincte in SQL, deci canalul fara abonament are
            # nevoie de propria constrangere partiala.
            models.UniqueConstraint(
                "notification",
                "channel",
                "subscription",
                condition=models.Q(subscription__isnull=False),
                name="o_livrare_per_canal_si_abonament",
            ),
            models.UniqueConstraint(
                "notification",
                "channel",
                condition=models.Q(subscription__isnull=True),
                name="o_livrare_per_canal_fara_abonament",
            ),
        ]

    def __str__(self):
        return f"{self.notification_id} · {self.channel} · {self.result}"
