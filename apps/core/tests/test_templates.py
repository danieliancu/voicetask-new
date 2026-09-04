"""Verificari care privesc toate sabloanele deodata."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from django.conf import settings

TEMPLATES = sorted(Path(settings.BASE_DIR).joinpath("templates").rglob("*.html"))

#: `{# ... #}` este recunoscut de Django numai pe o singura linie: expresia lui
#: `Lexer` nu are `DOTALL`. Un comentariu rupt pe doua randuri nu mai este comentariu
#: si ajunge afisat ca text in pagina. Pentru explicatii mai lungi exista
#: `{% comment %}`, folosit deja in `_item_card.html`.
_OPEN = re.compile(r"\{#")


def _comentarii_pe_mai_multe_randuri(text: str) -> list[int]:
    gasite = []
    for match in _OPEN.finditer(text):
        rest = text[match.start() :]
        capat_de_rand = rest.find("\n")
        inchidere = rest.find("#}")
        if inchidere == -1 or (capat_de_rand != -1 and inchidere > capat_de_rand):
            gasite.append(text[: match.start()].count("\n") + 1)
    return gasite


def test_exista_sabloane_de_verificat():
    assert TEMPLATES, "nu s-a găsit niciun șablon"


@pytest.mark.parametrize("template", TEMPLATES, ids=lambda p: p.name)
def test_comentariile_scurte_nu_se_intind_pe_mai_multe_randuri(template):
    randuri = _comentarii_pe_mai_multe_randuri(template.read_text(encoding="utf-8"))

    assert not randuri, (
        f"{template} are un „{{# #}}\" pe mai multe randuri (liniile {randuri}). "
        "Django îl afișează ca text; folosește {% comment %}."
    )
