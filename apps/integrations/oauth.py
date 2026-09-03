"""OAuth 2.0 pentru Google, cu permisiuni minime.

Gmail: implicit `gmail.metadata` — cele mai mici permisiuni care permit listarea
mesajelor. Acest scope nu returneaza snippet-uri; utilizatorul poate alege
explicit `gmail.readonly` daca vrea fragmente de text.
Calendar: `calendar.events` — citire si scriere, dar scrierea se face doar dupa
confirmare in interfata.
"""

from __future__ import annotations

from django.conf import settings
from django.core.signing import BadSignature, SignatureExpired, TimestampSigner

from apps.integrations.models import ConnectedAccount

SCOPES = {
    ConnectedAccount.Provider.GMAIL: {
        "metadata": ["https://www.googleapis.com/auth/gmail.metadata"],
        "readonly": ["https://www.googleapis.com/auth/gmail.readonly"],
    },
    ConnectedAccount.Provider.CALENDAR: {
        "default": ["https://www.googleapis.com/auth/calendar.events"],
    },
}

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"

_signer = TimestampSigner(salt="voicetask.oauth.state")
STATE_MAX_AGE = 600


def scopes_for(provider: str) -> list[str]:
    if provider == ConnectedAccount.Provider.GMAIL:
        configured = settings.GMAIL_SCOPE_LEVEL
        level = configured if configured in SCOPES[provider] else "metadata"
        return SCOPES[provider][level]
    return SCOPES[provider]["default"]


def is_configured() -> bool:
    return bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET)


def sign_state(user_id: int, provider: str) -> str:
    return _signer.sign(f"{user_id}:{provider}")


def unsign_state(state: str) -> tuple[int, str] | None:
    try:
        raw = _signer.unsign(state, max_age=STATE_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None
    user_id, _, provider = raw.partition(":")
    if not user_id.isdigit():
        return None
    return int(user_id), provider


def authorization_url(user_id: int, provider: str) -> str:
    from urllib.parse import urlencode

    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": settings.GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": " ".join(scopes_for(provider)),
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": sign_state(user_id, provider),
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def exchange_code(code: str) -> dict:
    """Schimba codul de autorizare pe tokenuri. Tokenurile nu se logheaza."""
    import requests

    response = requests.post(
        TOKEN_URL,
        data={
            "code": code,
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "redirect_uri": settings.GOOGLE_REDIRECT_URI,
            "grant_type": "authorization_code",
        },
        timeout=settings.PROVIDER_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json()
