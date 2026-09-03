"""System checks: erorile de configurare apar la `manage.py check`, nu in productie."""

from __future__ import annotations

from django.conf import settings
from django.core.checks import Error, Tags, Warning, register
from django.utils.module_loading import import_string

from apps.core.providers.registry import KIND_TO_INTERFACE, resolve_path


@register(Tags.compatibility)
def check_providers(app_configs, **kwargs):
    errors = []
    for kind, interface in KIND_TO_INTERFACE.items():
        if kind not in settings.PROVIDERS:
            errors.append(
                Error(
                    f"Lipsește providerul pentru '{kind}' în settings.PROVIDERS.",
                    id="core.E001",
                )
            )
            continue
        dotted = resolve_path(kind)
        try:
            cls = import_string(dotted)
        except ImportError as exc:
            errors.append(
                Error(
                    f"Providerul '{kind}' nu poate fi importat: {dotted} ({exc}).",
                    hint="Verifică variabila de mediu corespunzătoare.",
                    id="core.E002",
                )
            )
            continue
        if not (isinstance(cls, type) and issubclass(cls, interface)):
            errors.append(
                Error(
                    f"{dotted} nu implementează {interface.__name__}.",
                    id="core.E003",
                )
            )
    return errors


@register(Tags.security, deploy=True)
def check_secrets(app_configs, **kwargs):
    problems = []
    if not (settings.TOKEN_ENCRYPTION_KEY or "").strip():
        problems.append(
            Warning(
                "TOKEN_ENCRYPTION_KEY nu este setată; cheia se derivă din SECRET_KEY.",
                hint="Rulează `manage.py genereaza_chei` și pune valoarea în .env.",
                id="core.W001",
            )
        )
    if settings.SECRET_KEY == "insecure-doar-pentru-dev":
        problems.append(
            Error("DJANGO_SECRET_KEY are încă valoarea implicită de dezvoltare.", id="core.E004")
        )
    if settings.AI_ENABLED and not settings.OPENAI_API_KEY:
        problems.append(
            Error(
                "AI_ENABLED=True dar OPENAI_API_KEY lipsește.",
                hint="Setează cheia sau lasă AI_ENABLED=False pentru providerii offline.",
                id="core.E005",
            )
        )
    return problems
