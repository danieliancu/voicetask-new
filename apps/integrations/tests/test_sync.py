"""Sincronizarea idempotenta cu providerii Gmail si Calendar demonstrativi."""

import pytest
from django.urls import reverse

from apps.core.crypto import decrypt, encrypt
from apps.integrations import sync
from apps.integrations.models import ConnectedAccount, EmailReference
from apps.integrations.providers.mock_calendar import reset_store
from apps.scheduling.models import Appointment

pytestmark = pytest.mark.django_db


@pytest.fixture
def gmail_account(user):
    return ConnectedAccount.objects.create(
        owner=user,
        provider=ConnectedAccount.Provider.GMAIL,
        status=ConnectedAccount.Status.MOCK,
    )


@pytest.fixture
def calendar_account(user):
    reset_store()
    return ConnectedAccount.objects.create(
        owner=user,
        provider=ConnectedAccount.Provider.CALENDAR,
        status=ConnectedAccount.Status.MOCK,
    )


# --------------------------------------------------------------------- Gmail


def test_sincronizarea_importa_emailuri(user, gmail_account):
    result = sync.sync_emails(user, gmail_account)

    assert result.ok
    assert result.created > 0
    assert EmailReference.objects.for_user(user).count() == result.created


def test_a_doua_sincronizare_nu_creeaza_duplicate(user, gmail_account):
    sync.sync_emails(user, gmail_account)
    numar = EmailReference.objects.for_user(user).count()

    al_doilea = sync.sync_emails(user, gmail_account)

    assert al_doilea.created == 0
    assert EmailReference.objects.for_user(user).count() == numar


def test_emailul_din_cos_nu_se_reimporta(user, gmail_account):
    """Constrangerea de unicitate acopera si randurile din cos."""
    sync.sync_emails(user, gmail_account)
    email = EmailReference.objects.for_user(user).first()
    email.delete()

    sync.sync_emails(user, gmail_account)

    assert EmailReference.all_objects.filter(
        owner=user, external_message_id=email.external_message_id
    ).count() == 1


def test_emailurile_marcate_pentru_urmarire(user, gmail_account):
    sync.sync_emails(user, gmail_account)
    assert EmailReference.objects.for_user(user).filter(
        status=EmailReference.Status.FOLLOW_UP
    ).exists()


def test_contul_neconectat_nu_sincronizeaza(user):
    result = sync.sync_emails(user)
    assert not result.ok
    assert "nu este conectat" in result.error


def test_nu_se_stocheaza_corpul_emailului(user, gmail_account):
    sync.sync_emails(user, gmail_account)
    email = EmailReference.objects.for_user(user).first()
    campuri = {field.name for field in EmailReference._meta.get_fields()}

    assert "body" not in campuri
    assert len(email.snippet) <= 400


# --------------------------------------------------------------------- Calendar


def test_sincronizarea_calendarului_importa_evenimente(user, calendar_account):
    result = sync.sync_calendar(user, calendar_account)

    assert result.ok
    assert Appointment.objects.for_user(user).filter(source="calendar").exists()


def test_a_doua_sincronizare_a_calendarului_nu_dubleaza(user, calendar_account):
    sync.sync_calendar(user, calendar_account)
    numar = Appointment.objects.for_user(user).count()

    sync.sync_calendar(user, calendar_account)

    assert Appointment.objects.for_user(user).count() == numar


def test_trimiterea_in_calendar_este_idempotenta(user, calendar_account, appointment_factory):
    appointment = appointment_factory(user, title="De sincronizat")

    prima = sync.push_appointment(user, appointment)
    appointment.refresh_from_db()
    external_id = appointment.external_calendar_id
    a_doua = sync.push_appointment(user, appointment)
    appointment.refresh_from_db()

    assert prima.created == 1
    assert a_doua.updated == 1
    assert appointment.external_calendar_id == external_id


def test_scrierea_externa_este_auditata(user, calendar_account, appointment_factory):
    from apps.core.models import AuditLog

    sync.push_appointment(user, appointment_factory(user))

    assert AuditLog.objects.filter(
        user=user, action=AuditLog.Action.EXTERNAL_WRITE
    ).exists()


def test_trimiterea_fara_cont_conectat_esueaza(user, appointment_factory):
    result = sync.push_appointment(user, appointment_factory(user))
    assert not result.ok


# --------------------------------------------------------------------- view-uri


def test_ecranul_arata_neconectat_fara_cont(auth_client):
    response = auth_client.get(reverse("integrations:status"))
    assert "Neconectat" in response.content.decode()


def test_modul_demonstrativ_se_activeaza_si_importa(auth_client, user):
    response = auth_client.post(reverse("integrations:enable_demo", args=["gmail"]))

    assert response.status_code == 302
    account = ConnectedAccount.objects.for_user(user).get(provider="gmail")
    assert account.status == ConnectedAccount.Status.MOCK
    assert EmailReference.objects.for_user(user).exists()


def test_modul_demonstrativ_cere_post(auth_client):
    response = auth_client.get(reverse("integrations:enable_demo", args=["gmail"]))
    assert response.status_code == 405


def test_deconectarea_sterge_tokenurile(auth_client, user, gmail_account):
    gmail_account.access_token = "token-secret"
    gmail_account.status = ConnectedAccount.Status.CONNECTED
    gmail_account.save()

    auth_client.post(reverse("integrations:disconnect", args=[gmail_account.pk]))

    gmail_account.refresh_from_db()
    assert gmail_account.access_token == ""
    assert gmail_account.status == ConnectedAccount.Status.DISCONNECTED


def test_marcarea_unui_email_pentru_urmarire(auth_client, user, email_factory):
    email = email_factory(user)

    auth_client.post(reverse("integrations:toggle_follow_up", args=[email.pk]))

    email.refresh_from_db()
    assert email.status == EmailReference.Status.FOLLOW_UP
    assert email.follow_up_at is not None


# --------------------------------------------------------------------- tokenuri


def test_tokenurile_sunt_criptate_in_baza_de_date(user, gmail_account):
    gmail_account.access_token = "token-foarte-secret"
    gmail_account.save()

    brut = ConnectedAccount.objects.filter(pk=gmail_account.pk).values_list(
        "_access_token", flat=True
    )[0]

    assert "token-foarte-secret" not in brut
    assert gmail_account.access_token == "token-foarte-secret"


def test_criptarea_este_reversibila():
    assert decrypt(encrypt("valoare")) == "valoare"
    assert encrypt("") == ""
    assert decrypt("") == ""


def test_adminul_nu_expune_tokenurile():
    from apps.integrations.admin import ConnectedAccountAdmin

    assert "_access_token" in ConnectedAccountAdmin.exclude
    assert "_refresh_token" in ConnectedAccountAdmin.exclude


def test_starea_scope_ului_gmail_este_afisata_onest(auth_client, user, settings):
    """Scope-ul `metadata` nu returneaza snippet-uri; interfata o spune."""
    settings.GMAIL_SCOPE_LEVEL = "metadata"
    from apps.integrations.oauth import scopes_for

    assert scopes_for(ConnectedAccount.Provider.GMAIL) == [
        "https://www.googleapis.com/auth/gmail.metadata"
    ]
