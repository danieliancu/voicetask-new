"""Fiecare tip isi are formularul lui, ales pe server.

Formularul universal arata aceleasi campuri peste tot: o notita primea dată, oră,
locație, persoană si alarmă — campuri fara unde sa se salveze — iar dropdownul de
tip putea transforma din greseala notita in programare.
"""

from __future__ import annotations

import pytest

from apps.assistant.forms import (
    AppointmentDraftForm,
    EmailFollowUpForm,
    NoteDraftForm,
    ReminderDraftForm,
    get_draft_form_class,
)
from apps.assistant.models import IntentDraft
from apps.assistant.schemas import Intent
from apps.core.enums import ItemKind

pytestmark = pytest.mark.django_db

CAMPURI_DE_TIMP = {"date", "start_time", "end_time", "all_day"}


def schita(user, intent, **kwargs) -> IntentDraft:
    return IntentDraft.objects.create(
        owner=user, intent=intent, payload={"intent": intent}, **kwargs
    )


@pytest.mark.parametrize(
    "intent,clasa",
    [
        (Intent.CREATE_NOTE, NoteDraftForm),
        (Intent.CREATE_APPOINTMENT, AppointmentDraftForm),
        (Intent.CREATE_REMINDER, ReminderDraftForm),
        (Intent.FOLLOW_UP_EMAIL, EmailFollowUpForm),
    ],
)
def test_fiecare_intentie_primeste_formularul_ei(user, intent, clasa):
    assert get_draft_form_class(schita(user, intent)) is clasa


@pytest.mark.parametrize(
    "kind,clasa",
    [
        (ItemKind.NOTE, NoteDraftForm),
        (ItemKind.APPOINTMENT, AppointmentDraftForm),
        (ItemKind.REMINDER, ReminderDraftForm),
    ],
)
def test_modificarea_foloseste_formularul_tipului_vizat(user, kind, clasa):
    draft = schita(user, Intent.UPDATE_ITEM, target_kind=kind, target_id=1)

    assert get_draft_form_class(draft) is clasa


@pytest.mark.parametrize("intent", [Intent.SEARCH, Intent.UNKNOWN, Intent.DELETE_ITEM])
def test_ce_nu_se_salveaza_nu_are_formular(user, intent):
    assert get_draft_form_class(schita(user, intent)) is None


# ------------------------------------------------------------ campurile vizibile


def test_notita_are_doar_campurile_ei(user):
    form = NoteDraftForm(draft=schita(user, Intent.CREATE_NOTE))

    assert set(form.fields) == {"title", "description", "category_id", "is_pinned"}
    assert not CAMPURI_DE_TIMP & set(form.fields)
    assert "location" not in form.fields
    assert "person" not in form.fields
    assert "reminder_offset" not in form.fields


def test_alarma_nu_are_locatie_persoana_sau_ora_finala(user):
    form = ReminderDraftForm(draft=schita(user, Intent.CREATE_REMINDER))

    assert set(form.fields) == {"title", "description", "date", "start_time"}
    assert "all_day" not in form.fields
    assert "reminder_offset" not in form.fields


def test_programarea_are_toate_campurile_de_timp_si_loc(user):
    form = AppointmentDraftForm(draft=schita(user, Intent.CREATE_APPOINTMENT))

    assert set(form.fields) >= CAMPURI_DE_TIMP
    assert {"location", "person", "reminder_offset"} <= set(form.fields)


@pytest.mark.parametrize(
    "clasa,intent",
    [
        (NoteDraftForm, Intent.CREATE_NOTE),
        (AppointmentDraftForm, Intent.CREATE_APPOINTMENT),
        (ReminderDraftForm, Intent.CREATE_REMINDER),
        (EmailFollowUpForm, Intent.FOLLOW_UP_EMAIL),
    ],
)
def test_tipul_nu_se_poate_schimba_din_formular(user, clasa, intent):
    """Dropdownul de tip a disparut: o notita nu mai devine programare din greseala."""
    form = clasa(draft=schita(user, intent))

    assert "intent" not in form.fields
    assert form.intent == intent


def test_modificarea_ramane_modificare_desi_foloseste_formularul_programarii(user):
    draft = schita(user, Intent.UPDATE_ITEM, target_kind=ItemKind.APPOINTMENT, target_id=1)
    form = AppointmentDraftForm(
        {"title": "Control", "date": "2026-09-02", "start_time": "10:00"}, draft=draft
    )

    assert form.is_valid(), form.errors
    assert form.to_overrides()["intent"] == Intent.UPDATE_ITEM


# ---------------------------------------------------------- categoria notitei


def test_categoria_altui_utilizator_este_respinsa(user, other_user):
    from apps.notes.models import NoteCategory

    straina = NoteCategory.objects.create(owner=other_user, name="Personal", slug="personal")
    form = NoteDraftForm(
        {"title": "Idee", "category_id": str(straina.pk)}, draft=schita(user, Intent.CREATE_NOTE)
    )

    assert not form.is_valid()
    assert "category_id" in form.errors


def test_categoria_proprie_este_acceptata_si_salvata(user):
    from apps.assistant import drafts as drafts_module
    from apps.notes.models import Note, NoteCategory

    categorie = NoteCategory.objects.create(owner=user, name="Rețete", slug="retete")
    draft = schita(user, Intent.CREATE_NOTE)
    form = NoteDraftForm(
        {
            "title": "Ciorbă de burtă",
            "description": "smântână, usturoi",
            "category_id": str(categorie.pk),
            "is_pinned": "on",
        },
        draft=draft,
    )

    assert form.is_valid(), form.errors
    drafts_module.apply(draft, overrides=form.to_overrides())

    note = Note.objects.get()
    assert note.category_id == categorie.pk
    assert note.is_pinned is True
    assert note.content == "smântână, usturoi"


def test_notita_cere_titlu_sau_continut(user):
    form = NoteDraftForm({"title": "", "description": ""}, draft=schita(user, Intent.CREATE_NOTE))

    assert not form.is_valid()
