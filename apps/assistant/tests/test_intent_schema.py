"""Validarea stricta a rezultatului interpretarii."""

from datetime import date, time

import pytest

from apps.assistant.schemas import (
    Intent,
    IntentValidationError,
    parse_result,
)


def test_campurile_in_plus_sunt_respinse():
    """Un model care inventeaza un camp nu trebuie sa treaca de validare."""
    with pytest.raises(IntentValidationError):
        parse_result({"intent": "create_note", "title": "X", "camp_inventat": "da"})


def test_intentia_necunoscuta_este_respinsa():
    with pytest.raises(IntentValidationError):
        parse_result({"intent": "create_universe"})


def test_ora_de_final_inaintea_celei_de_inceput_este_respinsa():
    with pytest.raises(IntentValidationError):
        parse_result(
            {
                "intent": "create_appointment",
                "start_time": "12:00",
                "end_time": "10:00",
            }
        )


def test_cautarea_fara_termen_este_respinsa():
    with pytest.raises(IntentValidationError):
        parse_result({"intent": "search"})


def test_clarificarea_fara_intrebare_este_respinsa():
    with pytest.raises(IntentValidationError):
        parse_result({"intent": "create_note", "clarification_required": True})


def test_confidence_in_afara_intervalului_este_respinsa():
    with pytest.raises(IntentValidationError):
        parse_result({"intent": "create_note", "confidence": 1.5})


def test_decalajul_negativ_este_respins():
    with pytest.raises(IntentValidationError):
        parse_result({"intent": "create_reminder", "reminder_offset": -10})


def test_sirurile_goale_devin_none():
    result = parse_result({"intent": "create_note", "title": "  ", "location": ""})
    assert result.title is None
    assert result.location is None


def test_payload_valid_este_acceptat():
    result = parse_result(
        {
            "intent": "create_appointment",
            "title": "Întâlnire",
            "date": "2026-09-06",
            "start_time": "10:00",
            "end_time": "11:00",
            "location": "Google Meet",
            "reminder_offset": 30,
            "confidence": 0.9,
        }
    )
    assert result.intent is Intent.CREATE_APPOINTMENT
    assert result.date == date(2026, 9, 6)
    assert result.start_time == time(10, 0)
    assert result.reminder_offset == 30


def test_intentiile_distructive_sunt_marcate():
    assert parse_result({"intent": "delete_item", "target_id": 1}).is_destructive
    assert not parse_result({"intent": "create_note"}).is_destructive


def test_intentiile_care_au_nevoie_de_tinta():
    assert parse_result({"intent": "update_item", "target_id": 1}).needs_target
    assert parse_result({"intent": "delete_item", "target_id": 1}).needs_target
    assert not parse_result({"intent": "create_note"}).needs_target


def test_eroarea_expune_campurile_problematice():
    try:
        parse_result({"intent": "search", "camp_gresit": 1})
    except IntentValidationError as exc:
        assert exc.fields
    else:
        pytest.fail("Validarea ar fi trebuit sa esueze.")


def test_schema_json_contine_toate_campurile_cerute():
    """Schema trimisa modelului AI trebuie sa acopere contractul din cerinta."""
    from apps.assistant.schemas import JSON_SCHEMA

    obligatorii = {
        "intent",
        "title",
        "description",
        "date",
        "start_time",
        "end_time",
        "location",
        "reminder_offset",
        "search_query",
        "target_id",
        "confidence",
        "clarification_required",
        "clarification_question",
    }
    assert obligatorii <= set(JSON_SCHEMA["properties"])
