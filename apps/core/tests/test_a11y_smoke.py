"""Verificari de accesibilitate si de structura pe toate ecranele principale.

Nu inlocuiesc un audit manual, dar prind regresiile evidente: lipsa unui `lang`,
un buton-icon fara nume, un camp fara eticheta, emoji folosit ca icon.
"""

from html.parser import HTMLParser

import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db

ECRANE = [
    "core:home",
    "core:edit_hub",
    "core:delete_hub",
    "core:trash",
    "notes:list",
    "notes:create",
    "scheduling:calendar",
    "scheduling:reminder_list",
    "documents:list",
    "documents:scan",
    "search:index",
    "assistant:capture",
    "daily_brief:today",
    "notifications:inbox",
    "integrations:status",
    "accounts:preferences",
]


class Analiza(HTMLParser):
    def __init__(self):
        super().__init__()
        self.lang = None
        self.titluri_h1 = 0
        self.imagini_fara_alt = []
        self.butoane_fara_nume = []
        self.campuri = []
        self.etichete = []
        self.ids = []
        self._buton_curent = None
        self._text_buton = ""
        #: Un camp aflat in interiorul unui <label> este etichetat corect,
        #: chiar daca eticheta nu are atributul `for`.
        self._in_label = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "html":
            self.lang = attrs.get("lang")
        elif tag == "h1":
            self.titluri_h1 += 1
        elif tag == "img" and "alt" not in attrs:
            self.imagini_fara_alt.append(attrs.get("src", "?"))
        elif tag == "button":
            self._buton_curent = attrs
            self._text_buton = ""
        elif tag in {"input", "select", "textarea"}:
            tip = attrs.get("type", "text")
            if tip not in {"hidden", "submit", "button"}:
                self.campuri.append({**attrs, "_in_label": self._in_label > 0})
        elif tag == "label":
            self._in_label += 1
            if "for" in attrs:
                self.etichete.append(attrs["for"])
        if "id" in attrs:
            self.ids.append(attrs["id"])

    def handle_endtag(self, tag):
        if tag == "label":
            self._in_label = max(0, self._in_label - 1)
        if tag == "button" and self._buton_curent is not None:
            are_nume = bool(
                self._text_buton.strip()
                or self._buton_curent.get("aria-label")
                or self._buton_curent.get("title")
            )
            if not are_nume:
                self.butoane_fara_nume.append(str(self._buton_curent))
            self._buton_curent = None

    def handle_data(self, data):
        if self._buton_curent is not None:
            self._text_buton += data


def analizeaza(client, route):
    response = client.get(reverse(route))
    assert response.status_code == 200, route
    parser = Analiza()
    parser.feed(response.content.decode())
    return parser


@pytest.mark.parametrize("route", ECRANE)
def test_pagina_declara_limba_romana(auth_client, route):
    assert analizeaza(auth_client, route).lang == "ro"


@pytest.mark.parametrize("route", ECRANE)
def test_toate_imaginile_au_alt(auth_client, route):
    assert analizeaza(auth_client, route).imagini_fara_alt == []


@pytest.mark.parametrize("route", ECRANE)
def test_butoanele_icon_au_nume_accesibil(auth_client, route):
    assert analizeaza(auth_client, route).butoane_fara_nume == []


@pytest.mark.parametrize("route", ECRANE)
def test_campurile_de_formular_au_eticheta(auth_client, route):
    parser = analizeaza(auth_client, route)
    fara_eticheta = [
        camp
        for camp in parser.campuri
        if not camp.get("aria-label")
        and not camp.get("aria-labelledby")
        and not camp.get("_in_label")
        and camp.get("id") not in parser.etichete
    ]
    assert fara_eticheta == [], f"{route}: {fara_eticheta}"


@pytest.mark.parametrize("route", ECRANE)
def test_o_singura_zona_de_continut_principal(auth_client, route):
    response = auth_client.get(reverse(route))
    assert response.content.decode().count("<main") == 1


@pytest.mark.parametrize("route", ECRANE)
def test_exista_link_de_sarire_la_continut(auth_client, route):
    assert 'class="skip-link"' in auth_client.get(reverse(route)).content.decode()


@pytest.mark.parametrize("route", ECRANE)
def test_exista_regiune_aria_live(auth_client, route):
    assert 'aria-live="polite"' in auth_client.get(reverse(route)).content.decode()


NAV_ITEMS = ("Acasă", "Notițe", "Programări", "Caută")


@pytest.mark.parametrize(
    "route",
    ["core:home", "notes:list", "scheduling:calendar", "search:index"],
)
def test_navigatia_inferioara_ramane_stabila(auth_client, route):
    """Cele patru destinatii nu se schimba de la un ecran la altul."""
    content = auth_client.get(reverse(route)).content.decode()
    for item in NAV_ITEMS:
        assert item in content
    assert content.count('class="bottom-nav"') == 1


@pytest.mark.parametrize("route", ["core:edit_hub", "core:delete_hub"])
def test_modifica_si_sterge_nu_inlocuiesc_navigatia(auth_client, route):
    content = auth_client.get(reverse(route)).content.decode()
    for item in NAV_ITEMS:
        assert item in content


def test_ecranul_camerei_ascunde_navigatia(auth_client):
    """Singurul ecran fara navigatie inferioara, ca sa ramana imersiv."""
    content = auth_client.get(reverse("documents:scan")).content.decode()
    assert 'class="bottom-nav"' not in content


@pytest.mark.parametrize("route", ECRANE)
def test_nu_se_folosesc_emoji_in_locul_iconurilor(auth_client, route):
    content = auth_client.get(reverse("core:home")).content.decode()
    emoji = [ch for ch in content if 0x1F300 <= ord(ch) <= 0x1FAFF]
    assert emoji == []


def test_paginile_publice_nu_arata_navigatia(client):
    content = client.get(reverse("accounts:login")).content.decode()
    assert 'class="bottom-nav"' not in content
