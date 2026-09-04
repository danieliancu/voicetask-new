"""Fluxul intreg, prin HTTP: voce sau text → schiță → clarificare → obiect salvat.

Testele de mai sus verifica fiecare strat separat. Aici se verifica lantul, exact
prin adresele pe care le apeleaza interfata, ca o regresie intr-o vedere sa nu
treaca neobservata doar pentru ca modulele sunt corecte luate una cate una.
"""

from __future__ import annotations

import pytest
import time_machine
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.assistant.models import IntentDraft, VoiceCapture
from apps.assistant.schemas import Intent
from apps.assistant.tests._stubs import ACUM, MAINE, ModelSimulat, TranscriereSimulata
from apps.core.providers.registry import override_provider
from apps.notes.models import Note
from apps.scheduling.models import Appointment, Reminder

pytestmark = pytest.mark.django_db

COMANDA = "Mă întâlnesc mâine cu Ion."

MODEL_FARA_DATA = {
    "intent": Intent.CREATE_APPOINTMENT,
    "confidence": 0.9,
    "date": None,
    "start_time": None,
    "person": "Ion",
    "title": "Întâlnire cu Ion",
}


def test_comanda_scrisa_produce_schita_cu_data_completata(auth_client):
    with (
        time_machine.travel(ACUM, tick=False),
        override_provider("intent", ModelSimulat(**MODEL_FARA_DATA)),
    ):
        response = auth_client.post(
            reverse("assistant:text_command"), {"text": COMANDA}, headers={"HX-Request": "true"}
        )

    assert response.status_code == 200
    draft = IntentDraft.objects.get()
    assert draft.payload["date"] == MAINE
    assert draft.payload["person"] == "Ion"
    assert draft.status == IntentDraft.Status.NEEDS_CLARIFICATION
    assert "La ce oră este întâlnirea?" in response.content.decode()
    assert Appointment.objects.count() == 0


def test_lantul_complet_de_la_inregistrare_la_programare(auth_client, sample_audio):
    """transcriere → model simulat → reconciliere → clarificare → confirmare."""
    audio = SimpleUploadedFile("comanda.wav", sample_audio(), content_type="audio/wav")

    with (
        time_machine.travel(ACUM, tick=False),
        override_provider("transcription", TranscriereSimulata(COMANDA)),
        override_provider("intent", ModelSimulat(**MODEL_FARA_DATA)),
    ):
        upload = auth_client.post(reverse("assistant:voice_upload"), {"audio": audio})
        assert upload.status_code == 201

        draft = IntentDraft.objects.get()
        assert draft.capture is not None
        assert draft.capture.status == VoiceCapture.Status.READY
        assert draft.source_text == COMANDA
        assert draft.payload["date"] == MAINE
        assert draft.status == IntentDraft.Status.NEEDS_CLARIFICATION

        # Nimic nu exista inca in aplicatie.
        assert Appointment.objects.count() == 0
        assert Reminder.objects.count() == 0
        assert Note.objects.count() == 0

        auth_client.post(
            reverse("assistant:draft_clarify", args=[draft.uid]),
            {"raspuns": "La trei după-amiaza."},
            headers={"HX-Request": "true"},
        )
        draft.refresh_from_db()
        assert draft.status == IntentDraft.Status.DRAFT
        assert draft.payload["start_time"] == "15:00:00"

        confirm = auth_client.post(
            reverse("assistant:draft_confirm", args=[draft.uid]),
            {
                "intent": Intent.CREATE_APPOINTMENT,
                "title": "Întâlnire cu Ion",
                "date": MAINE,
                "start_time": "15:00",
                "person": "Ion",
            },
            headers={"HX-Request": "true"},
        )

    assert confirm.status_code == 204
    appointment = Appointment.objects.get()
    assert appointment.title == "Întâlnire cu Ion"
    assert appointment.starts_at.astimezone(ACUM.tzinfo).strftime("%Y-%m-%d %H:%M") == (
        f"{MAINE} 15:00"
    )


def test_confirmarea_fara_ora_este_respinsa_de_formular(auth_client):
    """Chiar cu schita deblocata, serverul nu primeste o programare fara ora."""
    with (
        time_machine.travel(ACUM, tick=False),
        override_provider("intent", ModelSimulat(**MODEL_FARA_DATA)),
    ):
        auth_client.post(reverse("assistant:text_command"), {"text": COMANDA})
        draft = IntentDraft.objects.get()
        draft.status = IntentDraft.Status.DRAFT
        draft.save(update_fields=["status"])

        response = auth_client.post(
            reverse("assistant:draft_confirm", args=[draft.uid]),
            {"intent": Intent.CREATE_APPOINTMENT, "title": "Întâlnire cu Ion", "date": MAINE},
            headers={"HX-Request": "true"},
        )

    assert response.status_code == 400
    assert Appointment.objects.count() == 0


def test_transcrierea_ramane_pe_ecranul_de_confirmare(auth_client):
    with (
        time_machine.travel(ACUM, tick=False),
        override_provider("intent", ModelSimulat(**MODEL_FARA_DATA)),
    ):
        auth_client.post(reverse("assistant:text_command"), {"text": COMANDA})
        draft = IntentDraft.objects.get()
        response = auth_client.get(reverse("assistant:draft", args=[draft.uid]))

    assert COMANDA in response.content.decode()


@pytest.mark.parametrize("incredere,afisat", [(0.9, "90%"), (0.45, "45%"), (1.0, "100%")])
def test_increderea_este_afisata_ca_procent(auth_client, incredere, afisat):
    """`floatformat:0` urmat de „0%" transforma 0.85 in „10%": procentul se calculeaza."""
    model = ModelSimulat(**{**MODEL_FARA_DATA, "confidence": incredere})
    with time_machine.travel(ACUM, tick=False), override_provider("intent", model):
        auth_client.post(reverse("assistant:text_command"), {"text": COMANDA})
        draft = IntentDraft.objects.get()
        response = auth_client.get(reverse("assistant:draft", args=[draft.uid]))

    assert f"Încredere {afisat}" in response.content.decode()
