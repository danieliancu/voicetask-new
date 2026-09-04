"""Raspunsul la clarificare completeaza schita, fara sa piarda ce era deja extras.

Cazul central este cel raportat: „Mă întâlnesc mâine cu Ion." → aplicatia intreaba
ora → „La trei după-amiaza." → aceeasi schita, cu ora completata si cu data,
persoana si titlul neatinse.
"""

from __future__ import annotations

import pytest
import time_machine
from django.urls import reverse

from apps.assistant import services
from apps.assistant.models import IntentDraft
from apps.assistant.schemas import Intent
from apps.assistant.tests._stubs import ACUM, MAINE, ModelSimulat
from apps.core.providers.registry import override_provider
from apps.scheduling.models import Appointment

pytestmark = pytest.mark.django_db


def schita_incompleta(user):
    """Schita produsa de comanda raportata: data si persoana da, ora nu."""
    model = ModelSimulat(
        intent=Intent.CREATE_APPOINTMENT,
        confidence=0.9,
        date=None,
        start_time=None,
        person="Ion",
        title="Întâlnire cu Ion",
    )
    with time_machine.travel(ACUM, tick=False), override_provider("intent", model):
        return services.interpret(user, "Mă întâlnesc mâine cu Ion.")


def raspunde(client, draft, text):
    with time_machine.travel(ACUM, tick=False):
        return client.post(
            reverse("assistant:draft_clarify", args=[draft.uid]),
            {"raspuns": text},
            headers={"HX-Request": "true"},
        )


def confirma(client, draft, **campuri):
    # Sub acelasi ceas ca interpretarea: altfel schita ar aparea expirata.
    with time_machine.travel(ACUM, tick=False):
        return client.post(
            reverse("assistant:draft_confirm", args=[draft.uid]),
            campuri,
            headers={"HX-Request": "true"},
        )


def test_schita_initiala_are_data_persoana_si_titlul_dar_cere_ora(user):
    draft = schita_incompleta(user)

    assert draft.intent == Intent.CREATE_APPOINTMENT
    assert draft.payload["date"] == MAINE
    assert draft.payload["person"] == "Ion"
    assert draft.payload["title"] == "Întâlnire cu Ion"
    assert draft.payload["start_time"] is None
    assert draft.status == IntentDraft.Status.NEEDS_CLARIFICATION
    assert draft.clarification_question == "La ce oră este întâlnirea?"


def test_raspunsul_completeaza_ora_si_pastreaza_restul(auth_client, user):
    draft = schita_incompleta(user)
    uid = draft.uid

    response = raspunde(auth_client, draft, "La trei după-amiaza.")
    assert response.status_code == 200

    draft.refresh_from_db()
    # Aceeasi schita, nu una noua: adresa din bara ramane valida.
    assert draft.uid == uid
    assert draft.status == IntentDraft.Status.DRAFT
    assert draft.payload["start_time"] == "15:00:00"
    assert draft.payload["date"] == MAINE
    assert draft.payload["person"] == "Ion"
    assert draft.payload["title"] == "Întâlnire cu Ion"
    assert draft.intent == Intent.CREATE_APPOINTMENT
    assert IntentDraft.objects.count() == 1


def test_raspunsul_nu_este_citit_ca_o_comanda_noua(auth_client, user):
    """„La trei după-amiaza." singur nu inseamna o programare fara persoana si zi."""
    draft = schita_incompleta(user)
    raspunde(auth_client, draft, "La trei după-amiaza.")

    draft.refresh_from_db()
    assert draft.intent == Intent.CREATE_APPOINTMENT
    assert draft.payload["date"] == MAINE
    assert IntentDraft.objects.filter(status=IntentDraft.Status.DISCARDED).count() == 0


def test_transcrierea_ramane_vizibila_dupa_completare(auth_client, user):
    draft = schita_incompleta(user)
    response = raspunde(auth_client, draft, "La trei după-amiaza.")

    draft.refresh_from_db()
    assert draft.source_text.startswith("Mă întâlnesc mâine cu Ion.")
    assert "La trei după-amiaza." in draft.source_text
    assert "Mă întâlnesc mâine cu Ion." in response.content.decode()


def test_raspunsul_care_nu_contine_ora_nu_strica_schita(auth_client, user):
    """Un raspuns pe langa subiect nu are voie sa stearga ce era deja bun."""
    draft = schita_incompleta(user)
    raspunde(auth_client, draft, "Nu știu încă.")

    draft.refresh_from_db()
    assert draft.status == IntentDraft.Status.NEEDS_CLARIFICATION
    assert draft.payload["date"] == MAINE
    assert draft.payload["person"] == "Ion"
    assert draft.payload["start_time"] is None
    assert draft.clarification_question.startswith("Nu am înțeles.")


def test_raspunsul_ambiguu_completeaza_dar_intreaba_mai_departe(auth_client, user):
    """„La trei" ramane neclar: valoarea intra in schita, confirmarea nu se deblocheaza."""
    draft = schita_incompleta(user)
    raspunde(auth_client, draft, "La trei.")

    draft.refresh_from_db()
    assert draft.payload["start_time"] == "15:00:00"
    assert draft.status == IntentDraft.Status.NEEDS_CLARIFICATION
    assert "ora_ambigua" in draft.payload["ambiguity"]


def test_raspunsul_la_conflictul_de_data_inlocuieste_data(auth_client, user):
    model = ModelSimulat(
        intent=Intent.CREATE_APPOINTMENT,
        confidence=0.9,
        date="2026-12-25",
        start_time="15:00",
        person="Ion",
        title="Întâlnire cu Ion",
    )
    with time_machine.travel(ACUM, tick=False), override_provider("intent", model):
        draft = services.interpret(user, "Mă întâlnesc mâine cu Ion.")

    # Ora „15:00" a fost si ea inventata: fraza nu contine nicio ora.
    assert "data_in_conflict" in draft.payload["ambiguity"]
    assert draft.payload["start_time"] is None

    raspunde(auth_client, draft, "Pe 5 septembrie.")

    draft.refresh_from_db()
    assert draft.payload["date"] == "2026-09-05"
    assert draft.payload["person"] == "Ion"
    assert "data_in_conflict" not in draft.payload["ambiguity"]
    # Data este lamurita, dar ora tot lipseste: schita ramane in clarificare.
    assert draft.clarification_question == "La ce oră este întâlnirea?"


def test_nimic_nu_se_salveaza_pana_la_confirmare(auth_client, user):
    draft = schita_incompleta(user)
    raspunde(auth_client, draft, "La trei după-amiaza.")

    assert Appointment.objects.count() == 0


def test_confirmarea_este_refuzata_cat_timp_schita_este_neclara(auth_client, user):
    draft = schita_incompleta(user)

    response = confirma(auth_client, draft)

    assert response.status_code == 409
    assert Appointment.objects.count() == 0


def test_fluxul_complet_pana_la_programarea_salvata(auth_client, user):
    """text → reconciliere → clarificare → confirmare → obiect real."""
    draft = schita_incompleta(user)
    raspunde(auth_client, draft, "La trei după-amiaza.")
    draft.refresh_from_db()

    response = confirma(
        auth_client,
        draft,
        intent=Intent.CREATE_APPOINTMENT,
        title="Întâlnire cu Ion",
        date=MAINE,
        start_time="15:00",
    )

    assert response.status_code == 204
    appointment = Appointment.objects.get()
    assert appointment.title == "Întâlnire cu Ion"
    assert appointment.starts_at.astimezone(ACUM.tzinfo).strftime("%Y-%m-%d %H:%M") == (
        f"{MAINE} 15:00"
    )


def test_partea_de_zi_dezambiguizeaza_ora_rostita_nu_o_inlocuieste(auth_client, user):
    """„La două" + „După-amiaza." inseamna 14:00, nu 15:00, cat da partea de zi."""
    model = ModelSimulat(
        intent=Intent.CREATE_APPOINTMENT, confidence=0.9, date=None, start_time=None, person="Ana"
    )
    with time_machine.travel(ACUM, tick=False), override_provider("intent", model):
        draft = services.interpret(user, "Mă întâlnesc poimâine la două cu Ana.")

    assert draft.payload["start_time"] == "14:00:00"
    assert "ora_ambigua" in draft.payload["ambiguity"]

    raspunde(auth_client, draft, "După-amiaza.")

    draft.refresh_from_db()
    assert draft.payload["start_time"] == "14:00:00"
    assert draft.status == IntentDraft.Status.DRAFT


def test_partea_de_zi_muta_ora_in_dimineata(auth_client, user):
    model = ModelSimulat(
        intent=Intent.CREATE_APPOINTMENT, confidence=0.9, date=None, start_time=None, person="Ana"
    )
    with time_machine.travel(ACUM, tick=False), override_provider("intent", model):
        draft = services.interpret(user, "Mă întâlnesc poimâine la două cu Ana.")

    raspunde(auth_client, draft, "Dimineața.")

    draft.refresh_from_db()
    assert draft.payload["start_time"] == "02:00:00"
