"""Corectiile deja livrate, pastrate sub test.

Sunt lucruri reparate in etapa anterioara, pe care lucrarile ulterioare —
formulare noi, intervale orare, alte clarificari — le-ar putea strica fara ca
cineva sa observe. Fiecare test aici este o problema care a existat cu adevarat.
"""

from __future__ import annotations

import json
import zoneinfo
from datetime import time
from pathlib import Path

import pytest
import time_machine
from django.conf import settings
from django.urls import reverse

from apps.accounts.models import UserPreference
from apps.assistant import drafts as drafts_module
from apps.assistant import services
from apps.assistant.models import IntentDraft
from apps.assistant.schemas import Intent
from apps.assistant.tests._stubs import ACUM, MAINE, ModelSimulat
from apps.core.providers.registry import override_provider
from apps.scheduling.models import Appointment

pytestmark = pytest.mark.django_db

INTALNIRE = {
    "intent": Intent.CREATE_APPOINTMENT,
    "confidence": 0.9,
    "date": None,
    "start_time": None,
    "person": "Ion",
    "title": "Întâlnire cu Ion",
}


def interpreteaza(user, text, **camp):
    model = ModelSimulat(**{**INTALNIRE, **camp})
    with time_machine.travel(ACUM, tick=False), override_provider("intent", model):
        return services.interpret(user, text)


def test_data_rostita_ajunge_in_schita_chiar_daca_modelul_o_omite(user):
    """Problema raportata initial: „mâine" se pierdea cand modelul returna null."""
    draft = interpreteaza(user, "Mă întâlnesc mâine cu Ion.")

    assert draft.payload["date"] == MAINE
    assert draft.payload["person"] == "Ion"
    assert draft.clarification_question == "La ce oră este întâlnirea?"


def test_raspunsul_completeaza_aceeasi_schita(auth_client, user):
    draft = interpreteaza(user, "Mă întâlnesc mâine cu Ion.")
    uid = draft.uid

    with time_machine.travel(ACUM, tick=False):
        auth_client.post(
            reverse("assistant:draft_clarify", args=[draft.uid]),
            {"raspuns": "La trei după-amiaza."},
            headers={"HX-Request": "true"},
        )

    draft.refresh_from_db()
    assert draft.uid == uid
    assert draft.payload["start_time"] == "15:00:00"
    assert draft.payload["date"] == MAINE
    assert draft.payload["person"] == "Ion"
    assert IntentDraft.objects.count() == 1


def test_all_day_nu_se_activeaza_singur(user):
    draft = interpreteaza(user, "Mă întâlnesc mâine la 10 cu Ion.", all_day=False)

    assert draft.payload["all_day"] is False


def test_all_day_cerut_de_model_cade_daca_s_a_rostit_o_ora(user):
    draft = interpreteaza(user, "Mă întâlnesc mâine la 10 cu Ion.", all_day=True, start_time=None)

    assert draft.payload["all_day"] is False
    assert draft.payload["start_time"] == "10:00:00"


@pytest.mark.parametrize(
    "fus,ora_utc", [("Europe/London", 14), ("Europe/Bucharest", 12)]
)
def test_ora_se_scrie_in_fusul_utilizatorului(user, fus, ora_utc):
    prefs = UserPreference.for_user(user)
    prefs.timezone = fus
    prefs.save(update_fields=["timezone"])

    draft = IntentDraft.objects.create(
        owner=user,
        intent=Intent.CREATE_APPOINTMENT,
        payload={
            "intent": Intent.CREATE_APPOINTMENT,
            "title": "Dentist",
            "date": MAINE,
            "start_time": "15:00:00",
            "confidence": 0.9,
        },
    )
    _, pk = drafts_module.apply(draft)
    appointment = Appointment.objects.get(pk=pk)

    assert appointment.starts_at.astimezone(zoneinfo.ZoneInfo("UTC")).hour == ora_utc


def test_nicio_ora_implicita_la_salvare(user):
    """`DEFAULT_TIME = 09:00` transforma tacit „mâine" in „mâine la 9"."""
    draft = IntentDraft.objects.create(
        owner=user,
        intent=Intent.CREATE_APPOINTMENT,
        payload={
            "intent": Intent.CREATE_APPOINTMENT,
            "title": "Dentist",
            "date": MAINE,
            "confidence": 0.9,
        },
    )

    with pytest.raises(drafts_module.DraftError, match="oră"):
        drafts_module.apply(draft)
    assert Appointment.objects.count() == 0


@pytest.mark.parametrize("incredere,afisat", [(0.85, "85%"), (0.45, "45%")])
def test_increderea_se_afiseaza_ca_procent(auth_client, user, incredere, afisat):
    """`floatformat:0` urmat de „0%" arata 0.85 ca „10%"."""
    draft = interpreteaza(user, "Mă întâlnesc mâine cu Ion.", confidence=incredere)

    with time_machine.travel(ACUM, tick=False):
        html = auth_client.get(reverse("assistant:draft", args=[draft.uid])).content.decode()

    assert f"Încredere {afisat}" in html


def schita_cu_conflict(user):
    return interpreteaza(user, "Mă văd vineri la 10 cu Maria.", date="2026-09-11", person="Maria")


def raspunde(client, draft, text):
    with time_machine.travel(ACUM, tick=False):
        return client.post(
            reverse("assistant:draft_clarify", args=[draft.uid]),
            {"raspuns": text},
            headers={"HX-Request": "true"},
        )


def test_conflictul_de_data_se_confirma_cu_da(auth_client, user):
    draft = schita_cu_conflict(user)
    assert "data_in_conflict" in draft.payload["ambiguity"]

    raspunde(auth_client, draft, "Da.")

    draft.refresh_from_db()
    assert draft.payload["date"] == "2026-09-04"
    assert draft.status == IntentDraft.Status.DRAFT


def test_conflictul_de_data_se_goleste_cu_nu(auth_client, user):
    draft = schita_cu_conflict(user)
    raspunde(auth_client, draft, "Nu.")

    draft.refresh_from_db()
    assert draft.payload["date"] is None
    assert draft.payload["person"] == "Maria"


def test_o_data_rostita_inlocuieste_valoarea_din_conflict(auth_client, user):
    draft = schita_cu_conflict(user)
    raspunde(auth_client, draft, "Pe 5 septembrie.")

    draft.refresh_from_db()
    assert draft.payload["date"] == "2026-09-05"


def test_shimul_httpx_ramane_compatibil_cu_ambele_versiuni():
    """`openai>=1.50,<4` acopera si `httpx`, si `httpx2`. Testul le accepta pe amandoua."""
    sursa = Path(settings.BASE_DIR, "apps/assistant/tests/test_openai_providers.py")
    text = sursa.read_text(encoding="utf-8")

    assert "import httpx2 as httpx" in text
    assert "except ImportError" in text


def test_dockerfile_are_un_cmd_json_valid():
    """Un „\\n" literal in lista JSON facea imaginea imposibil de pornit."""
    linii = Path(settings.BASE_DIR, "Dockerfile").read_text(encoding="utf-8").splitlines()
    cmd = [linie for linie in linii if linie.startswith("CMD ")]

    assert len(cmd) == 1, "Dockerfile trebuie să aibă exact o instrucțiune CMD"
    argv = json.loads(cmd[0][len("CMD ") :])
    assert argv[0] == "gunicorn"
    assert "config.wsgi:application" in argv


def test_dockerfile_nu_are_instructiuni_rupte():
    """Fiecare instructiune incepe cu o directiva Docker sau continua linia dinainte."""
    directive = {
        "FROM", "RUN", "CMD", "COPY", "ADD", "ENV", "EXPOSE", "WORKDIR",
        "ENTRYPOINT", "ARG", "LABEL", "USER", "VOLUME", "HEALTHCHECK",
    }
    continuare = False
    for linie in Path(settings.BASE_DIR, "Dockerfile").read_text(encoding="utf-8").splitlines():
        curatat = linie.strip()
        if not curatat or curatat.startswith("#"):
            continue
        if not continuare:
            assert curatat.split()[0] in directive, f"instrucțiune necunoscută: {linie}"
        continuare = curatat.endswith(chr(92))


def test_ora_ambigua_ramane_ambigua_fara_am_pm():
    from apps.assistant import ro_time

    assert "ora_ambigua" in ro_time.extract("la trei", now=ACUM).reasons
    assert ro_time.extract("la 3 PM", now=ACUM).at_time == time(15, 0)
