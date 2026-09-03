"""Rate limiting simplu, pe cache, pentru endpointurile costisitoare (OCR, voce, AI)."""

from __future__ import annotations

import functools
import time

from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse
from django.template.loader import render_to_string


class RateLimited(Exception):
    def __init__(self, retry_after: int):
        self.retry_after = retry_after
        super().__init__("Prea multe cereri.")


def _bucket_key(scope: str, request) -> str:
    if request.user.is_authenticated:
        identity = f"u{request.user.pk}"
    else:
        identity = request.META.get("REMOTE_ADDR", "anon")
    return f"rl:{scope}:{identity}"


def check(scope: str, request) -> None:
    """Fereastra fixa: suficient pentru a opri abuzul, fara dependenta de Redis."""
    limit, window = settings.RATE_LIMITS.get(scope, (60, 60))
    key = _bucket_key(scope, request)
    now = int(time.time())
    window_start = now - (now % window)
    slot = f"{key}:{window_start}"
    try:
        added = cache.add(slot, 1, timeout=window + 5)
        count = 1 if added else cache.incr(slot)
    except ValueError:
        # Cheia a expirat intre `add` si `incr`.
        cache.set(slot, 1, timeout=window + 5)
        count = 1
    if count > limit:
        raise RateLimited(retry_after=window_start + window - now)


def limited(scope: str):
    """Decorator pentru view-uri. Returneaza un fragment HTML 429, nu o pagina de eroare."""

    def decorator(view):
        @functools.wraps(view)
        def wrapper(request, *args, **kwargs):
            try:
                check(scope, request)
            except RateLimited as exc:
                html = render_to_string(
                    "core/_rate_limited.html",
                    {"retry_after": exc.retry_after},
                    request=request,
                )
                response = HttpResponse(html, status=429)
                response["Retry-After"] = str(exc.retry_after)
                return response
            return view(request, *args, **kwargs)

        return wrapper

    return decorator
