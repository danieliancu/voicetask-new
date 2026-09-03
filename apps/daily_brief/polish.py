"""Reformularea rezumatului de catre un model AI, sub o poarta stricta.

Contractul: modelul primeste textul determinist si are voie doar sa-l rescrie mai
natural. Rezultatul este verificat automat inainte de a fi acceptat:

1. nu are voie sa contina numere care nu apar in textul original;
2. nu are voie sa contina ore sau date noi;
3. nu are voie sa contina nume proprii noi;
4. nu are voie sa fie mult mai lung decat originalul;
5. nu are voie sa introduca prea multe cuvinte noi.

Daca oricare regula cade, se pastreaza textul determinist si se noteaza motivul.
Reformularea este oprita implicit (`BRIEF_POLISH_ENABLED=False`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from django.conf import settings

from apps.core.providers.base import ProviderError, ProviderTimeout, ProviderUnavailable
from apps.core.providers.instrumentation import timed
from apps.search.normalize import normalize

SYSTEM_PROMPT = """Rescrii un rezumat zilnic în limba română, ca să sune mai natural
când este citit cu voce tare.

Reguli absolute:
- Nu adăuga nicio informație nouă: nicio oră, dată, sumă, persoană, loc sau eveniment.
- Nu elimina nicio informație existentă.
- Păstrează exact toate numerele, orele și numele proprii din text.
- Maximum 20% mai lung decât originalul.
- Răspunde doar cu textul rescris, fără introduceri."""

_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
_PROPER = re.compile(r"\b[A-ZĂÂÎȘȚ][\wăâîșțĂÂÎȘȚ-]{2,}\b")
#: Cuvinte de legatura pe care modelul are voie sa le introduca.
ALLOWED_NEW_TOKENS = {
    "apoi", "urmeaza", "urmatoarea", "asadar", "deci", "iar", "si", "de", "la", "in",
    "pe", "cu", "ai", "este", "sunt", "ta", "tau", "tale", "azi", "astazi", "zi", "ziua",
    "dupa", "aceea", "mai", "tarziu", "dimineata", "seara", "dupa-amiaza", "programata",
    "programate", "ora", "orele", "urmata", "incheie", "incepe", "vei", "avea", "un", "o",
}
MAX_NEW_TOKENS = 8
MAX_LENGTH_RATIO = 1.2


@dataclass(frozen=True)
class PolishResult:
    text: str
    accepted: bool
    reason: str = ""


def validate_polish(original: str, candidate: str) -> tuple[bool, str]:
    """Poarta anti-halucinatie. Returneaza (acceptat, motiv_respingere)."""
    if not candidate.strip():
        return False, "text_gol"

    if len(candidate) > len(original) * MAX_LENGTH_RATIO:
        return False, "prea_lung"

    original_numbers = set(_NUMBER.findall(original))
    candidate_numbers = set(_NUMBER.findall(candidate))
    if candidate_numbers - original_numbers:
        return False, "numere_noi"
    if original_numbers - candidate_numbers:
        return False, "numere_pierdute"

    original_names = set(_PROPER.findall(original))
    candidate_names = set(_PROPER.findall(candidate))
    # Numele proprii de la inceput de fraza nu pot fi distinse de cuvinte obisnuite,
    # deci comparam doar aparitiile care nu incep o propozitie.
    new_names = {
        name
        for name in candidate_names - original_names
        if not _starts_sentence(candidate, name)
    }
    if new_names:
        return False, "nume_noi"

    original_tokens = set(normalize(original).split())
    candidate_tokens = set(normalize(candidate).split())
    new_tokens = candidate_tokens - original_tokens - ALLOWED_NEW_TOKENS
    if len(new_tokens) > MAX_NEW_TOKENS:
        return False, "prea_multe_cuvinte_noi"

    return True, ""


def _starts_sentence(text: str, word: str) -> bool:
    return bool(re.search(rf"(?:^|[.\n]\s+){re.escape(word)}\b", text))


def polish(text: str) -> PolishResult:
    """Reformuleaza textul. Orice esec inseamna „pastreaza originalul"."""
    if not settings.BRIEF_POLISH_ENABLED or not settings.AI_ENABLED:
        return PolishResult(text=text, accepted=False, reason="dezactivat")

    try:
        from openai import OpenAI
    except ImportError:
        return PolishResult(text=text, accepted=False, reason="sdk_lipsa")
    if not settings.OPENAI_API_KEY:
        return PolishResult(text=text, accepted=False, reason="cheie_lipsa")

    client = OpenAI(
        api_key=settings.OPENAI_API_KEY,
        base_url=settings.OPENAI_BASE_URL,
        timeout=settings.PROVIDER_TIMEOUT_SECONDS,
        max_retries=0,
    )
    try:
        with timed("openai-polish", "polish"):
            response = client.chat.completions.create(
                model=settings.OPENAI_MODEL_INTENT,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": text},
                ],
                temperature=0.3,
            )
    except (ProviderError, ProviderTimeout, ProviderUnavailable):
        return PolishResult(text=text, accepted=False, reason="eroare_provider")
    except Exception:
        return PolishResult(text=text, accepted=False, reason="eroare_provider")

    candidate = (response.choices[0].message.content or "").strip() if response.choices else ""
    accepted, reason = validate_polish(text, candidate)
    if not accepted:
        return PolishResult(text=text, accepted=False, reason=reason)
    return PolishResult(text=candidate, accepted=True)
