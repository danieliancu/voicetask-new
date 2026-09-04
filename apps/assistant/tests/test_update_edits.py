"""O modificare schimbă doar ce s-a cerut.

`UPDATE_FIELDS` aplica orice titlu si orice descriere produse de interpretare, deci
„Mută programarea la ora 16" rescria si titlul, si descrierea obiectului. Aici se
verifica regula noua: fara o cerere explicita, textul ramane al obiectului.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
import time_machine
from django.utils import timezone

from apps.assistant import drafts as drafts_module
from apps.assistant import edits, services
from apps.assistant.forms import get_draft_form_class
from apps.assistant.models import IntentDraft
from apps.assistant.schemas import Intent
from apps.assistant.tests._stubs import BUCURESTI, ModelSimulat
from apps.core.enums import ItemKind
from apps.core.providers.registry import override_provider

pytestmark = pytest.mark.django_db

TITLU = "Control stomatologic"
DESCRIERE = "Aduc radiografia veche."
#: Vineri, 4 septembrie 2026, 11:30 la Bucuresti — momentul care intra in separator.
ACUM = datetime(2026, 9, 4, 11, 30, tzinfo=BUCURESTI)


@pytest.fixture
def appointment(user, appointment_factory):
    return appointment_factory(
        user, title=TITLU, description=DESCRIERE, location="Clinica Dent", day_offset=2, hour=10
    )


def comanda(user, appointment, text, **model) -> IntentDraft:
    """Interpreteaza o comanda de modificare peste o programare existenta."""
    payload = {
        "intent": Intent.UPDATE_ITEM,
        "confidence": 0.9,
        "target_kind": ItemKind.APPOINTMENT,
        "target_id": appointment.pk,
        **model,
    }
    with time_machine.travel(ACUM, tick=False), override_provider(
        "intent", ModelSimulat(**payload)
    ):
        return services.interpret(
            user, text, mode="edit", target_kind=ItemKind.APPOINTMENT, target_id=appointment.pk
        )


def salveaza(draft, **camp):
    """Trimite formularul schitei, ca in interfata."""
    form_class = get_draft_form_class(draft)
    form = form_class(draft=draft)
    date = {
        "title": form.initial.get("title") or "",
        "description": form.initial.get("description") or "",
        "location": form.initial.get("location") or "",
        "date": form.initial["date"].isoformat(),
        "start_time": form.initial["start_time"].isoformat(),
        **camp,
    }
    bound = form_class(date, draft=draft)
    assert bound.is_valid(), bound.errors
    with time_machine.travel(ACUM, tick=False):
        return drafts_module.apply(draft, overrides=bound.to_overrides())


# ------------------------------------------------ ce nu s-a cerut nu se schimba


def test_mutarea_orei_nu_atinge_titlul_si_descrierea(user, appointment):
    """Modelul returneaza un titlu la fiecare comanda; el nu trebuie aplicat."""
    draft = comanda(
        user, appointment, "Mută programarea la ora 16", title="Mutare", description="Mutat la 16"
    )

    assert draft.payload["title"] is None
    assert draft.payload["description"] is None

    salveaza(draft)
    appointment.refresh_from_db()
    assert appointment.title == TITLU
    assert appointment.description == DESCRIERE
    assert timezone.localtime(appointment.starts_at, BUCURESTI).hour == 16


def test_schimbarea_locatiei_nu_atinge_titlul(user, appointment):
    draft = comanda(
        user,
        appointment,
        "Schimbă locația în Google Meet",
        title="Ședință online",
        location="Google Meet",
    )

    assert draft.payload["title"] is None
    salveaza(draft, location="Google Meet")

    appointment.refresh_from_db()
    assert appointment.title == TITLU
    assert appointment.location == "Google Meet"
    assert appointment.description == DESCRIERE


# ------------------------------------------------------- completarea descrierii


def test_completarea_adauga_si_pastreaza_originalul(user, appointment):
    draft = comanda(
        user, appointment, "Adaugă că trebuie să pregătesc raportul", description="raportul"
    )
    text = draft.payload["description"]

    assert text.startswith(DESCRIERE)
    assert edits.SEPARATOR in text
    assert "Modificare · 4 septembrie 2026, 11:30" in text
    assert text.endswith("trebuie să pregătesc raportul")


def test_completarea_nu_scrie_html(user, appointment):
    draft = comanda(user, appointment, "Adaugă că vin și copiii")

    assert "<" not in draft.payload["description"]


def test_fara_separator_cand_nu_exista_descriere(user, appointment_factory):
    gol = appointment_factory(user, title=TITLU, description="", day_offset=2, hour=10)
    draft = comanda(user, gol, "Adaugă că vin și copiii")

    assert draft.payload["description"] == "vin și copiii"
    assert edits.SEPARATOR not in draft.payload["description"]


def test_completarea_ajunge_in_obiect(user, appointment):
    draft = comanda(user, appointment, "Adaugă că vin și copiii")
    salveaza(draft, description=draft.payload["description"])

    appointment.refresh_from_db()
    assert appointment.description.startswith(DESCRIERE)
    assert appointment.description.endswith("vin și copiii")


def test_a_doua_confirmare_nu_adauga_din_nou(user, appointment):
    draft = comanda(user, appointment, "Adaugă că vin și copiii")
    salveaza(draft, description=draft.payload["description"])
    appointment.refresh_from_db()
    prima = appointment.description

    # A doua apasare pe „Salvează" pe aceeasi schita.
    with time_machine.travel(ACUM, tick=False):
        drafts_module.apply(draft)

    appointment.refresh_from_db()
    assert appointment.description == prima
    assert appointment.description.count(edits.SEPARATOR) == 1


# ------------------------------------------------------ schimbari explicite


def test_redenumirea_explicita_schimba_titlul(user, appointment):
    draft = comanda(user, appointment, "Schimbă titlul în Control anual")

    assert draft.payload["title"] == "Control anual"
    salveaza(draft, title="Control anual")

    appointment.refresh_from_db()
    assert appointment.title == "Control anual"
    assert appointment.description == DESCRIERE


def test_inlocuirea_explicita_schimba_descrierea(user, appointment):
    draft = comanda(user, appointment, "Înlocuiește descrierea cu Totul a fost amânat")

    assert draft.payload["description"] == "Totul a fost amânat"
    assert edits.SEPARATOR not in draft.payload["description"]
    assert draft.payload["title"] is None


def test_o_formulare_ambigua_nu_schimba_nimic(user, appointment):
    draft = comanda(user, appointment, "Schimbă titlul")

    assert "editare_ambigua" in draft.payload["ambiguity"]
    assert draft.payload["title"] is None
    assert draft.payload["description"] is None
    assert draft.status == IntentDraft.Status.NEEDS_CLARIFICATION

    appointment.refresh_from_db()
    assert appointment.title == TITLU


# ------------------------------------------------------------ detectorul pur


@pytest.mark.parametrize(
    "text,titlu",
    [
        ("Schimbă titlul în Control anual", "Control anual"),
        ("Modifică titlul în Ședință de proiect", "Ședință de proiect"),
        ("Redenumește în Vizită medicală", "Vizită medicală"),
    ],
)
def test_formulele_de_redenumire(text, titlu):
    assert edits.detect(text).title == titlu


@pytest.mark.parametrize(
    "text,adaugat",
    [
        ("Adaugă că trebuie să pregătesc raportul", "trebuie să pregătesc raportul"),
        ("Adaugă o notiță că vin și copiii", "vin și copiii"),
        ("Completează cu adresa nouă", "adresa nouă"),
    ],
)
def test_formulele_de_completare(text, adaugat):
    assert edits.detect(text).append == adaugat


@pytest.mark.parametrize(
    "text",
    [
        "Mută programarea la ora 16",
        "Schimbă locația în Google Meet",
        "Mută alarma cu două zile înainte",
        "Amână programarea pentru vineri",
    ],
)
def test_comenzile_structurale_nu_ating_textul(text):
    cerere = edits.detect(text)

    assert not cerere.touches_text
    assert not cerere.ambiguous


def test_separatorul_pastreaza_textul_dinainte_caracter_cu_caracter():
    existent = "Prima linie.\nA doua linie."
    rezultat = edits.append_to_description(existent, "ceva nou", ACUM)

    assert rezultat.startswith(existent)
    assert rezultat.count("ceva nou") == 1


def test_completarea_foloseste_fusul_utilizatorului(user, appointment):
    """Ora din separator este cea a utilizatorului, nu a serverului."""
    from apps.accounts.models import UserPreference

    prefs = UserPreference.for_user(user)
    prefs.timezone = "Europe/London"
    prefs.save(update_fields=["timezone"])

    draft = comanda(user, appointment, "Adaugă că vin și copiii")

    # 11:30 la Bucuresti inseamna 09:30 la Londra.
    assert "09:30" in draft.payload["description"]


def test_alarma_isi_pastreaza_titlul_la_mutare(user, reminder_factory):
    reminder = reminder_factory(user, title="Ia medicamentul", day_offset=1, hour=9)
    payload = {
        "intent": Intent.UPDATE_ITEM,
        "confidence": 0.9,
        "title": "Mutare alarmă",
        "target_kind": ItemKind.REMINDER,
        "target_id": reminder.pk,
    }
    with time_machine.travel(ACUM, tick=False), override_provider(
        "intent", ModelSimulat(**payload)
    ):
        draft = services.interpret(
            user, "Mută alarma la ora 8", mode="edit",
            target_kind=ItemKind.REMINDER, target_id=reminder.pk,
        )

    assert draft.payload["title"] is None

    form_class = get_draft_form_class(draft)
    form = form_class(draft=draft)
    bound = form_class(
        {
            "title": form.initial["title"],
            "description": form.initial.get("description") or "",
            "date": form.initial["date"].isoformat(),
            "start_time": "08:00",
        },
        draft=draft,
    )
    assert bound.is_valid(), bound.errors
    # Sub acelasi ceas ca interpretarea: altfel schita ar aparea expirata.
    with time_machine.travel(ACUM, tick=False):
        drafts_module.apply(draft, overrides=bound.to_overrides())

    reminder.refresh_from_db()
    assert reminder.title == "Ia medicamentul"
    assert timezone.localtime(reminder.remind_at, BUCURESTI).hour == 8


def test_durata_programarii_ramane_dupa_mutare(user, appointment_factory, at):
    starts = at(2, 10)
    appointment = appointment_factory(
        user, title=TITLU, starts_at=starts, ends_at=starts + timedelta(minutes=30)
    )
    draft = comanda(user, appointment, "Mută programarea la ora 16")
    salveaza(draft, start_time="16:00")

    appointment.refresh_from_db()
    assert appointment.ends_at - appointment.starts_at == timedelta(minutes=30)
