"""Titlul este o eticheta scurta, nu propozitia rostita.

Data, ora si locatia au campurile lor in formular; repetate in titlu, ar aparea
de doua ori pe ecran.
"""

import pytest
from django.utils import timezone

from apps.assistant.providers.rule_based import RuleBasedIntentParser
from apps.core.providers.context import IntentContext


def parse(text: str, **kwargs) -> dict:
    context = IntentContext(now=timezone.localtime(), **kwargs)
    return RuleBasedIntentParser().parse(text, context=context)


@pytest.mark.parametrize(
    "text, expected",
    [
        (
            "Programare mâine la dentist, la ora 12, pe strada Covaci, numărul 4.",
            "Programare la dentist",
        ),
        ("Notează să cumpăr lapte și pâine", "Cumpăr lapte și pâine"),
        ("Întâlnire joi la sediul central cu Andrei", "Întâlnire cu Andrei"),
    ],
)
def test_titlul_nu_repeta_detaliile_extrase(text, expected):
    assert parse(text)["title"] == expected


def test_adresa_cu_numar_intra_in_locatie_nu_in_titlu():
    payload = parse("Programare mâine la dentist, la ora 12, pe strada Covaci, numărul 4.")

    assert payload["location"] == "strada Covaci, numărul 4"
    assert "numărul" not in payload["title"]


def test_numele_locului_se_opreste_inainte_de_ora():
    # Fara oprire pe cuvintele functionale, locatia ar fi „clinica Regina Maria la ora".
    payload = parse("Programare marți la clinica Regina Maria la ora 9 dimineața")

    assert payload["location"] == "clinica Regina Maria"
    assert payload["start_time"].hour == 9
