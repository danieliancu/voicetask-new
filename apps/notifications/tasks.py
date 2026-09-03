"""Taskuri de notificare. Sunt idempotente: pot rula de mai multe ori fara efect dublu."""

from __future__ import annotations

import logging

from celery import shared_task

from apps.notifications import dispatch
from apps.scheduling.services import due_reminders

logger = logging.getLogger("voicetask.notifications")


@shared_task(name="notifications.dispatch_due_reminders", ignore_result=True)
def dispatch_due_reminders() -> int:
    sent = 0
    for reminder in due_reminders():
        result = dispatch.dispatch_reminder(reminder)
        if result.created:
            sent += 1
    if sent:
        logger.info("alarme notificate: %d", sent)
    return sent


@shared_task(name="notifications.dispatch_reminder", ignore_result=True)
def dispatch_reminder_task(reminder_id: int) -> bool:
    from apps.scheduling.models import Reminder

    reminder = Reminder.objects.filter(pk=reminder_id).first()
    if reminder is None:
        return False
    return dispatch.dispatch_reminder(reminder).created
