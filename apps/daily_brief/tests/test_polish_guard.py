"""Poarta anti-halucinatie pentru reformularea AI a rezumatului."""

import pytest

from apps.daily_brief.polish import polish, validate_polish

ORIGINAL = (
    "Bună dimineața, Daniel.\n"
    "Astăzi este joi, 3 septembrie.\n"
    "Ai 2 programări astăzi. Prima este la 10:00: Întâlnire proiect Alpha.\n"
    "La 12:30: Control medical, la Clinica MedLife.\n"
    "Factura energie are termen 6 septembrie, 84,20 lei."
)


def test_reformularea_curata_este_acceptata():
    candidat = (
        "Bună dimineața, Daniel.\n"
        "Astăzi, joi, 3 septembrie, ai 2 programări.\n"
        "Prima este la 10:00: Întâlnire proiect Alpha.\n"
        "Apoi la 12:30: Control medical, la Clinica MedLife.\n"
        "Factura energie are termen 6 septembrie, 84,20 lei."
    )
    acceptat, motiv = validate_polish(ORIGINAL, candidat)
    assert acceptat, motiv


def test_o_ora_inventata_este_respinsa():
    candidat = ORIGINAL + "\nȘi la 18:00 ai o ședință."
    acceptat, motiv = validate_polish(ORIGINAL, candidat)
    assert not acceptat
    assert motiv in {"numere_noi", "prea_lung", "prea_multe_cuvinte_noi"}


def test_o_suma_schimbata_este_respinsa():
    candidat = ORIGINAL.replace("84,20", "94,20")
    acceptat, motiv = validate_polish(ORIGINAL, candidat)
    assert not acceptat
    assert motiv == "numere_noi"


def test_pierderea_unei_informatii_este_respinsa():
    candidat = "Bună dimineața, Daniel. Ai o zi liniștită."
    acceptat, motiv = validate_polish(ORIGINAL, candidat)
    assert not acceptat
    assert motiv == "numere_pierdute"


def test_un_nume_propriu_nou_este_respins():
    candidat = ORIGINAL.replace("Clinica MedLife", "Clinica Regina Maria")
    acceptat, motiv = validate_polish(ORIGINAL, candidat)
    assert not acceptat
    assert motiv == "nume_noi"


def test_textul_prea_lung_este_respins():
    candidat = ORIGINAL + " " + ORIGINAL
    acceptat, motiv = validate_polish(ORIGINAL, candidat)
    assert not acceptat
    assert motiv == "prea_lung"


def test_textul_gol_este_respins():
    acceptat, motiv = validate_polish(ORIGINAL, "   ")
    assert not acceptat
    assert motiv == "text_gol"


def test_prea_multe_cuvinte_noi_sunt_respinse():
    candidat = (
        "Bună dimineața, Daniel. Astăzi este joi, 3 septembrie. Ai 2 programări astăzi. "
        "Prima este la 10:00: Întâlnire proiect Alpha. La 12:30: Control medical, la Clinica "
        "MedLife. Factura energie are termen 6 septembrie, 84,20 lei. "
        "Sper sincer să reușești absolut tot ceea ce ți-ai propus astăzi, indiferent cât "
        "de aglomerat pare programul."
    )
    acceptat, _ = validate_polish(ORIGINAL, candidat)
    assert not acceptat


def test_reformularea_este_oprita_implicit(settings):
    """`BRIEF_POLISH_ENABLED` este False in configuratia livrata."""
    assert settings.BRIEF_POLISH_ENABLED is False

    result = polish(ORIGINAL)

    assert result.accepted is False
    assert result.reason == "dezactivat"
    assert result.text == ORIGINAL


def test_fara_cheie_api_reformularea_nu_incearca(settings):
    settings.BRIEF_POLISH_ENABLED = True
    settings.AI_ENABLED = True
    settings.OPENAI_API_KEY = ""

    result = polish(ORIGINAL)

    assert result.accepted is False
    assert result.reason == "cheie_lipsa"
    assert result.text == ORIGINAL


@pytest.mark.django_db
def test_motivul_respingerii_este_pastrat_pe_rezumat(user, prefs, settings, monkeypatch):
    from apps.daily_brief import polish as polish_module
    from apps.daily_brief import services

    prefs.brief_polish_enabled = True
    prefs.save()
    monkeypatch.setattr(
        polish_module,
        "polish",
        lambda text: polish_module.PolishResult(text=text, accepted=False, reason="numere_noi"),
    )

    brief = services.get_or_create_brief(user, force=True)

    assert brief.polish_rejected_reason == "numere_noi"
    # Textul afisat ramane cel determinist.
    assert brief.text == brief.generated_text
