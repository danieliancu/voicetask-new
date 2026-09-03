"""Interfetele providerilor externi.

Nicio implementare concreta aici: doar contractele, structurile de rezultat si
ierarhia de exceptii. Implementarile reale si cele mock stau in aplicatia care
detine domeniul (documents, assistant, integrations, ...).
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

# --------------------------------------------------------------------------- erori


class ProviderError(Exception):
    """Eroare recuperabila dintr-un provider extern."""

    user_message = "Serviciul nu a putut fi contactat. Încearcă din nou."


class ProviderUnavailable(ProviderError):
    """Providerul nu este configurat sau dependenta lipseste."""

    user_message = "Serviciul nu este configurat pe acest server."


class ProviderTimeout(ProviderError):
    user_message = "Serviciul nu a răspuns la timp. Încearcă din nou."


class ProviderInvalidResponse(ProviderError):
    user_message = "Răspunsul serviciului nu a putut fi interpretat."


class ProviderAuthError(ProviderError):
    user_message = "Autorizarea a expirat. Reconectează contul."


# --------------------------------------------------------------------------- rezultate


@dataclass(frozen=True)
class TranscriptionResult:
    text: str
    language: str = "ro"
    confidence: float = 1.0
    duration_ms: int = 0
    provider: str = ""


@dataclass(frozen=True)
class OCRLine:
    text: str
    confidence: float
    box: tuple[int, int, int, int] | None = None


@dataclass(frozen=True)
class OCRResult:
    text: str
    lines: list[OCRLine] = field(default_factory=list)
    mean_confidence: float = 0.0
    provider: str = ""
    duration_ms: int = 0


def group_into_lines(lines: list[OCRLine]) -> list[OCRLine]:
    """Uneste casetele aflate pe acelasi rand, separate prin spatiu.

    Motoarele de detectie returneaza casete separate pentru coloane sau pentru
    fragmente de rand. Fara gruparea lor, un tabel ajunge un rand pe celula, iar
    etichetele de tipul „TOTAL DE PLATĂ  84,20 lei" nu mai stau impreuna.
    """
    with_box = [line for line in lines if line.box]
    if len(with_box) < 2:
        return lines

    heights = sorted(line.box[3] - line.box[1] for line in with_box)
    tolerance = max(6, heights[len(heights) // 2] * 0.6)

    with_box.sort(key=lambda line: ((line.box[1] + line.box[3]) / 2, line.box[0]))
    grouped: list[list[OCRLine]] = []
    for line in with_box:
        center = (line.box[1] + line.box[3]) / 2
        if grouped:
            previous = grouped[-1][-1]
            previous_center = (previous.box[1] + previous.box[3]) / 2
            if abs(center - previous_center) <= tolerance:
                grouped[-1].append(line)
                continue
        grouped.append([line])

    merged: list[OCRLine] = []
    for group in grouped:
        group.sort(key=lambda line: line.box[0])
        text = " ".join(line.text.strip() for line in group if line.text.strip())
        if not text:
            continue
        merged.append(
            OCRLine(
                text=text,
                confidence=sum(line.confidence for line in group) / len(group),
                box=(
                    min(line.box[0] for line in group),
                    min(line.box[1] for line in group),
                    max(line.box[2] for line in group),
                    max(line.box[3] for line in group),
                ),
            )
        )
    return merged


@dataclass(frozen=True)
class SpeechResult:
    audio: bytes
    content_type: str = "audio/wav"
    extension: str = "wav"
    duration_ms: int = 0
    voice: str = ""
    provider: str = ""


@dataclass(frozen=True)
class EmailMeta:
    """Doar metadatele necesare. Corpul emailului nu se stocheaza."""

    message_id: str
    sender: str
    subject: str
    snippet: str
    received_at: datetime
    thread_id: str = ""
    labels: tuple[str, ...] = ()
    needs_follow_up: bool = False


@dataclass(frozen=True)
class MessagePage:
    items: list[EmailMeta]
    next_cursor: str | None = None


@dataclass(frozen=True)
class ExternalEvent:
    external_id: str
    title: str
    starts_at: datetime
    ends_at: datetime | None = None
    location: str = ""
    description: str = ""
    updated_at: datetime | None = None


@dataclass(frozen=True)
class PushResult:
    delivered: bool
    detail: str = ""


# --------------------------------------------------------------------------- interfete


class BaseProvider:
    """Contract comun: fiecare provider stie sa spuna daca este utilizabil.

    Nu este `abc.ABC`: metodele abstracte apar in subclasele specializate, iar
    aceasta clasa doar aduna comportamentul comun.
    """

    name: str = "base"
    is_mock: bool = False

    def is_available(self) -> bool:
        return True

    def describe(self) -> dict[str, Any]:
        return {"name": self.name, "mock": self.is_mock, "available": self.is_available()}


class TranscriptionProvider(BaseProvider):
    @abc.abstractmethod
    def transcribe(
        self, audio: bytes, *, content_type: str, language: str = "ro"
    ) -> TranscriptionResult:
        """Transforma audio in text. Ridica ProviderError la esec."""


class IntentParserProvider(BaseProvider):
    @abc.abstractmethod
    def parse(self, text: str, *, context: IntentContext) -> dict[str, Any]:
        """Returneaza un dict brut, validat ulterior de schema Pydantic."""


class OCRProvider(BaseProvider):
    @abc.abstractmethod
    def recognize(self, image_bytes: bytes, *, languages: list[str] | None = None) -> OCRResult:
        """Extrage text dintr-o imagine deja preprocesata."""


class TextToSpeechProvider(BaseProvider):
    @abc.abstractmethod
    def synthesize(self, text: str, *, voice: str | None = None) -> SpeechResult:
        """Transforma text in audio."""


class GmailProvider(BaseProvider):
    @abc.abstractmethod
    def list_messages(
        self, account, *, query: str = "", cursor: str | None = None, limit: int = 25
    ) -> MessagePage:
        """Listeaza metadate de mesaje pentru contul dat."""

    @abc.abstractmethod
    def search(self, account, query: str, *, limit: int = 25) -> MessagePage:
        """Cauta in mesaje."""

    def supports_snippets(self) -> bool:
        """Scope-ul `metadata` nu returneaza snippet-uri."""
        return True


class CalendarProvider(BaseProvider):
    @abc.abstractmethod
    def list_events(self, account, *, start: datetime, end: datetime) -> list[ExternalEvent]:
        ...

    @abc.abstractmethod
    def create_event(self, account, *, appointment) -> ExternalEvent:
        """Se apeleaza numai dupa confirmarea explicita a utilizatorului."""

    @abc.abstractmethod
    def update_event(self, account, *, appointment) -> ExternalEvent:
        ...

    @abc.abstractmethod
    def delete_event(self, account, *, external_id: str) -> None:
        ...


class NotificationProvider(BaseProvider):
    @abc.abstractmethod
    def send(self, subscription, *, title: str, body: str, url: str, dedup_key: str) -> PushResult:
        ...

    def supports_push(self) -> bool:
        """False cand nu exista chei VAPID: interfata nu trebuie sa minta."""
        return False


# Importat aici la final ca sa evitam un import circular in adnotari.
from apps.core.providers.context import IntentContext  # noqa: E402  isort:skip

__all__ = [
    "BaseProvider",
    "CalendarProvider",
    "EmailMeta",
    "ExternalEvent",
    "GmailProvider",
    "IntentContext",
    "IntentParserProvider",
    "MessagePage",
    "NotificationProvider",
    "OCRLine",
    "OCRProvider",
    "OCRResult",
    "ProviderAuthError",
    "ProviderError",
    "ProviderInvalidResponse",
    "ProviderTimeout",
    "ProviderUnavailable",
    "PushResult",
    "SpeechResult",
    "TextToSpeechProvider",
    "TranscriptionProvider",
    "TranscriptionResult",
    "group_into_lines",
]
