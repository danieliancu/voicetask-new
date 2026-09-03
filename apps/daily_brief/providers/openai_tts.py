"""Sinteza vocala prin OpenAI."""

from __future__ import annotations

import time

from django.conf import settings

from apps.core.providers.base import (
    ProviderError,
    ProviderTimeout,
    ProviderUnavailable,
    SpeechResult,
    TextToSpeechProvider,
)
from apps.core.providers.instrumentation import timed, with_retries

MAX_CHARS = 4000


class OpenAITTSProvider(TextToSpeechProvider):
    name = "openai-tts"

    def _client(self):
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover
            raise ProviderUnavailable("Pachetul openai nu este instalat.") from exc
        if not settings.OPENAI_API_KEY:
            raise ProviderUnavailable("OPENAI_API_KEY nu este configurată.")
        return OpenAI(
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL,
            timeout=settings.PROVIDER_TIMEOUT_SECONDS,
            max_retries=0,
        )

    def is_available(self) -> bool:
        return bool(settings.OPENAI_API_KEY)

    def synthesize(self, text: str, *, voice: str | None = None) -> SpeechResult:
        client = self._client()
        selected_voice = voice or settings.OPENAI_TTS_VOICE
        payload = (text or "")[:MAX_CHARS]
        started = time.monotonic()

        def call():
            import openai

            try:
                response = client.audio.speech.create(
                    model=settings.OPENAI_MODEL_TTS,
                    voice=selected_voice,
                    input=payload,
                    response_format="mp3",
                )
                return response.read()
            except openai.APITimeoutError as exc:
                raise ProviderTimeout(str(exc)) from exc
            except openai.APIError as exc:
                raise ProviderError(str(exc)) from exc

        with timed(self.name, "synthesize"):
            audio = with_retries(
                call, attempts=settings.PROVIDER_MAX_RETRIES + 1, retry_on=(ProviderTimeout,)
            )

        return SpeechResult(
            audio=audio,
            content_type="audio/mpeg",
            extension="mp3",
            duration_ms=int((time.monotonic() - started) * 1000),
            voice=selected_voice,
            provider=self.name,
        )
