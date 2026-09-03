"""OCR real cu RapidOCR (ONNX Runtime).

Motorul se incarca lenes si o singura data per proces: initializarea citeste
modelele ONNX de pe disc si dureaza cateva sute de milisecunde.

Limitare cunoscuta: modelul de recunoastere nu este antrenat special pe diacritice
romanesti. Textul recunoscut este normalizat inainte de extractie, iar scorurile
mici de incredere sunt propagate in formular ca utilizatorul sa verifice.
"""

from __future__ import annotations

import threading
import time

from apps.core.providers.base import (
    OCRLine,
    OCRProvider,
    OCRResult,
    ProviderError,
    ProviderUnavailable,
)
from apps.core.providers.instrumentation import timed

_engine = None
_lock = threading.Lock()


def _get_engine():
    global _engine
    if _engine is None:
        with _lock:
            if _engine is None:
                try:
                    from rapidocr_onnxruntime import RapidOCR
                except ImportError as exc:
                    raise ProviderUnavailable(
                        "rapidocr-onnxruntime nu este instalat pe acest server."
                    ) from exc
                _engine = RapidOCR()
    return _engine


class RapidOCRProvider(OCRProvider):
    name = "rapidocr"

    def is_available(self) -> bool:
        try:
            import rapidocr_onnxruntime  # noqa: F401
        except ImportError:
            return False
        return True

    def recognize(self, image_bytes: bytes, *, languages: list[str] | None = None) -> OCRResult:
        import cv2
        import numpy as np

        engine = _get_engine()
        buffer = np.frombuffer(image_bytes, dtype=np.uint8)
        image = cv2.imdecode(buffer, cv2.IMREAD_COLOR)
        if image is None:
            raise ProviderError("Imaginea nu a putut fi decodată.")

        started = time.monotonic()
        with timed(self.name, "recognize"):
            result, _ = engine(image)

        lines: list[OCRLine] = []
        for entry in result or []:
            box, text, score = entry[0], entry[1], entry[2]
            xs = [int(point[0]) for point in box]
            ys = [int(point[1]) for point in box]
            lines.append(
                OCRLine(
                    text=str(text),
                    confidence=float(score),
                    box=(min(xs), min(ys), max(xs), max(ys)),
                )
            )

        # Randurile vin in ordinea detectiei; le reasezam de sus in jos, apoi stanga-dreapta.
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
