"""Interpretarea comenzii printr-un model OpenAI, constrans la schema aplicatiei.

Modelul primeste schema JSON generata din `IntentResult` si nu are voie sa
raspunda altceva. Rezultatul trece oricum prin validarea Pydantic: ce nu se
potriveste este respins, nu „reparat".
"""

from __future__ import annotations

import json

from django.conf import settings

from apps.assistant.schemas import JSON_SCHEMA, Intent
from apps.core.providers.base import (
    IntentParserProvider,
    ProviderError,
    ProviderInvalidResponse,
    ProviderTimeout,
    ProviderUnavailable,
)
from apps.core.providers.context import IntentContext
from apps.core.providers.instrumentation import timed, with_retries

SYSTEM_PROMPT = """Ești un interpret de comenzi în limba română pentru un asistent personal.
Transformi o singură propoziție rostită de utilizator într-un obiect JSON.

Reguli obligatorii:
- Nu inventa date, ore, sume, persoane sau locații care nu apar în text.
- Dacă utilizatorul nu spune o dată, lasă `date` null. Nu ghici.
- `intent` este exact una dintre valorile permise.
- `confidence` reflectă cât de sigur ești (0.0-1.0). Fii sever.
- Dacă textul e ambiguu (dată neclară, persoană neidentificabilă, mai multe
  interpretări posibile), setează `clarification_required` true și formulează
  `clarification_question` în română.
- Pentru ștergere sau modificare, `clarification_required` este întotdeauna true
  dacă nu ai un `target_id` primit în context.
- Răspunde exclusiv cu JSON valid, fără explicații."""


class OpenAIIntentParser(IntentParserProvider):
    name = "openai-intentii"

    def _client(self):
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover
            raise ProviderUnavailable("Pachetul openai nu este instalat.") from exc
        if not settings.OPENAI_API_KEY:
            raise ProviderUnavailable("OPENAI_API_KEY nu este configurată.")
        return OpenAI(
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL,
            timeout=settings.PROVIDER_TIMEOUT_SECONDS,
            max_retries=0,
        )

    def is_available(self) -> bool:
        return bool(settings.OPENAI_API_KEY)

    def parse(self, text: str, *, context: IntentContext) -> dict:
        client = self._client()
        user_prompt = json.dumps(
            {
                "comanda": text,
                "acum": context.now.isoformat(),
                "fus_orar": context.timezone_name,
                "mod": context.mode,
                "tinta_curenta": (
                    {"kind": context.target_kind, "id": context.target_id}
                    if context.target_id
                    else None
                ),
                "obiecte_cunoscute": [
                    {"kind": item.kind, "id": item.pk, "titlu": item.title}
                    for item in context.known_items[:40]
                ],
                "decalaj_alarma_implicit": context.default_reminder_offset,
            },
            ensure_ascii=False,
        )

        def call():
            import openai

            try:
                return client.chat.completions.create(
                    model=settings.OPENAI_MODEL_INTENT,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    response_format={
                        "type": "json_schema",
                        "json_schema": {
                            "name": "IntentResult",
                            "schema": JSON_SCHEMA,
                            "strict": False,
                        },
                    },
                    temperature=0,
                )
            except openai.APITimeoutError as exc:
                raise ProviderTimeout(str(exc)) from exc
            except openai.APIError as exc:
                raise ProviderError(str(exc)) from exc

        with timed(self.name, "parse"):
            response = with_retries(
                call, attempts=settings.PROVIDER_MAX_RETRIES + 1, retry_on=(ProviderTimeout,)
            )

        content = response.choices[0].message.content if response.choices else ""
        try:
            payload = json.loads(content or "{}")
        except json.JSONDecodeError as exc:
            raise ProviderInvalidResponse("Modelul nu a returnat JSON valid.") from exc
        if not isinstance(payload, dict):
            raise ProviderInvalidResponse("Modelul nu a returnat un obiect JSON.")
        payload.setdefault("intent", Intent.UNKNOWN)
        return payload
