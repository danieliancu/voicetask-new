"""CRUD pentru programari si alarme."""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.scheduling.models import Appointment, Reminder

pytestmark = pytest.mark.django_db


def form_data(starts, **extra):
    data = {
        "title": "Întâlnire proiect Alpha",
        "description": "",
        "location": "Google Meet",
        "starts_at": starts.strftime("%Y-%m-%dT%H:%M"),
        "ends_at": (starts + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M"),
        "color": "violet",
        "reminder_offset": "30",
    }
    data.update(extra)
    return data


def test_creare_cu_alarma(auth_client, user, at):
    starts = at(1, 10)

    response = auth_client.post(reverse("scheduling:create"), form_data(starts))

    assert response.status_code == 302
    appointment = Appointment.objects.for_user(user).get()
    reminder = appointment.reminders.get()
    assert reminder.offset_minutes == 30
    assert reminder.remind_at == appointment.starts_at - timedelta(minutes=30)


def test_sfarsit_inaintea_inceputului_este_respins(auth_client, user, at):
    starts = at(1, 10)
    data = form_data(starts, ends_at=(starts - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M"))

    response = auth_client.post(reverse("scheduling:create"), data)

    assert response.status_code == 200
    assert Appointment.objects.for_user(user).count() == 0


def test_editarea_muta_si_alarma(auth_client, user, appointment_factory, at):
    appointment = appointment_factory(user, day_offset=1, hour=10)
    from apps.scheduling.services import sync_appointment_reminder

    sync_appointment_reminder(appointment, 30)
    nou = at(2, 15)

    auth_client.post(reverse("scheduling:update", args=[appointment.pk]), form_data(nou))

    appointment.refresh_from_db()
    reminder = appointment.reminders.get()
    assert reminder.remind_at == appointment.starts_at - timedelta(minutes=30)


def test_alarma_se_actualizeaza_nu_se_dubleaza(user, appointment_factory):
    from apps.scheduling.services import sync_appointment_reminder

    appointment = appointment_factory(user)
    sync_appointment_reminder(appointment, 30)
    sync_appointment_reminder(appointment, 60)

    assert appointment.reminders.count() == 1
    assert appointment.reminders.get().offset_minutes == 60


def test_alarma_se_poate_anula(user, appointment_factory):
    from apps.scheduling.services import sync_appointment_reminder

    appointment = appointment_factory(user)
    sync_appointment_reminder(appointment, 30)
    sync_appointment_reminder(appointment, None)

    assert appointment.reminders.count() == 0


def test_stergerea_programarii_cascadeaza_pe_alarme(user, appointment_factory):
    from apps.scheduling.services import sync_appointment_reminder

    appointment = appointment_factory(user)
    sync_appointment_reminder(appointment, 30)

    appointment.delete()

    assert Reminder.objects.for_user(user).count() == 0
    assert Reminder.all_objects.filter(owner=user, deleted_by_cascade=True).count() == 1


def test_amanarea_alarmei(auth_client, user, reminder_factory):
    reminder = reminder_factory(user, day_offset=0, hour=8)

    auth_client.post(reverse("scheduling:reminder_snooze", args=[reminder.pk]), {"minute": 15})

    reminder.refresh_from_db()
    assert reminder.status == Reminder.Status.SNOOZED
    assert reminder.remind_at > timezone.now()


def test_marcarea_alarmei_ca_rezolvata(auth_client, user, reminder_factory):
    reminder = reminder_factory(user)

    auth_client.post(reverse("scheduling:reminder_complete", args=[reminder.pk]))

    reminder.refresh_from_db()
    assert reminder.status == Reminder.Status.DONE


def test_calendarul_afiseaza_ziua_ceruta(auth_client, user, appointment_factory, at):
    appointment = appointment_factory(user, title="Control medical", day_offset=3, hour=9)
    day = timezone.localtime(appointment.starts_at).date()

    response = auth_client.get(reverse("scheduling:calendar"), {"d": day.isoformat()})

    assert b"Control medical" in response.content


def test_vizualizarea_lunara_returneaza_grila(auth_client, user):
    response = auth_client.get(
        reverse("scheduling:agenda_partial"),
        {"vizualizare": "luna"},
        headers={"HX-Request": "true"},
    )
    assert b"month-grid" in response.content
