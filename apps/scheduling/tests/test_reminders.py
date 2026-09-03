"""Programarea alarmelor: calcul, fus orar si tranzitia de ora de vara."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone

from apps.scheduling.models import Reminder
from apps.scheduling.services import due_reminders, sync_appointment_reminder

pytestmark = pytest.mark.django_db

BUCURESTI = ZoneInfo("Europe/Bucharest")


def test_decalajul_se_scade_din_momentul_evenimentului(user, appointment_factory):
    appointment = appointment_factory(user, day_offset=2, hour=14)

    reminder = sync_appointment_reminder(appointment, 1440)

    assert reminder.remind_at == appointment.starts_at - timedelta(days=1)


def test_alarmele_se_stocheaza_in_utc_si_se_afiseaza_local(user, reminder_factory, at):
    reminder = reminder_factory(user, day_offset=1, hour=9)

    assert reminder.remind_at.tzinfo is not None
    assert timezone.localtime(reminder.remind_at).hour == 9


def test_ora_locala_ramane_stabila_peste_trecerea_la_ora_de_vara(user):
    """29 martie 2026 este ziua trecerii la ora de vara in Europa/Bucuresti.

    O alarma la 09:00 in ziua urmatoare trebuie sa ramana la 09:00 local, nu la
    08:00 sau 10:00 — de aceea calculul se face in ora locala, nu prin secunde.
    """
    inainte = timezone.make_aware(datetime(2026, 3, 28, 9, 0), BUCURESTI)
    dupa = timezone.make_aware(datetime(2026, 3, 30, 9, 0), BUCURESTI)

    assert timezone.localtime(inainte, BUCURESTI).hour == 9
    assert timezone.localtime(dupa, BUCURESTI).hour == 9

    # Diferenta reala, masurata in UTC, este de 47 de ore, nu 48: ora de vara a
    # mancat una. Scaderea directa a doua datetime-uri cu acelasi `tzinfo` ar da
    # 48, fiindca Python ignora atunci offsetul — de aceea stocam si comparam in UTC.
    assert (dupa.astimezone(UTC) - inainte.astimezone(UTC)) == timedelta(hours=47)
    assert (dupa - inainte) == timedelta(hours=48)


def test_alarmele_scadente_sunt_selectate(user, reminder_factory):
    scadenta = reminder_factory(user, title="Acum")
    Reminder.objects.filter(pk=scadenta.pk).update(
        remind_at=timezone.now() - timedelta(minutes=1)
    )
    reminder_factory(user, title="Mai târziu", day_offset=2)

    gasite = list(due_reminders())

    assert [r.pk for r in gasite] == [scadenta.pk]


def test_alarmele_foarte_vechi_nu_se_mai_trimit(user, reminder_factory):
    veche = reminder_factory(user)
    Reminder.objects.filter(pk=veche.pk).update(
        remind_at=timezone.now() - timedelta(hours=5)
    )

    assert list(due_reminders()) == []


def test_alarma_deja_trimisa_nu_se_reia(user, reminder_factory):
    reminder = reminder_factory(user)
    Reminder.objects.filter(pk=reminder.pk).update(
        remind_at=timezone.now() - timedelta(minutes=1),
        notification_sent_at=timezone.now(),
    )

    assert list(due_reminders()) == []


def test_amanarea_reactiveaza_alarma(user, reminder_factory):
    reminder = reminder_factory(user)
    Reminder.objects.filter(pk=reminder.pk).update(
        status=Reminder.Status.SENT, notification_sent_at=timezone.now()
    )
    reminder.refresh_from_db()

    reminder.snooze(5)

    assert reminder.status == Reminder.Status.SNOOZED
    assert reminder.notification_sent_at is None


def test_mutarea_programarii_in_viitor_reactiveaza_alarma_trimisa(user, appointment_factory):
    appointment = appointment_factory(user, day_offset=0, hour=8)
    reminder = sync_appointment_reminder(appointment, 30)
    Reminder.objects.filter(pk=reminder.pk).update(
        status=Reminder.Status.SENT, notification_sent_at=timezone.now()
    )

    appointment.starts_at = timezone.now() + timedelta(days=3)
    appointment.ends_at = appointment.starts_at + timedelta(hours=1)
    appointment.save()
    sync_appointment_reminder(appointment, 30)

    reminder.refresh_from_db()
    assert reminder.status == Reminder.Status.SCHEDULED
    assert reminder.notification_sent_at is None


def test_alarma_intarziata_este_marcata_ca_restanta(user, reminder_factory):
    reminder = reminder_factory(user)
    Reminder.objects.filter(pk=reminder.pk).update(
        remind_at=timezone.now() - timedelta(hours=2)
    )
    reminder.refresh_from_db()

    assert reminder.is_overdue
