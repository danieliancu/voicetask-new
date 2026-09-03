"""Masurarea si logarea apelurilor catre provideri, fara a scrie continut in loguri."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from contextlib import contextmanager

from apps.core.providers.base import ProviderError, ProviderTimeout

logger = logging.getLogger("voicetask.providers")


@contextmanager
def timed(provider_name: str, operation: str):
    """Logheaza durata si rezultatul. Niciodata payloadul."""
    started = time.monotonic()
    try:
        yield
    except ProviderError as exc:
        logger.warning(
            "provider=%s op=%s status=error type=%s durata_ms=%d",
            provider_name,
            operation,
            type(exc).__name__,
            int((time.monotonic() - started) * 1000),
        )
        raise
    else:
        logger.info(
            "provider=%s op=%s status=ok durata_ms=%d",
            provider_name,
            operation,
            int((time.monotonic() - started) * 1000),
        )


def with_retries(func: Callable, *, attempts: int, retry_on: tuple[type[Exception], ...]):
    """Reincearca de `attempts` ori, cu asteptare crescatoare. Fara jitter: e suficient."""
    last: Exception | None = None
    for attempt in range(max(1, attempts)):
        try:
            return func()
        except retry_on as exc:
            last = exc
            if attempt + 1 < attempts:
                time.sleep(0.4 * (2**attempt))
    raise last if last is not None else ProviderTimeout("Serviciul nu a răspuns.")
