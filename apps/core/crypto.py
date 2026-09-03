"""Criptarea simetrica a tokenurilor OAuth stocate in baza de date.

Cheia vine din `TOKEN_ENCRYPTION_KEY`. Daca lipseste, se deriva determinist din
`SECRET_KEY`, ca dezvoltarea sa functioneze fara configurare suplimentara; in
productie `manage.py check --deploy` avertizeaza daca nu a fost setata explicit.
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


class TokenDecryptionError(Exception):
    """Tokenul nu a putut fi decriptat: cheia s-a schimbat sau randul e corupt."""


def _fernet() -> Fernet:
    configured = (settings.TOKEN_ENCRYPTION_KEY or "").strip()
    if configured:
        return Fernet(configured.encode())
    derived = hashlib.sha256(f"voicetask-tokens:{settings.SECRET_KEY}".encode()).digest()
    return Fernet(base64.urlsafe_b64encode(derived))


def encrypt(value: str) -> str:
    if not value:
        return ""
    return _fernet().encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    if not value:
        return ""
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken as exc:
        raise TokenDecryptionError("Tokenul stocat nu a putut fi decriptat.") from exc


def generate_key() -> str:
    """Folosit de `manage.py genereaza_chei` pentru a popula .env."""
    return Fernet.generate_key().decode()
