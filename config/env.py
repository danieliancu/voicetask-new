"""Incarcarea variabilelor de mediu inainte ca Django sa rezolve modulul de setari.

`load_dotenv` apelat din interiorul `settings/base.py` ruleaza prea tarziu pentru
`DJANGO_SETTINGS_MODULE`: Django a ales deja modulul. `bootstrap()` se apeleaza ca
prima instructiune din manage.py / wsgi.py / asgi.py.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

_loaded = False


def bootstrap() -> None:
    """Incarca .env o singura data. Variabilele deja existente in mediu au prioritate."""
    global _loaded
    if _loaded:
        return
    load_dotenv(BASE_DIR / ".env")
    _loaded = True


def default_settings_module(fallback: str = "config.settings.dev") -> str:
    bootstrap()
    return os.environ.get("DJANGO_SETTINGS_MODULE") or fallback
