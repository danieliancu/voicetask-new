"""Registrul de provideri, verificarile de configurare si limitarea de rata."""

import pytest
from django.core.exceptions import ImproperlyConfigured

from apps.core.providers.base import (
    OCRProvider,
    ProviderError,
    ProviderTimeout,
    TranscriptionProvider,
)
from apps.core.providers.instrumentation import with_retries
from apps.core.providers.registry import (
    KIND_TO_INTERFACE,
    clear_provider_cache,
    get_provider,
    override_provider,
)


@pytest.mark.parametrize("kind", sorted(KIND_TO_INTERFACE))
def test_fiecare_provider_configurat_implementeaza_interfata(kind):
    provider = get_provider(kind)
    assert isinstance(provider, KIND_TO_INTERFACE[kind])


def test_tipul_necunoscut_este_respins():
    with pytest.raises(ImproperlyConfigured):
        get_provider("inexistent")


def test_calea_gresita_este_respinsa(settings):
    settings.PROVIDERS = {**settings.PROVIDERS, "ocr": "apps.inexistent.Provider"}
    clear_provider_cache()
    with pytest.raises(ImportError):
        get_provider("ocr")


def test_clasa_gresita_este_respinsa(settings):
    settings.PROVIDERS = {**settings.PROVIDERS, "ocr": "apps.notes.models.Note"}
    clear_provider_cache()
    with pytest.raises(ImproperlyConfigured):
        get_provider("ocr")


def test_ai_dezactivat_forteaza_providerii_offline(settings):
    settings.AI_ENABLED = False
    settings.PROVIDERS = {
        **settings.PROVIDERS,
        "transcription": (
            "apps.assistant.providers.openai_transcription.OpenAITranscriptionProvider"
        ),
    }
    clear_provider_cache()

    provider = get_provider("transcription")

    assert provider.is_mock is True


def test_override_ul_se_restaureaza():
    class Fals(OCRProvider):
        name = "fals"

        def recognize(self, image_bytes, *, languages=None):
            raise NotImplementedError

    initial = get_provider("ocr")
    with override_provider("ocr", Fals()):
        assert get_provider("ocr").name == "fals"
    assert get_provider("ocr").name == initial.name


def test_verificarea_de_sistem_trece_pe_configuratia_curenta():
    from apps.core.checks import check_providers

    assert check_providers(None) == []


def test_verificarea_de_sistem_semnaleaza_o_cale_gresita(settings):
    from apps.core.checks import check_providers

    settings.PROVIDERS = {**settings.PROVIDERS, "ocr": "apps.inexistent.Provider"}
    clear_provider_cache()

    erori = check_providers(None)

    assert any(eroare.id == "core.E002" for eroare in erori)


def test_reincercarea_se_opreste_dupa_numarul_dat():
    apeluri = {"n": 0}

    def esueaza():
        apeluri["n"] += 1
        raise ProviderTimeout("prea lent")

    with pytest.raises(ProviderTimeout):
        with_retries(esueaza, attempts=2, retry_on=(ProviderTimeout,))

    assert apeluri["n"] == 2


def test_reincercarea_nu_prinde_alte_erori():
    def esueaza():
        raise ProviderError("altceva")

    with pytest.raises(ProviderError):
        with_retries(esueaza, attempts=3, retry_on=(ProviderTimeout,))


def test_providerii_mock_sunt_marcati():
    assert get_provider("ocr").is_mock is True
    assert get_provider("gmail").is_mock is True
    # Parserul pe reguli este o implementare reala, nu un mock.
    assert get_provider("intent").is_mock is False


def test_transcrierea_demo_este_determinista(sample_audio):
    provider = get_provider("transcription")
    assert isinstance(provider, TranscriptionProvider)

    audio = sample_audio()
    primul = provider.transcribe(audio, content_type="audio/wav")
    al_doilea = provider.transcribe(audio, content_type="audio/wav")

    assert primul.text == al_doilea.text
    assert primul.text


def test_providerul_openai_fara_cheie_este_indisponibil(settings):
    from apps.assistant.providers.openai_transcription import OpenAITranscriptionProvider

    settings.OPENAI_API_KEY = ""
    assert OpenAITranscriptionProvider().is_available() is False


@pytest.mark.django_db
def test_limitarea_de_rata_blocheaza_dupa_prag(auth_client, settings):
    from django.urls import reverse

    settings.RATE_LIMITS = {**settings.RATE_LIMITS, "search": (3, 60)}

    coduri = [
        auth_client.get(reverse("search:results"), {"q": "test"}).status_code
        for _ in range(5)
    ]

    assert coduri.count(429) >= 1
