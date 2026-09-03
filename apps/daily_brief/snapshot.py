"""Construirea instantaneului din care se genereaza rezumatul zilei.

Rezumatul se construieste exclusiv din aceste date. Amprenta (`source_hash`)
acopera fiecare valoare afisata: daca se schimba o ora, o suma sau un titlu,
amprenta se schimba si rezumatul se regenereaza. Daca nu se schimba nimic,
textul si fisierul audio se refolosesc din cache.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, time, timedelta

from django.utils import timezone

from apps.core import dates_ro


def _day_bounds(day: date) -> tuple[datetime, datetime]:
    tz = timezone.get_current_timezone()
    start = timezone.make_aware(datetime.combine(day, time.min), tz)
    return start, start + timedelta(days=1)


def build_snapshot(user, day: date) -> dict:
    """Toate datele relevante pentru o zi, intr-o structura serializabila si stabila."""
    from apps.documents.models import ScannedDocument
    from apps.integrations.models import ConnectedAccount, EmailReference
    from apps.scheduling.models import Appointment, Reminder

    start, end = _day_bounds(day)
    horizon = start + timedelta(days=7)

    appointments = [
        {
            "id": item.pk,
            "title": item.title,
            "starts_at": item.starts_at.isoformat(),
            "ends_at": item.ends_at.isoformat() if item.ends_at else None,
            "location": item.location,
            "source": item.source,
            "time": dates_ro.format_time(item.starts_at),
        }
        for item in Appointment.objects.for_user(user)
        .filter(starts_at__gte=start, starts_at__lt=end)
        .order_by("starts_at")
    ]

    reminders = [
        {
            "id": item.pk,
            "title": item.title,
            "remind_at": item.remind_at.isoformat(),
            "time": dates_ro.format_time(item.remind_at),
            "status": item.status,
        }
        for item in Reminder.objects.for_user(user)
        .filter(remind_at__gte=start, remind_at__lt=end)
        .exclude(status=Reminder.Status.DONE)
        .order_by("remind_at")
    ]

    emails = [
        {
            "id": item.pk,
            "sender": item.sender_name,
            "subject": item.subject,
            "follow_up_at": item.follow_up_at.isoformat() if item.follow_up_at else None,
        }
        for item in EmailReference.objects.for_user(user)
        .filter(status=EmailReference.Status.FOLLOW_UP)
        .order_by("follow_up_at", "-received_at")[:5]
    ]

    documents = []
    for item in (
        ScannedDocument.objects.for_user(user)
        .filter(
            processing_status__in=[
                ScannedDocument.Status.READY,
                ScannedDocument.Status.CONFIRMED,
            ]
        )
        .order_by("-created_at")[:20]
    ):
        due = item.field("due_date")
        if not due:
            continue
        try:
            due_date = date.fromisoformat(str(due))
        except (TypeError, ValueError):
            continue
        if start.date() <= due_date <= horizon.date():
            documents.append(
                {
                    "id": item.pk,
                    "title": str(item),
                    "due_date": due_date.isoformat(),
                    "amount": item.field("amount"),
                    "currency": item.field("currency") or "",
                }
            )

    accounts = {
        account.provider: account.status
        for account in ConnectedAccount.objects.for_user(user)
    }

    snapshot = {
        "date": day.isoformat(),
        "name": _greeting_name(user),
        "appointments": appointments,
        "reminders": reminders,
        "emails": emails,
        "documents": documents,
        "accounts": accounts,
        "counts": {
            "appointments": len(appointments),
            "todo": len(reminders) + len(documents),
            "emails": len(emails),
        },
    }
    return snapshot


def _greeting_name(user) -> str:
    from apps.accounts.models import UserPreference

    return UserPreference.for_user(user).greeting_name


def source_hash(snapshot: dict) -> str:
    """Amprenta stabila: sortam cheile ca ordinea sa nu produca falsi pozitivi."""
    payload = json.dumps(snapshot, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
