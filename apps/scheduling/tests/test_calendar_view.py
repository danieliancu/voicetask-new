"""Selectorul „Zi / Săptămână / Lună" arata mereu ce vizualizare este activa.

Cat timp selectorul statea in afara tintei HTMX, `aria-pressed` nu se mai rerandà
dupa un swap: continutul devenea lunar, dar butonul selectat ramanea „Zi".
"""

from __future__ import annotations

import re

import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db

MODURI = ["zi", "saptamana", "luna"]
MOD_SI_ETICHETA = list(zip(MODURI, ["Zi", "Săptămână", "Lună"], strict=True))


def optiunea_activa(html: str) -> list[str]:
    """Etichetele optiunilor marcate ca active."""
    return [
        eticheta.strip()
        for eticheta in re.findall(
            r'<a[^>]*aria-pressed="true"[^>]*>(?:[^<]*<svg.*?</svg>)?([^<]*)</a>', html, re.S
        )
    ]


@pytest.mark.parametrize("mod,eticheta", MOD_SI_ETICHETA)
def test_pagina_completa_marcheaza_modul_cerut(auth_client, mod, eticheta):
    html = auth_client.get(reverse("scheduling:calendar"), {"vizualizare": mod}).content.decode()

    assert optiunea_activa(html) == [eticheta]


@pytest.mark.parametrize("mod,eticheta", MOD_SI_ETICHETA)
def test_fragmentul_htmx_marcheaza_modul_cerut(auth_client, mod, eticheta):
    """Fragmentul contine si selectorul, nu doar agenda."""
    response = auth_client.get(
        reverse("scheduling:agenda_partial"),
        {"vizualizare": mod},
        headers={"HX-Request": "true"},
    )
    html = response.content.decode()

    assert 'class="segmented"' in html
    assert optiunea_activa(html) == [eticheta]


@pytest.mark.parametrize("mod", MODURI)
def test_o_singura_optiune_este_activa(auth_client, mod):
    html = auth_client.get(reverse("scheduling:calendar"), {"vizualizare": mod}).content.decode()

    assert html.count('aria-pressed="true"') == 1


def test_fragmentul_si_pagina_au_acelasi_bloc(auth_client):
    """Ambele cai randeaza acelasi partial, deci nu pot ajunge in stari diferite."""
    pagina = auth_client.get(reverse("scheduling:calendar"), {"vizualizare": "luna"})
    fragment = auth_client.get(
        reverse("scheduling:agenda_partial"),
        {"vizualizare": "luna"},
        headers={"HX-Request": "true"},
    )

    assert 'id="calendar"' in pagina.content.decode()
    assert 'id="calendar"' in fragment.content.decode()
    assert b"month-grid" in fragment.content


def test_adresa_impinsa_este_a_paginii_nu_a_fragmentului(auth_client):
    """`hx-push-url=\"true\"` punea in bara adresa fragmentului, fara layout."""
    html = auth_client.get(reverse("scheduling:calendar")).content.decode()

    assert f'hx-push-url="{reverse("scheduling:calendar")}?vizualizare=luna' in html
    assert 'hx-push-url="true"' not in html


def test_o_vizualizare_necunoscuta_cade_pe_zi(auth_client):
    html = auth_client.get(
        reverse("scheduling:calendar"), {"vizualizare": "trimestru"}
    ).content.decode()

    assert optiunea_activa(html) == ["Zi"]


def test_ziua_aleasa_ramane_in_linkurile_selectorului(auth_client):
    """Dupa un swap, linkurile poarta ziua curenta, nu pe cea de la incarcare."""
    html = auth_client.get(
        reverse("scheduling:agenda_partial"),
        {"vizualizare": "saptamana", "d": "2026-09-15"},
        headers={"HX-Request": "true"},
    ).content.decode()

    assert "d=2026-09-15" in html
