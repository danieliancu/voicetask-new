"""Rezolvarea providerilor din setari."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from functools import cache

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils.module_loading import import_string

from apps.core.providers.base import (
    CalendarProvider,
    GmailProvider,
    IntentParserProvider,
    NotificationProvider,
    OCRProvider,
    TextToSpeechProvider,
    TranscriptionProvider,
)

logger = logging.getLogger("voicetask.providers")

KIND_TO_INTERFACE = {
    "transcription": TranscriptionProvider,
    "intent": IntentParserProvider,
    "ocr": OCRProvider,
    "tts": TextToSpeechProvider,
    "gmail": GmailProvider,
    "calendar": CalendarProvider,
    "notification": NotificationProvider,
}

#: Providerii care consuma un serviciu AI platit si care se dezactiveaza cu AI_ENABLED=False.
AI_KINDS = frozenset({"transcription", "intent", "tts"})

_overrides: dict[str, object] = {}


@cache
def _instantiate(dotted_path: str):
    return import_string(dotted_path)()


def resolve_path(kind: str) -> str:
    """Calea configurata pentru acest tip de provider, tinand cont de AI_ENABLED."""
    try:
        dotted = settings.PROVIDERS[kind]
    except KeyError as exc:
        raise ImproperlyConfigured(f"Nu există un provider configurat pentru '{kind}'.") from exc
    if kind in AI_KINDS and not settings.AI_ENABLED:
        return settings.PROVIDERS_OFFLINE.get(kind, dotted)
    return dotted


def get_offline_provider(kind: str):
    """Providerul local pentru acest tip, indiferent de configuratie.

    Folosit ca rezerva atunci cand serviciul extern esueaza. Ramane configurabil
    prin `PROVIDERS_OFFLINE`, deci nu se cablează o clasa anume in cod.
    """
    dotted = settings.PROVIDERS_OFFLINE.get(kind)
    if dotted is None:
        raise ImproperlyConfigured(f"Nu există un provider offline pentru '{kind}'.")
    return _instantiate(dotted)


def get_provider(kind: str):
    if kind in _overrides:
        return _overrides[kind]
    interface = KIND_TO_INTERFACE.get(kind)
    if interface is None:
        raise ImproperlyConfigured(f"Tip de provider necunoscut: '{kind}'.")
    dotted = resolve_path(kind)
    provider = _instantiate(dotted)
    if not isinstance(provider, interface):
        raise ImproperlyConfigured(f"{dotted} nu implementează {interface.__name__}.")
    return provider


@contextmanager
def override_provider(kind: str, provider):
    """Inlocuieste temporar un provider. Folosit in teste."""
    if isinstance(provider, str):
        provider = import_string(provider)()
    previous = _overrides.get(kind, ...)
    _overrides[kind] = provider
    try:
        yield provider
    finally:
        if previous is ...:
            _overrides.pop(kind, None)
        else:
            _overrides[kind] = previous


def clear_provider_cache() -> None:
    _instantiate.cache_clear()
    _overrides.clear()
