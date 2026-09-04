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


def test_partea_de_zi_cea_mai_lunga_castiga():
    """„amiaza" este continut in „dupa-amiaza"; ordinea de cautare conteaza."""
    assert extract("la 3 după-amiaza").at_time == time(15, 0)
    assert "ora_lipseste_dupa_amiaza" in extract("mâine după-amiaza").reasons


@pytest.mark.parametrize(
    "text,cod",
    [
        ("mâine dimineața", "ora_lipseste_dimineata"),
        ("mâine după-amiaza", "ora_lipseste_dupa_amiaza"),
        ("mâine seara", "ora_lipseste_seara"),
        ("mâine noaptea", "ora_lipseste_noaptea"),
    ],
)
def test_o_perioada_vaga_nu_devine_ora_exacta(text, cod):
    """„Seara" acopera cinci ore. 19:00 ar fi o ora pe care nu a rostit-o nimeni."""
    match = extract(text)

    assert match.at_time is None
    assert cod in match.reasons
    assert match.day is not None


@pytest.mark.parametrize("text", ["mâine la amiază", "mâine la prânz"])
def test_partile_care_numesc_un_moment_raman_exacte(text):
    """„La prânz" nu este o perioada vaga: numeste ora 12."""
    assert extract(text).at_time == time(12, 0)
    assert extract(text).reasons == ()


@pytest.mark.parametrize(
    "text,asteptat",
    [
        ("la trei după-amiaza", time(15, 0)),
        ("la două dimineața", time(2, 0)),
        ("la zece noaptea", time(22, 0)),
        ("la două noaptea", time(2, 0)),
        ("la opt seara", time(20, 0)),
        ("la nouă dimineața", time(9, 0)),
    ],
)
def test_partea_de_zi_aseaza_ora_rostita(text, asteptat):
    match = extract(text)

    assert match.at_time == asteptat
    # Partea de zi a rezolvat ambiguitatea; nu mai are rost nicio intrebare.
    assert "ora_ambigua" not in match.reasons


# ----------------------------------------------------------------- AM si PM


@pytest.mark.parametrize(
    "text,asteptat",
    [
        ("3 PM", time(15, 0)),
        ("la 3 PM", time(15, 0)),
        ("3 p.m.", time(15, 0)),
        ("10 AM", time(10, 0)),
        ("12 AM", time(0, 0)),
        ("12 PM", time(12, 0)),
        ("la 7:30 PM", time(19, 30)),
        ("ora 11 am", time(11, 0)),
    ],
)
def test_am_pm_este_recunoscut(text, asteptat):
    assert extract(text).at_time == asteptat


def test_am_pm_explicit_nu_mai_este_ambiguu():
    """„La 3" singur ar fi neclar; „la 3 PM" nu mai are ce sa intrebe."""
    assert "ora_ambigua" in extract("la 3").reasons
    assert extract("la 3 PM").reasons == ()


# ------------------------------------------------------------ intervale orare


@pytest.mark.parametrize(
    "text,inceput,final",
    [
        ("de la 10 la 12", time(10, 0), time(12, 0)),
        ("între 10 și 12", time(10, 0), time(12, 0)),
        ("10–12", time(10, 0), time(12, 0)),
        ("10:30–12:45", time(10, 30), time(12, 45)),
        ("10:30-12:45", time(10, 30), time(12, 45)),
        ("de la zece la douăsprezece", time(10, 0), time(12, 0)),
        ("de la 10 AM la 12 PM", time(10, 0), time(12, 0)),
        ("de la 2 PM la 4 PM", time(14, 0), time(16, 0)),
        ("de la 10 până la 12", time(10, 0), time(12, 0)),
    ],
)
def test_intervalul_da_si_ora_de_final(text, inceput, final):
    match = extract(text)

    assert match.at_time == inceput
    assert match.end_time == final


def test_intervalul_este_scos_din_titlu():
    text = "Ședință mâine de la 10 la 12 cu echipa"
    match = extract(text)

    assert (match.at_time, match.end_time) == (time(10, 0), time(12, 0))
    assert ro_time.strip_temporal(text, match) == "Ședință cu echipa"


def test_intervalul_are_prioritate_fata_de_data_numerica():
    """Fara aceasta ordine, „10–12" ar fi citit ca 10 decembrie."""
    match = extract("Ne vedem 10–12")

    assert match.at_time == time(10, 0)
    assert match.day is None


def test_intervalul_intors_cere_clarificare():
    match = extract("de la 14 la 12")

    assert match.at_time == time(14, 0)
    assert match.end_time is None
    assert "interval_invalid" in match.reasons


def test_cratima_intre_doua_numere_mici_nu_se_decide_singura():
    """„10-12" poate fi si interval orar, si 10 decembrie. Intrebam."""
    match = extract("Ne vedem 10-12")

    assert match.at_time is None
    assert match.end_time is None
    assert match.day is None
    assert "interval_sau_data" in match.reasons


def test_data_cu_an_scrisa_cu_cratima_ramane_data():
    assert extract("pe 10-12-2026").day == date(2026, 12, 10)


# ------------------------------------------------- saptamana viitoare fara zi


def test_saptamana_viitoare_fara_zi_cere_ziua():
    match = extract("Ne vedem săptămâna viitoare.")

    assert match.day is None
    assert "zi_saptamana_lipseste" in match.reasons


def test_saptamana_viitoare_cu_zi_da_data():
    """„Miercuri săptămâna viitoare" este o zi anume, nu o intrebare."""
    assert extract("miercuri săptămâna viitoare").day is not None


def test_ziua_din_saptamana_urmatoare_nu_este_prima_de_acum():
    # NOW este marti, 1 septembrie. Miercuri „săptămâna viitoare" este 9, nu 2.
    assert ro_time.weekday_next_week(NOW.date(), 2) == date(2026, 9, 9)


@pytest.mark.parametrize(
    "text,asteptat",
    [("la trei", time(15, 0)), ("la două", time(14, 0)), ("la zece", time(10, 0))],
)
def test_ora_rostita_in_cuvinte_este_recunoscuta(text, asteptat):
    assert extract(text).at_time == asteptat


@pytest.mark.parametrize("text", ["la o întâlnire", "la un control", "la noua adresă"])
def test_prepozitia_urmata_de_substantiv_nu_devine_ora(text):
    assert extract(text).at_time is None


@pytest.mark.parametrize(
    "text,are_zi,are_ora",
    [
        ("Mă întâlnesc mâine cu Ion.", True, False),
        ("Programează o întâlnire cu Ion.", False, False),
        ("Mă văd vineri la trei.", True, True),
        ("Cumpăr lapte și pâine.", False, False),
        ("Sună-l pe Ion la 14:30.", False, True),
    ],
)
def test_marcajele_temporale_sunt_detectate_separat(text, are_zi, are_ora):
    assert ro_time.has_date_marker(text) is are_zi
    assert ro_time.has_time_marker(text) is are_ora
