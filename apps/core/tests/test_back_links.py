"""Fiecare săgeată de întoarcere urcă la părintele logic al paginii.

Trei locuri depindeau de istoricul browserului sau de antetul `Referer`, deci duceau
unde se nimerea. Hubul „Șterge" mergea chiar mai departe: punea un antet venit din
exterior direct in `href`.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from django.conf import settings
from django.urls import reverse

pytestmark = pytest.mark.django_db

_SAGEATA = re.compile(r'<a[^>]*href="([^"]*)"[^>]*aria-label="Înapoi"')

#: Pagina → părintele ei. Ierarhia din cerință, scrisă o singură dată.
PARINTI = [
    ("core:edit_hub", "core:home"),
    ("core:delete_hub", "core:home"),
    ("core:trash", "core:home"),
    ("notes:list", None),
    ("documents:list", "core:home"),
    ("documents:scan", "core:home"),
    ("integrations:status", "core:home"),
    ("integrations:email_list", "integrations:status"),
    ("notifications:inbox", "core:home"),
    ("accounts:preferences", "core:home"),
    ("accounts:password_change", "accounts:preferences"),
    ("daily_brief:today", "core:home"),
    ("scheduling:reminder_list", "scheduling:calendar"),
]


def sageata(client, url: str) -> str | None:
    raspuns = client.get(url)
    assert raspuns.status_code == 200, url
    gasit = _SAGEATA.search(raspuns.content.decode())
    return gasit.group(1) if gasit else None


@pytest.mark.parametrize("pagina,parinte", [(p, t) for p, t in PARINTI if t])
def test_sageata_duce_la_parintele_paginii(auth_client, pagina, parinte):
    assert sageata(auth_client, reverse(pagina)) == reverse(parinte)


@pytest.mark.parametrize(
    "pagina,parinte",
    [
        ("notes:detail", "notes:list"),
        ("scheduling:detail", "scheduling:calendar"),
        ("scheduling:reminder_detail", "scheduling:reminder_list"),
    ],
)
def test_paginile_de_detaliu_urca_la_lista_lor(
    auth_client, user, note_factory, appointment_factory, reminder_factory, pagina, parinte
):
    obiect = {
        "notes:detail": lambda: note_factory(user),
        "scheduling:detail": lambda: appointment_factory(user),
        "scheduling:reminder_detail": lambda: reminder_factory(user),
    }[pagina]()

    assert sageata(auth_client, reverse(pagina, args=[obiect.pk])) == reverse(parinte)


def test_modificarea_prin_voce_urca_la_obiect(auth_client, user, appointment_factory):
    """Părintele acestui ecran este obiectul editat, nu hubul „Modifică"."""
    appointment = appointment_factory(user)
    url = reverse("assistant:edit", args=["programare", appointment.pk])

    assert sageata(auth_client, url) == reverse("scheduling:detail", args=[appointment.pk])


def test_schita_de_creare_urca_la_ecranul_adauga(auth_client, user):
    from apps.assistant import services

    draft = services.capture_note(user, "Lapte și pâine")

    assert sageata(auth_client, reverse("assistant:draft", args=[draft.uid])) == reverse(
        "assistant:capture"
    )


def test_schita_de_modificare_urca_la_obiectul_vizat(auth_client, user, note_factory):
    """Părintele vine din schița salvată, nu dintr-un parametru din adresă."""
    from apps.assistant.models import IntentDraft
    from apps.assistant.schemas import Intent
    from apps.core.enums import ItemKind

    note = note_factory(user)
    draft = IntentDraft.objects.create(
        owner=user,
        intent=Intent.UPDATE_ITEM,
        payload={"intent": Intent.UPDATE_ITEM},
        target_kind=ItemKind.NOTE,
        target_id=note.pk,
    )

    assert sageata(auth_client, reverse("assistant:draft", args=[draft.uid])) == reverse(
        "notes:detail", args=[note.pk]
    )


def test_hubul_de_stergere_ignora_un_referer_extern(auth_client):
    """Antetul `Referer` ajungea direct in `href`, fara verificare de origine."""
    raspuns = auth_client.get(
        reverse("core:delete_hub"), headers={"Referer": "https://exemplu-rau.test/pagina"}
    )
    html = raspuns.content.decode()

    assert "exemplu-rau.test" not in html
    assert _SAGEATA.search(html).group(1) == reverse("core:home")


# ------------------------------------------- niciun mecanism bazat pe istoric


SURSE = [
    *Path(settings.BASE_DIR, "templates").rglob("*.html"),
    *Path(settings.BASE_DIR, "static", "js").rglob("*.js"),
    *Path(settings.BASE_DIR, "apps").rglob("*.py"),
]

INTERZISE = ("data-history-back", "use_history_back", "HTTP_REFERER", "history.back")


@pytest.mark.parametrize("interzis", INTERZISE)
def test_nicio_intoarcere_prin_istoric_sau_referrer(interzis):
    vinovate = [
        str(cale.relative_to(settings.BASE_DIR))
        for cale in SURSE
        if "tests" not in cale.parts and interzis in cale.read_text(encoding="utf-8")
    ]

    assert not vinovate, f"{interzis} încă apare în: {vinovate}"


def test_fiecare_back_url_este_o_ruta_nu_un_sir_literal():
    """Un literal se rupe tăcut la prima redenumire de rută."""
    vinovate = [
        str(cale.relative_to(settings.BASE_DIR))
        for cale in Path(settings.BASE_DIR, "templates").rglob("*.html")
        if 'back_url="/' in cale.read_text(encoding="utf-8")
    ]

    assert not vinovate, f"cale scrisă literal în: {vinovate}"
