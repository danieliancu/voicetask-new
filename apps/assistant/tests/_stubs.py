"""Unelte comune testelor de reconciliere: un model AI simulat si timp fixat.

Nu este un fisier de teste (`test_*.py`), deci pytest nu il colecteaza.
"""

from __future__ import annotations

import zoneinfo
from datetime import datetime

from apps.core.providers.base import (
    IntentParserProvider,
    TranscriptionProvider,
    TranscriptionResult,
)

#: Marți, 1 septembrie 2026, 08:00 la Bucuresti — aceeasi referinta ca in
#: `test_ro_dates.py`, ca datele asteptate sa se poata citi dintr-o privire.
BUCURESTI = zoneinfo.ZoneInfo("Europe/Bucharest")
ACUM = datetime(2026, 9, 1, 8, 0, tzinfo=BUCURESTI)

MAINE = "2026-09-02"
POIMAINE = "2026-09-03"


class ModelSimulat(IntentParserProvider):
    """Provider de intentii care returneaza exact raspunsul dictat de test.

    Inlocuieste OpenAI ca sa putem descrie precis cazurile care conteaza: modelul
    da data corecta, o omite, sau da alta decat parserul determinist.
    """

    name = "model-simulat"

    def __init__(self, payload: dict | None = None, **campuri):
        self.payload = {**(payload or {}), **campuri}
        self.texts: list[str] = []

    def parse(self, text: str, *, context) -> dict:
        self.texts.append(text)
        return dict(self.payload)


class TranscriereSimulata(TranscriptionProvider):
    """Whisper simulat: intoarce exact fraza pe care testul vrea sa o auda."""

    name = "transcriere-simulata"

    def __init__(self, text: str):
        self.text = text

    def transcribe(self, audio: bytes, *, content_type: str, language: str = "ro"):
        return TranscriptionResult(text=self.text, provider=self.name, duration_ms=1200)
