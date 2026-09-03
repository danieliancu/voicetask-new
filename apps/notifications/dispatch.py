"""Trimiterea notificarilor, cu deduplicare garantata de baza de date.

Cheia de deduplicare este derivata din evenimentul care a produs notificarea, nu
din momentul rularii. Doua rulari ale aceluiasi task creeaza acelasi `dedup_key`,
iar constrangerea unica opreste a doua notificare.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import UserPreference
from apps.core.providers.base import ProviderError
from apps.core.providers.registry import get_provider
from apps.notifications.models import Notification, NotificationDelivery, PushSubscription

logger = logging.getLogger("voicetask.notifications")


@dataclass(frozen=True)
class DispatchResult:
    notification: Notification | None
    created: bool
    push_sent: int = 0
    push_failed: int = 0
    skipped_reason: str = ""


def reminder_dedup_key(reminder) -> str:
    """Include momentul alarmei: dupa amanare se poate trimite din nou, o singura data."""
    return f"reminder:{reminder.pk}:{reminder.remind_at.isoformat()}"


def dispatch_reminder(reminder) -> DispatchResult:
    prefs = UserPreference.for_user(reminder.owner)
    if not prefs.notifications_enabled:
        return DispatchResult(notification=None, created=False, skipped_reason="dezactivate")

    key = reminder_dedup_key(reminder)
    body_parts = []
    if reminder.appointment_id:
        body_parts.append(reminder.appointment.title)
        if reminder.appointment.location:
            body_parts.append(reminder.appointment.location)
    elif reminder.description:
        body_parts.append(reminder.description)

    try:
        with transaction.atomic():
            notification, created = Notification.objects.get_or_create(
                owner=reminder.owner,
                dedup_key=key,
                defaults={
                    "kind": Notification.Kind.REMINDER,
                    "title": reminder.title,
                    "body": " · ".join(body_parts)[:400],
                    "url": reverse("scheduling:reminder_detail", args=[reminder.pk]),
                    "reminder": reminder,
                },
            )
    except IntegrityError:
        notification = Notification.objects.get(owner=reminder.owner, dedup_key=key)
        created = False

    _record(notification, Notification.Channel.IN_APP, NotificationDelivery.Result.SENT)

    sent, failed = _send_push(notification)

    reminder.notification_sent_at = timezone.now()
    reminder.status = reminder.Status.SENT
    reminder.save(update_fields=["notification_sent_at", "status", "updated_at"])

    return DispatchResult(
        notification=notification, created=created, push_sent=sent, push_failed=failed
    )


def notify(user, *, kind: str, title: str, body: str, url: str, dedup_key: str) -> DispatchResult:
    """Notificare generica, tot cu deduplicare."""
    prefs = UserPreference.for_user(user)
    if not prefs.notifications_enabled:
        return DispatchResult(notification=None, created=False, skipped_reason="dezactivate")

    notification, created = Notification.objects.get_or_create(
        owner=user,
        dedup_key=dedup_key,
        defaults={"kind": kind, "title": title, "body": body[:400], "url": url},
    )
    _record(notification, Notification.Channel.IN_APP, NotificationDelivery.Result.SENT)
    sent, failed = _send_push(notification)
    return DispatchResult(
        notification=notification, created=created, push_sent=sent, push_failed=failed
    )


def _record(notification, channel, result, *, subscription=None, detail: str = "") -> bool:
    """Inregistreaza livrarea. Returneaza False daca exista deja (deci nu retrimitem)."""
    try:
        with transaction.atomic():
            NotificationDelivery.objects.create(
                notification=notification,
                channel=channel,
                subscription=subscription,
                result=result,
                detail=detail[:300],
            )
    except IntegrityError:
        return False
    return True


def _send_push(notification) -> tuple[int, int]:
    provider = get_provider("notification")
    if not provider.supports_push():
        return 0, 0

    sent = failed = 0
    subscriptions = PushSubscription.objects.for_user(notification.owner).filter(is_active=True)
    for subscription in subscriptions:
        # Livrarea se inregistreaza inainte de trimitere: daca randul exista deja,
        # inseamna ca am trimis-o si nu o repetam.
        if not _record(
            notification,
            Notification.Channel.PUSH,
            NotificationDelivery.Result.SENT,
            subscription=subscription,
        ):
            continue
        try:
            result = provider.send(
                subscription,
                title=notification.title,
                body=notification.body,
                url=notification.url,
                dedup_key=notification.dedup_key,
            )
        except ProviderError as exc:
            failed += 1
            NotificationDelivery.objects.filter(
                notification=notification,
                channel=Notification.Channel.PUSH,
                subscription=subscription,
            ).update(result=NotificationDelivery.Result.FAILED, detail=type(exc).__name__)
            continue
        if result.delivered:
            sent += 1
            subscription.last_used_at = timezone.now()
            subscription.failure_count = 0
            subscription.save(update_fields=["last_used_at", "failure_count", "updated_at"])
        else:
            failed += 1
            NotificationDelivery.objects.filter(
                notification=notification,
                channel=Notification.Channel.PUSH,
                subscription=subscription,
            ).update(result=NotificationDelivery.Result.FAILED, detail=result.detail[:300])
    return sent, failed


def push_status(user) -> dict:
    """Starea reala a notificarilor push. Nu pretindem ca sunt active daca nu sunt."""
    provider = get_provider("notification")
    active = PushSubscription.objects.for_user(user).filter(is_active=True).count()
    return {
        "provider_supports_push": provider.supports_push(),
        "subscriptions": active,
        # „Activ" cere si suport pe server, si un abonament inregistrat.
        "is_active": provider.supports_push() and active > 0,
    }
