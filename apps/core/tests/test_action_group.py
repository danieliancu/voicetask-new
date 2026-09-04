"""Grupul „Modifică / Prin voce / Șterge" rămâne pe un rând.

Markupul era copiat in fiecare pagina de detaliu, cu `.row`, care are `flex-wrap`.
Cele trei butoane cereau ~376 px intr-un spatiu de 288 px la 320 px latime, deci
treceau pe doua randuri.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from django.conf import settings
from django.urls import reverse

pytestmark = pytest.mark.django_db

CSS = Path(settings.BASE_DIR, "static", "css", "components", "controls.css")
_GRUP = re.compile(r'<div class="item-actions">(.*?)</div>', re.S)


def grup(client, url: str) -> str:
    raspuns = client.get(url)
    assert raspuns.status_code == 200, url
    gasit = _GRUP.search(raspuns.content.decode())
    assert gasit, f"pagina {url} nu folosește componenta comună"
    return gasit.group(1)


@pytest.mark.parametrize(
    "pagina,actiuni",
    [
        ("notes:detail", ("Modifică", "Prin voce", "Șterge")),
        ("scheduling:detail", ("Modifică", "Prin voce", "Șterge")),
        ("scheduling:reminder_detail", ("Modifică", "Prin voce")),
    ],
)
def test_actiunile_sunt_toate_in_acelasi_grup(
    auth_client, user, note_factory, appointment_factory, reminder_factory, pagina, actiuni
):
    obiect = {
        "notes:detail": lambda: note_factory(user),
        "scheduling:detail": lambda: appointment_factory(user),
        "scheduling:reminder_detail": lambda: reminder_factory(user),
    }[pagina]()

    html = grup(auth_client, reverse(pagina, args=[obiect.pk]))

    for eticheta in actiuni:
        assert eticheta in html, f"{eticheta} lipsește din grup"


def test_etichetele_raman_vizibile(auth_client, user, note_factory):
    """Nicio actiune nu este ascunsa ca sa incapa: toate trei se citesc."""
    note = note_factory(user)
    html = grup(auth_client, reverse("notes:detail", args=[note.pk]))

    assert "visually-hidden" not in html
    assert html.count("btn") >= 3


def test_paginile_folosesc_aceeasi_componenta():
    """O corectie locala s-ar rupe la urmatoarea pagina; sursa este una singura."""
    sabloane = [
        "notes/note_detail.html",
        "scheduling/appointment_detail.html",
        "scheduling/reminder_detail.html",
    ]
    for nume in sabloane:
        text = Path(settings.BASE_DIR, "templates", nume).read_text(encoding="utf-8")
        assert 'include "core/_item_actions.html"' in text, nume
        assert "Prin voce" not in text, f"{nume} încă are markup propriu"


def test_grupul_nu_se_rupe_pe_doua_randuri():
    stil = CSS.read_text(encoding="utf-8")
    regula = stil[stil.index(".item-actions {") : stil.index(".item-actions .btn")]

    assert "flex-wrap" not in regula
    assert "grid" in regula
    # La latimi extreme, derulare orizontala in loc de al doilea rand.
    assert "overflow-x: auto" in regula


def test_butoanele_din_grup_nu_isi_rup_eticheta():
    stil = CSS.read_text(encoding="utf-8")
    regula = stil[stil.index(".item-actions .btn {") :].split("}")[0]

    assert "white-space: nowrap" in regula
    assert "min-width: 0" in regula


def test_zona_tactila_ramane_de_44px():
    """`.btn` pastreaza `min-height: var(--tap-min)`; grupul nu il suprascrie."""
    stil = CSS.read_text(encoding="utf-8")
    regula = stil[stil.index(".item-actions .btn {") :].split("}")[0]

    assert "min-height" not in regula
    assert "min-height: var(--tap-min);" in stil[stil.index(".btn {") :].split("}")[0]
