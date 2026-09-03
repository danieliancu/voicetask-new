"""OCR demonstrativ.

Returneaza textul unei facturi de energie romanesti, ca fluxul complet
(preprocesare → extractie → formular editabil) sa poata fi parcurs si testat
fara motorul real. Rezultatul este marcat `is_mock`, iar interfata afiseaza
explicit ca datele sunt demonstrative.
"""

from __future__ import annotations

import hashlib

from apps.core.providers.base import OCRLine, OCRProvider, OCRResult

INVOICE_TEXT = """energio energie pentru tine
FACTURA ENERGIE ELECTRICA
Seria EL 12345678
Date client
Popescu Andrei
Str. Exemplului nr. 10, bl. B1, ap. 12
400123 Cluj-Napoca, Cluj
CUI: RO12345678
Perioada de facturare 01.08.2026 - 31.08.2026
Data emiterii 01.09.2026
DATA LIMITA DE PLATA
06.09.2026
TOTAL DE PLATA
84,20 lei
TVA inclus
DETALII FACTURA
Energie activa 64,20 lei
Tarif de distributie 12,30 lei
Accize 1,20 lei
TVA (19%) 6,50 lei
TOTAL DE PLATA 84,20 lei
DATE CONTRACT
Cod loc de consum RO 123 456 789
Tip contract Casnic
Putere contractata 3,45 kW"""

INVITATION_TEXT = """INVITATIE
Va invitam la serbarea scolara de sfarsit de an
Scoala Nr. 12, Sala festiva
Sambata, 14 septembrie 2026, ora 10:00
Va asteptam cu drag!"""


class MockOCRProvider(OCRProvider):
    name = "ocr-demo"
    is_mock = True

    def recognize(self, image_bytes: bytes, *, languages: list[str] | None = None) -> OCRResult:
        digest = hashlib.sha256(image_bytes or b"").digest()
        text = INVOICE_TEXT if digest[0] % 2 == 0 else INVITATION_TEXT
        lines = [
            OCRLine(text=line, confidence=0.82 if line.isupper() else 0.9)
            for line in text.splitlines()
            if line.strip()
        ]
        mean = sum(line.confidence for line in lines) / len(lines) if lines else 0.0
        return OCRResult(
            text=text,
            lines=lines,
            mean_confidence=round(mean, 3),
            provider=self.name,
            duration_ms=12,
        )
