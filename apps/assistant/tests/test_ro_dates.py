"""Interpretarea expresiilor temporale in limba romana."""

from datetime import date, datetime, time

import pytest
from django.utils import timezone

from apps.assistant import ro_time

# Marți, 1 septembrie 2026, ora 08:00 — referinta fixa pentru toate testele.
NOW = datetime(2026, 9, 1, 8, 0)


def extract(text: str):
    return ro_time.extract(text, now=NOW)


@pytest.mark.parametrize(
    "text,asteptat",
    [
        ("mâine la 10", date(2026, 9, 2)),
        ("poimâine", date(2026, 9, 3)),
        ("astăzi", date(2026, 9, 1)),
        ("azi la 15", date(2026, 9, 1)),
        ("pe 6 septembrie", date(2026, 9, 6)),
        ("6 septembrie 2026", date(2026, 9, 6)),
        ("06.09.2026", date(2026, 9, 6)),
        ("6/9/2026", date(2026, 9, 6)),
        ("peste două săptămâni", date(2026, 9, 15)),
        ("peste 3 zile", date(2026, 9, 4)),
        ("vineri", date(2026, 9, 4)),
        ("marți viitoare", date(2026, 9, 15)),
        ("luni", date(2026, 9, 7)),
    ],
)
def test_data_este_recunoscuta(text, asteptat):
    assert extract(text).day == asteptat


@pytest.mark.parametrize(
    "text,asteptat",
    [
        ("mâine la 10", time(10, 0)),
        ("la 14:30", time(14, 30)),
        ("ora 9", time(9, 0)),
        ("la 17.30", time(17, 30)),
        ("mâine dimineața", time(9, 0)),
        ("mâine seara", time(19, 0)),
        ("la zece și jumătate", time(10, 30)),
        ("la 9 și un sfert", time(9, 15)),
    ],
)
def test_ora_este_recunoscuta(text, asteptat):
    assert extract(text).at_time == asteptat


def test_data_fara_an_care_a_trecut_trece_in_anul_urmator():
    match = ro_time.extract("pe 1 martie", now=NOW)
    assert match.day == date(2027, 3, 1)


def test_ora_mica_fara_indiciu_este_marcata_ambigua():
    match = extract("la 3")
    assert match.ambiguous
    assert match.reason == "ora_ambigua"


def test_partea_de_zi_dezambiguizeaza_ora():
    assert extract("la 3 după-amiaza").at_time == time(15, 0)


def test_data_invalida_este_semnalata():
    match = extract("pe 31.02.2026")
    assert match.ambiguous
    assert match.reason == "data_invalida"


def test_textul_fara_indicii_temporale_nu_inventeaza_o_data():
    match = ro_time.extract("cumpăr lapte și pâine", now=NOW)
    assert match.day is None
    assert match.at_time is None


def test_fragmentele_temporale_sunt_scoase_din_text():
    text = "Întâlnire mâine la 10 cu echipa"
    match = extract(text)
    assert ro_time.strip_temporal(text, match) == "Întâlnire cu echipa"


def test_diacriticele_raman_intacte_dupa_taiere():
    text = "Ședință marți la 17:30 cu părinții"
    match = extract(text)
    assert ro_time.strip_temporal(text, match) == "Ședință cu părinții"


def test_peste_n_ore_calculeaza_de_la_momentul_curent():
    match = ro_time.extract("peste 2 ore", now=NOW)
    assert match.day == date(2026, 9, 1)
    assert match.at_time == time(10, 0)


def test_ora_locala_reala_nu_arunca():
    """Rulare cu momentul curent, ca sa prindem regresii dependente de fus."""
    assert ro_time.extract("mâine la 9", now=timezone.localtime()).at_time == time(9, 0)
