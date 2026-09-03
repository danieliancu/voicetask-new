"""Sincronizarea idempotenta cu Gmail si Google Calendar.

Regula: fiecare obiect extern are un identificator stabil; sincronizarea repetata
face `update_or_create` pe el, deci nu produce duplicate. Scrierile catre
serviciile externe se fac numai dupa confirmarea explicita a utilizatorului.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.core.enums import Source
from apps.core.models import AuditLog
from apps.core.providers.base import ProviderError
from apps.core.providers.registry import get_provider
from apps.integrations.models import ConnectedAccount, EmailReference

logger = logging.getLogger("voicetask.integrations")

FOLLOW_UP_DEFAULT_DELAY_HOURS = 24


@dataclass(frozen=True)
class SyncResult:
    created: int = 0
    updated: int = 0
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error


def sync_emails(user, account: ConnectedAccount | None = None, *, limit: int = 25) -> SyncResult:
    account = account or _account(user, ConnectedAccount.Provider.GMAIL)
    if account is None or not account.is_connected:
        return SyncResult(error="Contul Gmail nu este conectat.")

    provider = get_provider("gmail")
    try:
        page = provider.list_messages(account, limit=limit)
    except ProviderError as exc:
        _mark_error(account, exc.user_message)
        return SyncResult(error=exc.user_message)

    created = updated = 0
    for message in page.items:
        defaults = {
            "account": account,
            "thread_id": message.thread_id,
            "sender": message.sender[:200],
            "subject": message.subject[:300],
            "snippet": message.snippet[:400] if provider.supports_snippets() else "",
            "received_at": message.received_at,
        }
        with transaction.atomic():
            reference, was_created = EmailReference.all_objects.update_or_create(
                owner=user, external_message_id=message.message_id, defaults=defaults
            )
            if was_created:
                created += 1
                if message.needs_follow_up:
                    reference.status = EmailReference.Status.FOLLOW_UP
                    reference.follow_up_at = message.received_at + timedelta(
                        hours=FOLLOW_UP_DEFAULT_DELAY_HOURS
                    )
                    reference.save(update_fields=["status", "follow_up_at", "updated_at"])
            else:
                updated += 1

    account.last_synced_at = timezone.now()
    account.last_error = ""
    account.save(update_fields=["last_synced_at", "last_error", "updated_at"])
    return SyncResult(created=created, updated=updated)


def sync_calendar(user, account: ConnectedAccount | None = None, *, days: int = 30) -> SyncResult:
    from apps.scheduling.models import Appointment

    account = account or _account(user, ConnectedAccount.Provider.CALENDAR)
    if account is None or not account.is_connected:
        return SyncResult(error="Google Calendar nu este conectat.")

    provider = get_provider("calendar")
    start = timezone.now() - timedelta(days=1)
    end = timezone.now() + timedelta(days=days)
    try:
        events = provider.list_events(account, start=start, end=end)
    except ProviderError as exc:
        _mark_error(account, exc.user_message)
        return SyncResult(error=exc.user_message)

    created = updated = 0
    for event in events:
        with transaction.atomic():
            _, was_created = Appointment.all_objects.update_or_create(
                owner=user,
                external_calendar_id=event.external_id,
                defaults={
                    "title": event.title[:200],
                    "description": event.description,
                    "location": event.location[:200],
                    "starts_at": event.starts_at,
                    "ends_at": event.ends_at,
                    "source": Source.CALENDAR,
                    "external_synced_at": timezone.now(),
                },
            )
        created += int(was_created)
        updated += int(not was_created)

    account.last_synced_at = timezone.now()
    account.last_error = ""
    account.save(update_fields=["last_synced_at", "last_error", "updated_at"])
    return SyncResult(created=created, updated=updated)


def push_appointment(user, appointment) -> SyncResult:
    """Scrie programarea in calendarul extern. Apelat doar dupa confirmare."""
    account = _account(user, ConnectedAccount.Provider.CALENDAR)
    if account is None or not account.is_connected:
        return SyncResult(error="Google Calendar nu este conectat.")

    provider = get_provider("calendar")
    try:
        if appointment.external_calendar_id:
            event = provider.update_event(account, appointment=appointment)
            action = "update"
        else:
            event = provider.create_event(account, appointment=appointment)
            action = "create"
    except ProviderError as exc:
        return SyncResult(error=exc.user_message)

    appointment.external_calendar_id = event.external_id
    appointment.external_synced_at = timezone.now()
    appointment.save(
        update_fields=["external_calendar_id", "external_synced_at", "updated_at"]
    )
    AuditLog.objects.create(
        user=user,
        action=AuditLog.Action.EXTERNAL_WRITE,
        object_label=appointment._meta.label,
        object_id=str(appointment.pk),
        detail={"serviciu": "calendar", "actiune": action},
    )
    return SyncResult(created=int(action == "create"), updated=int(action == "update"))


def delete_external_event(user, appointment) -> SyncResult:
    account = _account(user, ConnectedAccount.Provider.CALENDAR)
    if account is None or not account.is_connected or not appointment.external_calendar_id:
        return SyncResult(error="Nu există un eveniment extern de șters.")
    provider = get_provider("calendar")
    try:
        provider.delete_event(account, external_id=appointment.external_calendar_id)
    except ProviderError as exc:
        return SyncResult(error=exc.user_message)
    AuditLog.objects.create(
        user=user,
        action=AuditLog.Action.EXTERNAL_WRITE,
        object_label=appointment._meta.label,
        object_id=str(appointment.pk),
        detail={"serviciu": "calendar", "actiune": "delete"},
    )
    return SyncResult(updated=1)


def _account(user, provider: str) -> ConnectedAccount | None:
    return ConnectedAccount.objects.for_user(user).filter(provider=provider).first()


def _mark_error(account: ConnectedAccount, message: str) -> None:
    account.status = ConnectedAccount.Status.ERROR
    account.last_error = message[:300]
    account.save(update_fields=["status", "last_error", "updated_at"])
