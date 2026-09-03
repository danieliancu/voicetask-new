"""Sinteza vocala demonstrativa.

Genereaza un fisier WAV valid, cu durata proportionala cu lungimea textului, ca
playerul din interfata (play/pause/progres) sa fie complet functional fara nicio
cheie API. Nu pretinde ca ar fi voce reala: interfata marcheaza sursa audio.
"""

from __future__ import annotations

import io
import math
import struct
import wave

from apps.core.providers.base import SpeechResult, TextToSpeechProvider

SAMPLE_RATE = 8000
WORDS_PER_MINUTE = 150


class MockTTSProvider(TextToSpeechProvider):
    name = "tts-demo"
    is_mock = True

    def synthesize(self, text: str, *, voice: str | None = None) -> SpeechResult:
        words = max(1, len((text or "").split()))
        duration_s = min(180.0, max(2.0, words / WORDS_PER_MINUTE * 60))
        frames = int(duration_s * SAMPLE_RATE)

        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(SAMPLE_RATE)
            # Ton foarte slab, doar ca fisierul sa fie audibil ca semnal, nu tacere.
            samples = bytearray()
            for index in range(frames):
                value = int(1200 * math.sin(2 * math.pi * 220 * index / SAMPLE_RATE))
                envelope = 0.15 if (index // SAMPLE_RATE) % 2 == 0 else 0.05
                samples += struct.pack("<h", int(value * envelope))
            handle.writeframes(bytes(samples))

        return SpeechResult(
            audio=buffer.getvalue(),
            content_type="audio/wav",
            extension="wav",
            duration_ms=int(duration_s * 1000),
            voice=voice or "demo",
            provider=self.name,
        )
