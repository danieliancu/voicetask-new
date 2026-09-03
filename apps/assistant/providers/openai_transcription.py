"""Transcriere prin OpenAI. Importul SDK-ului este lazy, ca aplicatia sa porneasca fara el."""

from __future__ import annotations

import io
import time

from django.conf import settings

from apps.core.providers.base import (
    ProviderError,
    ProviderTimeout,
    ProviderUnavailable,
    TranscriptionProvider,
    TranscriptionResult,
)
from apps.core.providers.instrumentation import timed, with_retries

EXTENSION_FOR = {
    "audio/webm": "webm",
    "audio/ogg": "ogg",
    "audio/mp4": "m4a",
    "audio/wav": "wav",
    "audio/mpeg": "mp3",
    "audio/aac": "aac",
}


class OpenAITranscriptionProvider(TranscriptionProvider):
    name = "openai-transcriere"

    def _client(self):
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - depinde de mediu
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

    def transcribe(
        self, audio: bytes, *, content_type: str, language: str = "ro"
    ) -> TranscriptionResult:
        client = self._client()
        extension = EXTENSION_FOR.get(content_type, "webm")
        started = time.monotonic()

        def call():
            import openai

            stream = io.BytesIO(audio)
            stream.name = f"inregistrare.{extension}"
            try:
                return client.audio.transcriptions.create(
                    model=settings.OPENAI_MODEL_TRANSCRIBE,
                    file=stream,
                    language=language,
                    response_format="json",
                )
            except openai.APITimeoutError as exc:
                raise ProviderTimeout(str(exc)) from exc
            except (openai.AuthenticationError, openai.PermissionDeniedError) as exc:
                raise ProviderUnavailable(str(exc)) from exc
            except openai.APIError as exc:
                raise ProviderError(str(exc)) from exc
            except openai.OpenAIError as exc:
                # `OpenAIError` este radacina: unele erori (lungime, filtru de
                # continut) nu trec prin `APIError` si ar deveni altfel 500.
                raise ProviderError(str(exc)) from exc

        with timed(self.name, "transcribe"):
            response = with_retries(
                call,
                attempts=settings.PROVIDER_MAX_RETRIES + 1,
                retry_on=(ProviderTimeout,),
            )

        return TranscriptionResult(
            text=(getattr(response, "text", "") or "").strip(),
            language=language,
            confidence=0.9,
            duration_ms=int((time.monotonic() - started) * 1000),
            provider=self.name,
        )
