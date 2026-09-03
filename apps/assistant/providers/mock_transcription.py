"""Transcriere demonstrativa, folosita cand nu exista o cheie OpenAI.

Nu inventeaza continut care sa fie confundat cu unul real: rezultatul este marcat
explicit ca demonstrativ in interfata, iar textul provine dintr-o listă fixă,
aleasă determinist din amprenta înregistrării, ca aceeași înregistrare să dea
mereu aceeași transcriere.
"""

from __future__ import annotations

import hashlib

from apps.core.providers.base import TranscriptionProvider, TranscriptionResult

DEMO_PHRASES: tuple[str, ...] = (
    "Notează că trebuie să cumpăr lapte, ouă și pâine integrală",
    "Programează o întâlnire mâine la 10 cu titlul Întâlnire proiect Alpha la Google Meet",
    "Pune-mi o alarmă vineri la 9 pentru controlul medical la Clinica MedLife",
    "Urmărește emailul de la Ana Popescu mâine la 14",
    "Caută factura de energie",
    "Notează idei pentru campania de vară",
)


class MockTranscriptionProvider(TranscriptionProvider):
    name = "transcriere-demo"
    is_mock = True

    def transcribe(
        self, audio: bytes, *, content_type: str, language: str = "ro"
    ) -> TranscriptionResult:
        digest = hashlib.sha256(audio or b"").digest()
        phrase = DEMO_PHRASES[digest[0] % len(DEMO_PHRASES)]
        return TranscriptionResult(
            text=phrase,
            language=language,
            confidence=0.75,
            duration_ms=len(audio) // 32 if audio else 0,
            provider=self.name,
        )
