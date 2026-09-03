"""Deduplicarea notificarilor si starea reala a push-ului."""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.core.providers.base import NotificationProvider, PushResult
from apps.core.providers.registry import override_provider
from apps.notifications import dispatch
from apps.notifications.models import Notification, PushSubscription
from apps.notifications.tasks import dispatch_due_reminders
from apps.scheduling.models import Reminder

pytestmark = pytest.mark.django_db


class PushDeTest(NotificationProvider):
    name = "push-test"

    def __init__(self):
        self.trimise = []

    def supports_push(self) -> bool:
        return True

    def send(self, subscription, *, title, body, url, dedup_key):
        self.trimise.append(dedup_key)
        return PushResult(delivered=True)


def scadenta(reminder, *, secunde_in_urma: int = 30):
    """Face alarma scadenta la un moment explicit.

    Momentul se da explicit, nu prin `timezone.now()` repetat: pe Windows doua
    apeluri succesive pot returna aceeasi valoare, iar cheia de deduplicare
    include momentul alarmei.
    """
    Reminder.objects.filter(pk=reminder.pk).update(
        remind_at=timezone.now() - timedelta(seconds=secunde_in_urma)
    )
    reminder.refresh_from_db()
    return reminder


def test_o_alarma_produce_o_singura_notificare(user, reminder_factory):
    reminder = scadenta(reminder_factory(user))

    dispatch.dispatch_reminder(reminder)
    dispatch.dispatch_reminder(reminder)

    assert Notification.objects.for_user(user).count() == 1


def test_taskul_rulat_de_doua_ori_nu_dubleaza(user, reminder_factory):
    scadenta(reminder_factory(user))

    primul = dispatch_due_reminders()
    al_doilea = dispatch_due_reminders()

    assert primul == 1
    assert al_doilea == 0
    assert Notification.objects.for_user(user).count() == 1


def test_livrarea_in_aplicatie_se_inregistreaza_o_singura_data(user, reminder_factory):
    reminder = scadenta(reminder_factory(user))

    dispatch.dispatch_reminder(reminder)
    dispatch.dispatch_reminder(reminder)

    notification = Notification.objects.for_user(user).get()
    assert notification.deliveries.filter(channel=Notification.Channel.IN_APP).count() == 1


def test_push_ul_nu_se_retrimite_pentru_acelasi_abonament(user, reminder_factory):
    PushSubscription.objects.create(
        owner=user, endpoint="https://push.example/1", p256dh="k", auth="a"
    )
    reminder = scadenta(reminder_factory(user))
    provider = PushDeTest()

    with override_provider("notification", provider):
        dispatch.dispatch_reminder(reminder)
        dispatch.dispatch_reminder(reminder)

    assert len(provider.trimise) == 1


def test_amanarea_permite_o_notificare_noua(user, reminder_factory):
    reminder = scadenta(reminder_factory(user), secunde_in_urma=600)
    dispatch.dispatch_reminder(reminder)

    reminder.snooze(1)
    scadenta(reminder, secunde_in_urma=30)
    dispatch.dispatch_reminder(reminder)

    # Cheia include momentul alarmei, deci dupa amanare se trimite din nou — o data.
    assert Notification.objects.for_user(user).count() == 2
    dispatch.dispatch_reminder(reminder)
    assert Notification.objects.for_user(user).count() == 2


def test_alarma_marcata_ca_trimisa_dupa_notificare(user, reminder_factory):
    reminder = scadenta(reminder_factory(user))

    dispatch.dispatch_reminder(reminder)

    reminder.refresh_from_db()
    assert reminder.status == Reminder.Status.SENT
    assert reminder.notification_sent_at is not None


def test_notificarile_dezactivate_opresc_trimiterea(user, reminder_factory, prefs):
    prefs.notifications_enabled = False
    prefs.save()
    reminder = scadenta(reminder_factory(user))

    result = dispatch.dispatch_reminder(reminder)

    assert result.notification is None
    assert result.skipped_reason == "dezactivate"
    assert Notification.objects.for_user(user).count() == 0


def test_starea_push_este_falsa_fara_suport_pe_server(user):
    """Fara chei VAPID interfata nu are voie sa spuna ca push-ul e activ."""
    PushSubscription.objects.create(
        owner=user, endpoint="https://push.example/1", p256dh="k", auth="a"
    )

    status = dispatch.push_status(user)

    assert status["provider_supports_push"] is False
    assert status["is_active"] is False


def test_starea_push_cere_si_abonament(user):
    with override_provider("notification", PushDeTest()):
        fara_abonament = dispatch.push_status(user)
        PushSubscription.objects.create(
            owner=user, endpoint="https://push.example/1", p256dh="k", auth="a"
        )
        cu_abonament = dispatch.push_status(user)

    assert fara_abonament["is_active"] is False
    assert cu_abonament["is_active"] is True


def test_abonarea_salveaza_o_singura_inregistrare(auth_client, user):
    payload = {
        "endpoint": "https://push.example/abc",
        "keys": {"p256dh": "cheie", "auth": "auth"},
    }

    for _ in range(2):
        auth_client.post(
            reverse("notifications:subscribe"),
            data=payload,
            content_type="application/json",
        )

    assert PushSubscription.objects.for_user(user).count() == 1


def test_abonarea_incompleta_este_respinsa(auth_client):
    response = auth_client.post(
        reverse("notifications:subscribe"),
        data={"endpoint": "https://push.example/abc"},
        content_type="application/json",
    )
    assert response.status_code == 400


def test_dezabonarea_dezactiveaza_abonamentul(auth_client, user):
    subscription = PushSubscription.objects.create(
        owner=user, endpoint="https://push.example/1", p256dh="k", auth="a"
    )

    auth_client.post(
        reverse("notifications:unsubscribe"),
        data={"endpoint": subscription.endpoint},
        content_type="application/json",
    )

    subscription.refresh_from_db()
    assert subscription.is_active is False


def test_marcarea_ca_citit(auth_client, user, reminder_factory):
    reminder = scadenta(reminder_factory(user))
    dispatch.dispatch_reminder(reminder)
    notification = Notification.objects.for_user(user).get()

    auth_client.post(reverse("notifications:mark_read", args=[notification.pk]))

    notification.refresh_from_db()
    assert notification.is_read


def test_alarma_altui_utilizator_nu_ajunge_la_tine(user, other_user, reminder_factory):
    reminder = scadenta(reminder_factory(other_user))
    dispatch.dispatch_reminder(reminder)

    assert Notification.objects.for_user(user).count() == 0
    assert Notification.objects.for_user(other_user).count() == 1
