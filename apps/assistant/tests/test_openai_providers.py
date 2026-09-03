"""Calea reala OpenAI: selectia providerilor, erorile si rezerva determinista.

Toate raspunsurile OpenAI sunt simulate. `conftest.py` blocheaza reteaua, deci
niciun test nu consuma credit si niciunul nu depinde de internet.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import httpx2
import openai
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone

from apps.assistant import services
from apps.assistant.models import IntentDraft, VoiceCapture
from apps.assistant.providers.openai_intent import OpenAIIntentParser
from apps.assistant.providers.openai_transcription import OpenAITranscriptionProvider
from apps.assistant.providers.rule_based import RuleBasedIntentParser
from apps.assistant.schemas import Intent
from apps.core.providers.base import (
    IntentParserProvider,
    ProviderError,
    ProviderInvalidResponse,
    ProviderTimeout,
    ProviderUnavailable,
    TranscriptionProvider,
    TranscriptionResult,
)
from apps.core.providers.context import IntentContext
from apps.core.providers.registry import clear_provider_cache, get_provider, override_provider
from apps.notes.models import Note

OPENAI_TRANSCRIPTION = "apps.assistant.providers.openai_transcription.OpenAITranscriptionProvider"
OPENAI_INTENT = "apps.assistant.providers.openai_intent.OpenAIIntentParser"


# --------------------------------------------------------------------- ajutoare


def _client_fals(atribut: str, apel):
    """Un client OpenAI fals, cu o singura metoda utila."""
    if atribut == "transcriere":
        return SimpleNamespace(
            audio=SimpleNamespace(transcriptions=SimpleNamespace(create=apel))
        )
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=apel)))


def _returneaza(valoare):
    def _apel(*_args, **_kwargs):
        return valoare

    return _apel


def _ridica(exceptie):
    def _apel(*_args, **_kwargs):
        raise exceptie

    return _apel


def _eroare_de_stare(cls: type, status: int) -> Exception:
    """Erorile de stare din SDK au nevoie de un raspuns HTTP real."""
    cerere = httpx2.Request("POST", "https://api.openai.com/v1/chat/completions")
    return cls("eroare simulata", response=httpx2.Response(status, request=cerere), body=None)


def _mesaj(continut: str):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=continut))])


def _context() -> IntentContext:
    return IntentContext(now=timezone.localtime())


def _fisier_audio(sample_audio):
    return SimpleUploadedFile("comanda.wav", sample_audio(0.5), content_type="audio/wav")


class ParserCareEsueaza(IntentParserProvider):
    name = "esuat"

    def __init__(self, exceptie: Exception | None = None):
        self.exceptie = exceptie or ProviderError("serviciul nu raspunde")

    def parse(self, text, *, context):
        raise self.exceptie


class ParserCuRaspunsInvalid(IntentParserProvider):
    """Trece de `json.loads`, dar pica la validarea Pydantic."""

    name = "invalid"

    def parse(self, text, *, context):
        return {"intent": "create_note", "camp_inventat": "x"}


class TranscriereCareEsueaza(TranscriptionProvider):
    name = "transcriere-esuata"

    def transcribe(self, audio, *, content_type, language="ro"):
        raise ProviderError("serviciul nu raspunde")


class TranscriereGoala(TranscriptionProvider):
    name = "transcriere-goala"

    def transcribe(self, audio, *, content_type, language="ro"):
        return TranscriptionResult(text="   ", confidence=0.9)


class ParserSpion(IntentParserProvider):
    """Semnaleaza daca interpretarea este apelata cand nu ar trebui."""

    name = "spion"

    def __init__(self):
        self.apelat = False

    def parse(self, text, *, context):
        self.apelat = True
        return {"intent": Intent.CREATE_NOTE, "title": "Nu ar trebui", "confidence": 0.9}


@pytest.fixture
def cu_openai(settings):
    settings.AI_ENABLED = True
    settings.OPENAI_API_KEY = "cheie-de-test"
    settings.PROVIDERS = {
        **settings.PROVIDERS,
        "transcription": OPENAI_TRANSCRIPTION,
        "intent": OPENAI_INTENT,
    }
    clear_provider_cache()
    return settings


# ------------------------------------------------------- selectia providerilor


def test_ai_activ_selecteaza_providerii_openai(cu_openai):
    assert isinstance(get_provider("transcription"), OpenAITranscriptionProvider)
    assert isinstance(get_provider("intent"), OpenAIIntentParser)


def test_ai_oprit_selecteaza_providerii_locali(cu_openai):
    cu_openai.AI_ENABLED = False
    clear_provider_cache()

    assert get_provider("transcription").is_mock is True
    assert isinstance(get_provider("intent"), RuleBasedIntentParser)


def test_fara_cheie_providerii_sunt_indisponibili(settings):
    settings.OPENAI_API_KEY = ""

    assert OpenAITranscriptionProvider().is_available() is False
    assert OpenAIIntentParser().is_available() is False


def test_fara_cheie_transcrierea_ridica_provider_unavailable(settings):
    settings.OPENAI_API_KEY = ""

    with pytest.raises(ProviderUnavailable):
        OpenAITranscriptionProvider().transcribe(b"audio", content_type="audio/webm")


# ------------------------------------------------------------------ transcriere


def test_transcriere_reusita(cu_openai):
    provider = OpenAITranscriptionProvider()
    apel = _returneaza(SimpleNamespace(text="  Notează că trebuie să cumpăr lapte.  "))

    with patch.object(provider, "_client", return_value=_client_fals("transcriere", apel)):
        rezultat = provider.transcribe(b"audio", content_type="audio/webm")

    assert rezultat.text == "Notează că trebuie să cumpăr lapte."
    assert rezultat.language == "ro"


def test_eroare_openai_devine_provider_error(cu_openai):
    provider = OpenAITranscriptionProvider()
    apel = _ridica(_eroare_de_stare(openai.InternalServerError, 500))

    with (
        patch.object(provider, "_client", return_value=_client_fals("transcriere", apel)),
        pytest.raises(ProviderError),
    ):
        provider.transcribe(b"audio", content_type="audio/webm")


def test_timeout_devine_provider_timeout_si_se_reincearca(cu_openai):
    cu_openai.PROVIDER_MAX_RETRIES = 2
    provider = OpenAITranscriptionProvider()
    apeluri = {"n": 0}

    def _apel(*_args, **_kwargs):
        apeluri["n"] += 1
        raise openai.APITimeoutError(request=httpx2.Request("POST", "https://api.openai.com/v1"))

    with (
        patch.object(provider, "_client", return_value=_client_fals("transcriere", _apel)),
        pytest.raises(ProviderTimeout),
    ):
        provider.transcribe(b"audio", content_type="audio/webm")

    assert apeluri["n"] == 3


def test_cheie_respinsa_devine_provider_unavailable(cu_openai):
    provider = OpenAITranscriptionProvider()
    apel = _ridica(_eroare_de_stare(openai.AuthenticationError, 401))

    with (
        patch.object(provider, "_client", return_value=_client_fals("transcriere", apel)),
        pytest.raises(ProviderUnavailable),
    ):
        provider.transcribe(b"audio", content_type="audio/webm")


@pytest.mark.django_db
def test_transcrierea_goala_opreste_fluxul(user):
    capture = VoiceCapture.objects.create(owner=user, content_type="audio/webm")
    spion = ParserSpion()

    with (
        override_provider("transcription", TranscriereGoala()),
        override_provider("intent", spion),
    ):
        draft = services.process_capture(capture, b"audio")

    capture.refresh_from_db()
    assert draft is None
    assert capture.status == VoiceCapture.Status.FAILED
    assert capture.transcript == ""
    assert "Nu am auzit nimic" in capture.error
    assert spion.apelat is False


@pytest.mark.django_db
def test_esecul_transcrierii_nu_inventeaza_text(user):
    """Providerul demonstrativ nu trebuie sa acopere un apel real esuat."""
    from apps.assistant.providers.mock_transcription import DEMO_PHRASES

    capture = VoiceCapture.objects.create(owner=user, content_type="audio/webm")
    spion = ParserSpion()

    with (
        override_provider("transcription", TranscriereCareEsueaza()),
        override_provider("intent", spion),
    ):
        draft = services.process_capture(capture, b"audio")

    capture.refresh_from_db()
    assert draft is None
    assert capture.status == VoiceCapture.Status.FAILED
    assert capture.transcript == ""
    assert capture.transcript not in DEMO_PHRASES
    assert spion.apelat is False
    assert IntentDraft.objects.count() == 0


# --------------------------------------------------------------- interpretare


def test_json_valid_este_acceptat(cu_openai):
    parser = OpenAIIntentParser()
    continut = '{"intent": "create_note", "title": "Cumpăr lapte", "confidence": 0.9}'
    apel = _returneaza(_mesaj(continut))

    with patch.object(parser, "_client", return_value=_client_fals("intentie", apel)):
        payload = parser.parse("Notează că trebuie să cumpăr lapte.", context=_context())

    assert payload["intent"] == "create_note"
    assert payload["title"] == "Cumpăr lapte"


def test_json_invalid_este_respins(cu_openai):
    parser = OpenAIIntentParser()
    apel = _returneaza(_mesaj("nu este json"))

    with (
        patch.object(parser, "_client", return_value=_client_fals("intentie", apel)),
        pytest.raises(ProviderInvalidResponse),
    ):
        parser.parse("orice", context=_context())


def test_raspunsul_care_nu_e_obiect_este_respins(cu_openai):
    parser = OpenAIIntentParser()
    apel = _returneaza(_mesaj("[1, 2, 3]"))

    with (
        patch.object(parser, "_client", return_value=_client_fals("intentie", apel)),
        pytest.raises(ProviderInvalidResponse),
    ):
        parser.parse("orice", context=_context())


def test_intentia_nula_devine_necunoscuta(cu_openai):
    parser = OpenAIIntentParser()
    apel = _returneaza(_mesaj('{"intent": null, "confidence": 0.1}'))

    with patch.object(parser, "_client", return_value=_client_fals("intentie", apel)):
        payload = parser.parse("orice", context=_context())

    assert payload["intent"] == Intent.UNKNOWN


# ------------------------------------------------------- rezerva determinista


@pytest.mark.django_db
def test_rezerva_preia_cand_openai_esueaza(user):
    """Interpretarea cade pe parserul local pentru o comanda pe care o intelege."""
    with override_provider("intent", ParserCareEsueaza()):
        draft = services.interpret(user, "Notează că trebuie să cumpăr lapte.")

    assert draft.intent == Intent.CREATE_NOTE
    assert draft.status == IntentDraft.Status.DRAFT
    assert Note.objects.count() == 0


@pytest.mark.django_db
def test_rezerva_preia_si_la_raspuns_invalid(user):
    with override_provider("intent", ParserCuRaspunsInvalid()):
        draft = services.interpret(user, "Notează că trebuie să cumpăr lapte.")

    assert draft.intent == Intent.CREATE_NOTE
    assert draft.status == IntentDraft.Status.DRAFT


@pytest.mark.django_db
def test_rezerva_nu_porneste_la_eroare_de_configurare(user):
    """O cheie lipsa nu trebuie mascata de parserul local."""
    with override_provider("intent", ParserCareEsueaza(ProviderUnavailable("fara cheie"))):
        draft = services.interpret(user, "Notează că trebuie să cumpăr lapte.")

    assert draft.intent == Intent.UNKNOWN
    assert draft.status == IntentDraft.Status.NEEDS_CLARIFICATION


@pytest.mark.django_db
def test_rezerva_nu_decide_stergeri(user, note_factory):
    """„Serviciul a cazut, deci presupun ca voiai sa stergi" nu este acceptabil."""
    note = note_factory(user, title="Lista de cumpărături")

    with override_provider("intent", ParserCareEsueaza()):
        draft = services.interpret(user, f"Șterge notița {note.title}")

    assert draft.intent == Intent.UNKNOWN
    assert draft.status == IntentDraft.Status.NEEDS_CLARIFICATION
    note.refresh_from_db()
    assert note.deleted_at is None


@pytest.mark.django_db
def test_rezerva_fara_decizie_cere_reformulare(user):
    with override_provider("intent", ParserCareEsueaza()):
        draft = services.interpret(user, "aaa bbb ccc")

    assert draft.status == IntentDraft.Status.NEEDS_CLARIFICATION
    assert draft.clarification_question


# ------------------------------------------------------------------- siguranta


@pytest.mark.django_db
def test_comanda_ambigua_nu_inventeaza_data(user):
    """«Programează ceva săptămâna viitoare» trebuie sa ceara lamuriri."""
    draft = services.interpret(user, "Programează ceva săptămâna viitoare.")

    assert draft.status == IntentDraft.Status.NEEDS_CLARIFICATION
    assert draft.payload.get("date") is None


@pytest.mark.django_db
def test_interpretarea_nu_salveaza_nimic(user):
    services.interpret(user, "Notează că trebuie să cumpăr lapte.")

    assert Note.objects.count() == 0


@pytest.mark.django_db
def test_schita_altui_utilizator_da_404(user, other_client):
    draft = services.interpret(user, "Notează că trebuie să cumpăr lapte.")

    raspuns = other_client.get(reverse("assistant:draft", args=[draft.uid]))

    assert raspuns.status_code == 404


@pytest.mark.django_db
def test_limitarea_de_rata_raspunde_json_pentru_fetch(auth_client, settings, sample_audio):
    """`recorder.js` citeste doar JSON: un 429 HTML i-ar ascunde motivul."""
    settings.RATE_LIMITS = {**settings.RATE_LIMITS, "voice": (1, 300)}
    url = reverse("assistant:voice_upload")

    raspunsuri = [
        auth_client.post(
            url,
            {"audio": _fisier_audio(sample_audio)},
            headers={"x-requested-with": "fetch"},
        )
        for _ in range(3)
    ]

    limitate = [r for r in raspunsuri if r.status_code == 429]
    assert limitate, "limitarea de rata nu a pornit"
    assert limitate[0]["Content-Type"].startswith("application/json")
    assert "eroare" in limitate[0].json()


# ------------------------------------------------- regresii gasite la testul live


def test_base_url_gol_nu_ajunge_in_mediu():
    """SDK-ul citeste singur `OPENAI_BASE_URL`; un sir vid ar da un URL invalid.

    `.env.example` livreaza variabila goala, deci fara curatarea din settings
    orice apel OpenAI ar esua cu „Connection error".
    """
    import os

    assert os.environ.get("OPENAI_BASE_URL") != ""


def test_clientul_openai_are_adresa_valida(cu_openai):
    import openai

    client = openai.OpenAI(api_key="x", base_url=cu_openai.OPENAI_BASE_URL)

    assert str(client.base_url).startswith("https://")


@pytest.mark.parametrize(
    "antet",
    [
        b"ID3" + b"XXX",
        bytes.fromhex("fffb") + b"XXXX",
        bytes.fromhex("fffa") + b"XXXX",
        bytes.fromhex("fff3") + b"XXXX",
        bytes.fromhex("fff2") + b"XXXX",
        bytes.fromhex("ffe3") + b"XXXX",
    ],
)
def test_mp3_este_acceptat_indiferent_de_versiunea_cadrului(antet):
    """Antetul difera dupa versiunea MPEG; toate variantele sunt mp3 valide."""
    from apps.core.files import validate_audio_upload

    fisier = SimpleUploadedFile("a.mp3", antet + b"0" * 2048, content_type="audio/mpeg")

    detectat = validate_audio_upload(fisier, max_bytes=10 * 1024 * 1024)

    assert detectat.content_type == "audio/mpeg"
    assert detectat.extension == "mp3"
