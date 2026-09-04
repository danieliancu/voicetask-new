"""Campurile obligatorii pe intentii, si cele trei bariere care le apara.

Politica opreste confirmarea, formularul refuza trimiterea, iar aplicarea schitei
refuza sa scrie. Oricare dintre ele ar fi ocolita, urmatoarea tot nu lasa sa treaca
o programare fara ora.
"""

from __future__ import annotations

from datetime import UTC, date, time

import pytest

from apps.assistant import drafts as drafts_module
from apps.assistant import policy
from apps.assistant.forms import AppointmentDraftForm, ReminderDraftForm
from apps.assistant.models import IntentDraft
from apps.assistant.schemas import Intent, IntentResult
from apps.scheduling.models import Appointment, Reminder

ZI = date(2026, 9, 2)


def rezultat(**campuri) -> IntentResult:
    return IntentResult(confidence=0.9, **campuri)


# ------------------------------------------------------------ campuri obligatorii


@pytest.mark.parametrize(
    "campuri,lipsuri",
    [
        (
            {"intent": Intent.CREATE_APPOINTMENT},
            ["titlu_lipseste", "data_lipseste", "ora_lipseste"],
        ),
        (
            {"intent": Intent.CREATE_APPOINTMENT, "title": "Dentist"},
            ["data_lipseste", "ora_lipseste"],
        ),
        (
            {"intent": Intent.CREATE_APPOINTMENT, "title": "Dentist", "date": ZI},
            ["ora_lipseste"],
        ),
        (
            {
                "intent": Intent.CREATE_APPOINTMENT,
                "title": "Dentist",
                "date": ZI,
                "start_time": time(10, 0),
            },
            [],
        ),
        (
            {"intent": Intent.CREATE_APPOINTMENT, "title": "Concediu", "date": ZI, "all_day": True},
            [],
        ),
        (
            {"intent": Intent.CREATE_REMINDER, "title": "Medicament", "date": ZI},
            ["ora_lipseste"],
        ),
        ({"intent": Intent.CREATE_NOTE}, ["continut_lipseste"]),
        ({"intent": Intent.CREATE_NOTE, "description": "lapte"}, []),
        ({"intent": Intent.SEARCH, "search_query": "factura"}, []),
        (
            {"intent": Intent.FOLLOW_UP_EMAIL},
            ["email_nespecificat", "data_lipseste", "ora_lipseste"],
        ),
        (
            {
                "intent": Intent.FOLLOW_UP_EMAIL,
                "target_id": 7,
                "date": ZI,
                "start_time": time(9, 0),
            },
            [],
        ),
    ],
)
def test_campurile_obligatorii_pe_intentii(campuri, lipsuri):
    assert policy.missing_fields(rezultat(**campuri)) == lipsuri


def test_alarma_nu_poate_fi_toata_ziua():
    """`all_day` scuteste de ora doar programarile, nu si alarmele."""
    with pytest.raises(ValueError, match="programare"):
        rezultat(intent=Intent.CREATE_REMINDER, title="Medicament", date=ZI, all_day=True)


def test_programarea_toata_ziua_nu_are_ora():
    with pytest.raises(ValueError, match="toată ziua"):
        rezultat(
            intent=Intent.CREATE_APPOINTMENT,
            title="Concediu",
            date=ZI,
            all_day=True,
            start_time=time(9, 0),
        )


@pytest.mark.parametrize(
    "campuri,intrebare",
    [
        (
            {"intent": Intent.CREATE_APPOINTMENT, "title": "Dentist", "date": ZI},
            "La ce oră este întâlnirea?",
        ),
        (
            {"intent": Intent.CREATE_REMINDER, "title": "Medicament", "date": ZI},
            "La ce oră să te anunț?",
        ),
        (
            {"intent": Intent.CREATE_REMINDER, "title": "Medicament"},
            "Pentru ce dată să setez alarma?",
        ),
    ],
)
def test_intrebarea_este_formulata_pe_intentie(campuri, intrebare):
    decision = policy.decide(rezultat(**campuri))

    assert decision.needs_clarification
    assert not decision.can_confirm
    assert decision.question == intrebare


def test_motivele_noi_de_reconciliere_opresc_confirmarea():
    """Un motiv necunoscut politicii ar fi fost inregistrat si ignorat tacit."""
    decision = policy.decide(
        rezultat(
            intent=Intent.CREATE_APPOINTMENT,
            title="Dentist",
            date=ZI,
            start_time=time(10, 0),
            ambiguity=["data_in_conflict"],
        )
    )

    assert decision.needs_clarification
    assert decision.reason == "data_in_conflict"


# ------------------------------------------------------- formularul, pe server


@pytest.mark.django_db
def test_formularul_refuza_programarea_fara_ora(user):
    draft = IntentDraft.objects.create(
        owner=user, intent=Intent.CREATE_APPOINTMENT, payload={"intent": Intent.CREATE_APPOINTMENT}
    )
    form = AppointmentDraftForm({"title": "Dentist", "date": "2026-09-02"}, draft=draft)

    assert not form.is_valid()
    assert "start_time" in form.errors


@pytest.mark.django_db
def test_formularul_refuza_alarma_fara_ora(user):
    draft = IntentDraft.objects.create(
        owner=user, intent=Intent.CREATE_REMINDER, payload={"intent": Intent.CREATE_REMINDER}
    )
    form = ReminderDraftForm({"title": "Medicament", "date": "2026-09-02"}, draft=draft)

    assert not form.is_valid()
    assert "start_time" in form.errors


@pytest.mark.django_db
def test_formularul_accepta_programarea_pe_toata_ziua(user):
    draft = IntentDraft.objects.create(
        owner=user, intent=Intent.CREATE_APPOINTMENT, payload={"intent": Intent.CREATE_APPOINTMENT}
    )
    form = AppointmentDraftForm(
        {"title": "Concediu", "date": "2026-09-02", "all_day": "on"}, draft=draft
    )

    assert form.is_valid(), form.errors
    assert form.to_overrides()["all_day"] is True


@pytest.mark.django_db
def test_formularul_refuza_ora_impreuna_cu_toata_ziua(user):
    draft = IntentDraft.objects.create(
        owner=user, intent=Intent.CREATE_APPOINTMENT, payload={"intent": Intent.CREATE_APPOINTMENT}
    )
    form = AppointmentDraftForm(
        {"title": "Concediu", "date": "2026-09-02", "start_time": "10:00", "all_day": "on"},
        draft=draft,
    )

    assert not form.is_valid()
    assert "all_day" in form.errors


# --------------------------------------------------- aplicarea schitei confirmate


@pytest.mark.django_db
def test_aplicarea_refuza_programarea_fara_ora_in_loc_sa_o_presupuna(user):
    """Inainte, o programare fara ora se salva tacit la 09:00."""
    draft = IntentDraft.objects.create(
        owner=user,
        intent=Intent.CREATE_APPOINTMENT,
        payload=rezultat(
            intent=Intent.CREATE_APPOINTMENT, title="Dentist", date=ZI
        ).model_dump(mode="json"),
    )

    with pytest.raises(drafts_module.DraftError, match="oră"):
        drafts_module.apply(draft)

    assert Appointment.objects.count() == 0


@pytest.mark.django_db
def test_aplicarea_refuza_alarma_fara_ora(user):
    draft = IntentDraft.objects.create(
        owner=user,
        intent=Intent.CREATE_REMINDER,
        payload=rezultat(
            intent=Intent.CREATE_REMINDER, title="Medicament", date=ZI
        ).model_dump(mode="json"),
    )

    with pytest.raises(drafts_module.DraftError, match="oră"):
        drafts_module.apply(draft)

    assert Reminder.objects.count() == 0


@pytest.mark.django_db
def test_programarea_pe_toata_ziua_se_salveaza_fara_ora(user, prefs):
    draft = IntentDraft.objects.create(
        owner=user,
        intent=Intent.CREATE_APPOINTMENT,
        payload=rezultat(
            intent=Intent.CREATE_APPOINTMENT, title="Concediu", date=ZI, all_day=True
        ).model_dump(mode="json"),
    )

    _, pk = drafts_module.apply(draft)
    appointment = Appointment.objects.get(pk=pk)

    assert appointment.all_day is True
    assert appointment.ends_at is None
    assert appointment.starts_at.astimezone(prefs.tzinfo).time() == time(0, 0)


@pytest.mark.django_db
@pytest.mark.parametrize("fus,ora_utc", [("Europe/London", 14), ("Europe/Bucharest", 12)])
def test_ora_se_scrie_in_fusul_utilizatorului(user, prefs, fus, ora_utc):
    """Ora 15:00 la Londra si ora 15:00 la Bucuresti sunt momente diferite.

    Verificarea se face pe valoarea stocata (UTC), pentru ca acolo se vede daca
    fusul folosit la scriere a fost al utilizatorului sau al serverului.
    """
    prefs.timezone = fus
    prefs.save(update_fields=["timezone"])
    draft = IntentDraft.objects.create(
        owner=user,
        intent=Intent.CREATE_APPOINTMENT,
        payload=rezultat(
            intent=Intent.CREATE_APPOINTMENT, title="Dentist", date=ZI, start_time=time(15, 0)
        ).model_dump(mode="json"),
    )

    _, pk = drafts_module.apply(draft)
    appointment = Appointment.objects.get(pk=pk)

    assert appointment.starts_at.astimezone(prefs.tzinfo).strftime("%H:%M") == "15:00"
    assert appointment.starts_at.astimezone(UTC).hour == ora_utc
