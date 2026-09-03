"""OCR alternativ cu EasyOCR.

Nu este instalat implicit (aduce PyTorch, ~3 GB). Se activeaza cu:

    pip install easyocr
    PROVIDER_OCR=apps.documents.providers.easy_ocr.EasyOCRProvider

Modelul latin al EasyOCR ("ro") recunoaste diacriticele romanesti sensibil mai
bine decat RapidOCR, cu pretul unei instalari mult mai grele.
"""

from __future__ import annotations

import threading
import time

from django.conf import settings

from apps.core.providers.base import (
    OCRLine,
    OCRProvider,
    OCRResult,
    ProviderError,
    ProviderUnavailable,
)
from apps.core.providers.instrumentation import timed

_reader = None
_lock = threading.Lock()


def _get_reader(languages: list[str]):
    global _reader
    if _reader is None:
        with _lock:
            if _reader is None:
                try:
                    import easyocr
                except ImportError as exc:
                    raise ProviderUnavailable("easyocr nu este instalat pe acest server.") from exc
                _reader = easyocr.Reader(languages, gpu=False, verbose=False)
    return _reader


class EasyOCRProvider(OCRProvider):
    name = "easyocr"

    def is_available(self) -> bool:
        try:
            import easyocr  # noqa: F401
        except ImportError:
            return False
        return True

    def recognize(self, image_bytes: bytes, *, languages: list[str] | None = None) -> OCRResult:
        import cv2
        import numpy as np

        langs = languages or settings.OCR_LANGUAGES or ["ro", "en"]
        reader = _get_reader(langs)
        buffer = np.frombuffer(image_bytes, dtype=np.uint8)
        image = cv2.imdecode(buffer, cv2.IMREAD_COLOR)
        if image is None:
            raise ProviderError("Imaginea nu a putut fi decodată.")

        started = time.monotonic()
        with timed(self.name, "recognize"):
            detections = reader.readtext(image)

        lines: list[OCRLine] = []
        for box, text, score in detections:
            xs = [int(point[0]) for point in box]
            ys = [int(point[1]) for point in box]
            lines.append(
                OCRLine(
                    text=str(text),
                    confidence=float(score),
                    box=(min(xs), min(ys), max(xs), max(ys)),
                )
            )
        lines.sort(
            key=lambda line: (line.box[1] if line.box else 0, line.box[0] if line.box else 0)
        )
        text = "\n".join(line.text for line in lines)
        mean = sum(line.confidence for line in lines) / len(lines) if lines else 0.0
        return OCRResult(
            text=text,
            lines=lines,
            mean_confidence=round(mean, 3),
            provider=self.name,
            duration_ms=int((time.monotonic() - started) * 1000),
        )
