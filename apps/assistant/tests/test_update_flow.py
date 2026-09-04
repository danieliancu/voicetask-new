"""Modificarea prin comanda vocala nu are voie sa piarda date existente.

O comanda de modificare spune doar ce se schimba („mută la ora 14"). Tot restul
— titlu, descriere, locatie, data — trebuie sa ramana ce era, si in formular, si
dupa salvare.
"""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.assistant import drafts, services
from apps.assistant.forms import get_draft_form_class
from apps.core.enums import ItemKind
from apps.scheduling.models import Appointment

pytestmark = pytest.mark.django_db


def _appointment(user, **kwargs) -> Appointment:
    starts_at = timezone.localtime().replace(
        hour=10, minute=0, second=0, microsecond=0
    ) + timedelta(days=1)
    defaults = {
        "owner": user,
        "title": "Control stomatologic",
        "description": "Aduc radiografia",
        "location": "Clinica Dent",
        "starts_at": starts_at,
        "ends_at": starts_at + timedelta(hours=1),
    }
    return Appointment.objects.create(**{**defaults, **kwargs})


def formular(draft, data=None):
    """Formularul potrivit schitei. La modificare, cel al tipului vizat."""
    return get_draft_form_class(draft)(data, draft=draft) if data else (
        get_draft_form_class(draft)(draft=draft)
    )


def _update_draft(user, appointment, text: str):
    return services.interpret(
        user,
        text,
        mode="edit",
        target_kind=ItemKind.APPOINTMENT,
        target_id=appointment.pk,
    )


def test_formularul_de_modificare_arata_valorile_existente(user):
    appointment = _appointment(user)
    draft = _update_draft(user, appointment, "Schimbă ora la 16")

    form = formular(draft)

    # Fara asta, titlul ar fi fost textul comenzii („Schimbă ora la 16"), iar
    # trimiterea formularului l-ar fi scris peste titlul real.
    assert form.initial["title"] == "Control stomatologic"
    assert form.initial["description"] == "Aduc radiografia"
    assert form.initial["location"] == "Clinica Dent"
    assert form.initial["date"] == timezone.localtime(appointment.starts_at).date()


def test_ora_rostita_are_prioritate_fata_de_valoarea_existenta(user):
    appointment = _appointment(user)
    draft = _update_draft(user, appointment, "Schimbă ora la 16")

    form = formular(draft)

    assert form.initial["start_time"].hour == 16


def test_modificarea_orei_nu_sterge_restul_programarii(user):
    appointment = _appointment(user)
    draft = _update_draft(user, appointment, "Schimbă ora la 16")

    form = formular(draft)
    bound = formular(
        draft,
        data={
            "title": form.initial["title"],
            "description": form.initial["description"],
            "date": form.initial["date"].isoformat(),
            "start_time": form.initial["start_time"].isoformat(),
            "location": form.initial["location"],
        },
    )
    assert bound.is_valid(), bound.errors
    drafts.apply(draft, overrides=bound.to_overrides())

    appointment.refresh_from_db()
    assert appointment.title == "Control stomatologic"
    assert appointment.description == "Aduc radiografia"
    assert appointment.location == "Clinica Dent"
    assert timezone.localtime(appointment.starts_at).hour == 16


def test_mutarea_pastreaza_durata_programarii(user):
    starts_at = timezone.localtime().replace(
        hour=10, minute=0, second=0, microsecond=0
    ) + timedelta(days=1)
    appointment = _appointment(
        user, starts_at=starts_at, ends_at=starts_at + timedelta(minutes=30)
    )
    draft = _update_draft(user, appointment, "Schimbă ora la 16")

    form = formular(draft)
    overrides = {
        "intent": draft.intent,
        "title": form.initial["title"],
        "date": form.initial["date"].isoformat(),
        "start_time": "16:00:00",
        "end_time": None,
    }
    drafts.apply(draft, overrides=overrides)

    appointment.refresh_from_db()
    assert appointment.ends_at - appointment.starts_at == timedelta(minutes=30)


def test_tinta_altui_utilizator_nu_ajunge_in_formular(user, django_user_model):
    strain = django_user_model.objects.create_user(username="strain", password="x" * 12)
    appointment = _appointment(strain)
    draft = _update_draft(user, appointment, "Schimbă ora la 16")

    form = formular(draft)

    assert form.initial.get("title") != "Control stomatologic"
