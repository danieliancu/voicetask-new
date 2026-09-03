"""Logica de programare a alarmelor.

Alarmele se calculeaza in ora locala a utilizatorului si se stocheaza in UTC.
Reprogramarea unei programari rescrie alarma existenta in loc sa creeze una noua,
ca sa nu se acumuleze duplicate.
"""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from apps.core.enums import Source
from apps.scheduling.models import Appointment, Reminder


def sync_appointment_reminder(
    appointment: Appointment, offset_minutes: int | None, *, source: str = Source.MANUAL
) -> Reminder | None:
    """Creeaza, actualizeaza sau anuleaza alarma atasata unei programari."""
    existing = (
        appointment.reminders.exclude(status=Reminder.Status.DONE).order_by("remind_at").first()
    )

    if offset_minutes is None:
        if existing is not None:
            existing.delete()
        return None

    remind_at = appointment.starts_at - timedelta(minutes=offset_minutes)
    if existing is None:
        return Reminder.objects.create(
            owner=appointment.owner,
            title=appointment.title,
            description=appointment.description,
            remind_at=remind_at,
            offset_minutes=offset_minutes,
            appointment=appointment,
            source=source,
        )

    existing.title = appointment.title
    existing.remind_at = remind_at
    existing.offset_minutes = offset_minutes
    if existing.status == Reminder.Status.SENT and remind_at > timezone.now():
        # Programarea a fost mutata in viitor: alarma redevine activa.
        existing.status = Reminder.Status.SCHEDULED
        existing.notification_sent_at = None
    existing.save(
        update_fields=[
            "title",
            "remind_at",
            "offset_minutes",
            "status",
            "notification_sent_at",
            "updated_at",
        ]
    )
    return existing


def due_reminders(*, now=None, grace_minutes: int = 60):
    """Alarmele scadente care nu au fost inca trimise.

    Fereastra de gratie acopera cazul in care workerul a fost oprit o vreme, dar
    nu retrimite alarme foarte vechi.
    """
    now = now or timezone.now()
    return (
        Reminder.objects.filter(
            status__in=[Reminder.Status.SCHEDULED, Reminder.Status.SNOOZED],
            remind_at__lte=now,
            remind_at__gte=now - timedelta(minutes=grace_minutes),
            notification_sent_at__isnull=True,
        )
        .select_related("owner", "appointment")
        .order_by("remind_at")
    )
