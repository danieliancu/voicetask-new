"""Autentificare, inregistrare si preferinte."""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.accounts.models import UserPreference

pytestmark = pytest.mark.django_db
User = get_user_model()


def test_autentificare_reusita(client, make_user):
    make_user("ana", password="parola-buna-123")

    response = client.post(
        reverse("accounts:login"), {"username": "ana", "password": "parola-buna-123"}
    )

    assert response.status_code == 302
    assert response.wsgi_request.user.is_authenticated


def test_parola_gresita_da_mesaj_in_romana(client, make_user):
    make_user("ana", password="parola-buna-123")

    response = client.post(
        reverse("accounts:login"), {"username": "ana", "password": "gresita"}
    )

    assert response.status_code == 200
    assert "nu sunt corecte" in response.content.decode()


def test_inregistrarea_creeaza_cont_si_autentifica(client):
    response = client.post(
        reverse("accounts:register"),
        {
            "username": "utilizator-nou",
            "email": "nou@example.com",
            "password1": "parola-lunga-2026",
            "password2": "parola-lunga-2026",
        },
    )

    assert response.status_code == 302
    assert User.objects.filter(username="utilizator-nou").exists()
    assert response.wsgi_request.user.is_authenticated


def test_parolele_care_nu_coincid_sunt_respinse(client):
    response = client.post(
        reverse("accounts:register"),
        {
            "username": "x",
            "password1": "parola-lunga-2026",
            "password2": "alta-parola-2026",
        },
    )

    assert response.status_code == 200
    assert not User.objects.filter(username="x").exists()


def test_preferintele_se_creeaza_automat(make_user):
    user = make_user("ana")
    assert UserPreference.objects.filter(user=user).exists()


def test_preferintele_implicite_sunt_romanesti(user):
    prefs = UserPreference.for_user(user)
    assert prefs.language == "ro"
    assert prefs.timezone == "Europe/Bucharest"
    assert prefs.notifications_enabled is True
    # Reformularea AI este oprita implicit.
    assert prefs.brief_polish_enabled is False


def test_salvarea_preferintelor(auth_client, user):
    response = auth_client.post(
        reverse("accounts:preferences"),
        {
            "display_name": "Daniel",
            "timezone": "Europe/Bucharest",
            "brief_time": "08:00",
            "default_reminder_offset": "60",
        },
    )

    assert response.status_code == 302
    prefs = UserPreference.for_user(user)
    assert prefs.display_name == "Daniel"
    assert prefs.default_reminder_offset == 60
    # Bifele nebifate inseamna dezactivat.
    assert prefs.notifications_enabled is False


def test_delogarea(auth_client):
    response = auth_client.post(reverse("accounts:logout"))
    assert response.status_code == 302
    assert not response.wsgi_request.user.is_authenticated


def test_nu_poti_vedea_preferintele_altcuiva(auth_client, other_user, user):
    """Ecranul de setari lucreaza mereu pe utilizatorul autentificat."""
    response = auth_client.get(reverse("accounts:preferences"))
    assert response.context["object"].user == user


def test_utilizatorul_autentificat_nu_vede_pagina_de_inregistrare(auth_client):
    response = auth_client.get(reverse("accounts:register"))
    assert response.status_code == 302
