"""Taskuri pentru programari."""

from __future__ import annotations

from celery import shared_task

from apps.scheduling.models import Appointment
from apps.scheduling.services import sync_appointment_reminder


@shared_task(name="scheduling.resync_reminder", ignore_result=True)
def resync_reminder(appointment_id: int, offset_minutes: int | None) -> None:
    appointment = Appointment.objects.filter(pk=appointment_id).first()
    if appointment is not None:
        sync_appointment_reminder(appointment, offset_minutes)
