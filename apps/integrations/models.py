"""Conturi externe conectate si referinte de email.

Din emailuri se stocheaza doar metadatele necesare pentru urmarire: expeditor,
subiect, un fragment scurt si data. Corpul mesajului nu ajunge in baza de date.
"""

from __future__ import annotations

from django.db import models
from django.utils import timezone

from apps.core import crypto
from apps.core.enums import ColorToken, ItemKind
from apps.core.models import OwnedModel, OwnedSoftDeleteModel, TimeStampedModel
from apps.search.normalize import normalize


class ConnectedAccount(OwnedModel, TimeStampedModel):
    class Provider(models.TextChoices):
        GMAIL = "gmail", "Gmail"
        CALENDAR = "calendar", "Google Calendar"

    class Status(models.TextChoices):
        DISCONNECTED = "disconnected", "Neconectat"
        CONNECTED = "connected", "Conectat"
        EXPIRED = "expired", "Autorizare expirată"
        ERROR = "error", "Eroare"
        MOCK = "mock", "Demonstrativ"

    provider = models.CharField("serviciu", max_length=16, choices=Provider.choices)
    external_account_id = models.CharField("cont extern", max_length=200, blank=True)
    email = models.EmailField("adresă", blank=True)
    scopes = models.JSONField("permisiuni", default=list, blank=True)
    status = models.CharField(
        "stare", max_length=16, choices=Status.choices, default=Status.DISCONNECTED
    )
    token_expires_at = models.DateTimeField("expiră la", null=True, blank=True)
    last_synced_at = models.DateTimeField("ultima sincronizare", null=True, blank=True)
    last_error = models.CharField(max_length=300, blank=True)

    # Tokenurile sunt criptate cu Fernet inainte de scriere; nu se logheaza niciodata.
    _access_token = models.TextField("token acces", blank=True, db_column="access_token")
    _refresh_token = models.TextField("token reîmprospătare", blank=True, db_column="refresh_token")

    class Meta:
        verbose_name = "Cont conectat"
        verbose_name_plural = "Conturi conectate"
        constraints = [
            models.UniqueConstraint("owner", "provider", name="un_cont_per_serviciu")
        ]

    def __str__(self):
        return f"{self.get_provider_display()} · {self.get_status_display()}"

    @property
    def access_token(self) -> str:
        return crypto.decrypt(self._access_token)

    @access_token.setter
    def access_token(self, value: str) -> None:
        self._access_token = crypto.encrypt(value or "")

    @property
    def refresh_token(self) -> str:
        return crypto.decrypt(self._refresh_token)

    @refresh_token.setter
    def refresh_token(self, value: str) -> None:
        self._refresh_token = crypto.encrypt(value or "")

    @property
    def is_connected(self) -> bool:
        return self.status in {self.Status.CONNECTED, self.Status.MOCK}

    @property
    def is_expired(self) -> bool:
        return bool(self.token_expires_at and self.token_expires_at <= timezone.now())


class EmailReference(OwnedSoftDeleteModel, TimeStampedModel):
    class Status(models.TextChoices):
        NEW = "new", "Nou"
        FOLLOW_UP = "follow_up", "De urmărit"
        DONE = "done", "Rezolvat"
        IGNORED = "ignored", "Ignorat"

    account = models.ForeignKey(
        ConnectedAccount, on_delete=models.CASCADE, related_name="emails", null=True, blank=True
    )
    external_message_id = models.CharField("id mesaj", max_length=200, db_index=True)
    thread_id = models.CharField(max_length=200, blank=True)
    sender = models.CharField("expeditor", max_length=200)
    subject = models.CharField("subiect", max_length=300, blank=True)
    snippet = models.CharField("fragment", max_length=400, blank=True)
    received_at = models.DateTimeField("primit la", db_index=True)
    follow_up_at = models.DateTimeField("de urmărit la", null=True, blank=True, db_index=True)
    #: Nota scrisa de utilizator la marcarea pentru urmarire. `snippet` nu poate tine
    #: locul ei: acela vine de la Gmail si se rescrie la fiecare sincronizare.
    follow_up_note = models.TextField("notă", blank=True)
    status = models.CharField(
        "stare", max_length=12, choices=Status.choices, default=Status.NEW, db_index=True
    )
    match_text = models.TextField(editable=False, blank=True)

    class Meta:
        ordering = ["-received_at"]
        verbose_name = "Referință email"
        verbose_name_plural = "Referințe email"
        constraints = [
            # Sincronizarea repetata nu trebuie sa creeze duplicate, nici dupa stergere.
            models.UniqueConstraint(
                "owner", "external_message_id", name="email_unic_pe_utilizator"
            )
        ]

    def __str__(self):
        return self.subject or self.sender

    def save(self, *args, **kwargs):
        self.match_text = normalize(f"{self.subject} {self.sender} {self.snippet}")
        if kwargs.get("update_fields") is not None:
            kwargs["update_fields"] = {*kwargs["update_fields"], "match_text"}
        super().save(*args, **kwargs)

    @property
    def kind(self) -> str:
        return ItemKind.EMAIL

    @property
    def color_token(self) -> str:
        return ColorToken.BLUE

    @property
    def sender_name(self) -> str:
        return self.sender.split("<")[0].strip().strip('"') or self.sender
