"""Bara de jos, lupa din appbar si drumul catre stergere.

„Modifică" si „Șterge" erau ascunse in meniul lateral, desi sunt exact ce cauta
cineva care vrea sa schimbe ceva. „Caută" ocupa un loc in bara desi are deja un
camp mare pe homepage.
"""

from __future__ import annotations

import re

import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db

ETICHETE = ("Acasă", "Notițe", "Modifică", "Șterge", "Programări")


def bara(client, url: str) -> str:
    raspuns = client.get(url)
    assert raspuns.status_code == 200
    html = raspuns.content.decode()
    inceput = html.index('<nav class="bottom-nav"')
    return html[inceput : html.index("</nav>", inceput)]


def test_bara_are_cele_cinci_destinatii_in_ordine(auth_client):
    html = bara(auth_client, reverse("core:home"))
    pozitii = [html.index(eticheta) for eticheta in ETICHETE]

    assert pozitii == sorted(pozitii), "ordinea din bară nu este cea cerută"


def test_cautarea_nu_mai_este_in_bara(auth_client):
    html = bara(auth_client, reverse("core:home"))

    assert "Caută" not in html
    assert reverse("search:index") not in html


@pytest.mark.parametrize(
    "nume,eticheta",
    [("core:edit_hub", "Modifică"), ("core:delete_hub", "Șterge")],
)
def test_modifica_si_sterge_sunt_accesibile_din_bara(auth_client, nume, eticheta):
    html = bara(auth_client, reverse("core:home"))

    assert reverse(nume) in html
    assert eticheta in html


@pytest.mark.parametrize(
    "url_name,eticheta",
    [
        ("core:home", "Acasă"),
        ("core:edit_hub", "Modifică"),
        ("core:delete_hub", "Șterge"),
        ("notes:list", "Notițe"),
        ("scheduling:calendar", "Programări"),
    ],
)
def test_elementul_curent_este_marcat(auth_client, url_name, eticheta):
    html = bara(auth_client, reverse(url_name))
    curent = re.findall(r'aria-current="page"[^>]*>(?:(?!</a>).)*?<span>([^<]+)</span>', html, re.S)

    assert curent == [eticheta]


def test_lupa_apare_pe_paginile_interne_nu_pe_homepage(auth_client):
    acasa = auth_client.get(reverse("core:home")).content.decode()
    interna = auth_client.get(reverse("notes:list")).content.decode()

    assert 'aria-label="Caută"' not in acasa
    assert 'aria-label="Caută"' in interna
    # Notificarile raman accesibile alaturi de lupa.
    assert reverse("notifications:inbox") in interna


def test_campul_mare_de_cautare_ramane_pe_homepage(auth_client):
    html = auth_client.get(reverse("core:home")).content.decode()

    assert reverse("search:index") in html


def test_stergerea_nu_se_face_dintr_o_apasare(auth_client, note_factory, user):
    """Bara duce la ecranul de alegere, nu la o stergere."""
    from apps.notes.models import Note

    note = note_factory(user, title="Listă cumpărături")
    raspuns = auth_client.get(reverse("core:delete_hub"))

    assert raspuns.status_code == 200
    assert Note.objects.filter(pk=note.pk).exists()


def test_sablonul_nu_scapa_comentarii_in_pagina(auth_client):
    """Un `{# #}` pe doua randuri ar aparea ca text; `{% comment %}` nu apare."""
    html = auth_client.get(reverse("core:home")).content.decode()

    assert "{#" not in html
    assert "Stergerea propriu-zisa cere confirmare" not in html
