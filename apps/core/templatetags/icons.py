"""Iconuri SVG inline. Sursa este `templates/icons/<nume>.svg`.

Nu folosim emoji si nu incarcam iconuri din retea.
"""

from __future__ import annotations

import functools
import re

from django import template
from django.template.exceptions import TemplateDoesNotExist
from django.template.loader import get_template
from django.utils.safestring import mark_safe

register = template.Library()

_SVG_OPEN = re.compile(r"<svg\b", re.IGNORECASE)


@functools.lru_cache(maxsize=256)
def _load(name: str) -> str:
    try:
        return get_template(f"icons/{name}.svg").template.source.strip()
    except TemplateDoesNotExist:
        return ""


@register.simple_tag
def icon(name: str, size: int = 24, css_class: str = "", label: str = "") -> str:
    """Insereaza un icon. Fara `label` este pur decorativ si primit aria-hidden."""
    source = _load(name)
    if not source:
        return ""
    classes = f"icon {css_class}".strip()
    if label:
        attrs = f'class="{classes}" width="{size}" height="{size}" role="img" aria-label="{label}"'
    else:
        attrs = (
            f'class="{classes}" width="{size}" height="{size}" '
            'aria-hidden="true" focusable="false"'
        )
    return mark_safe(_SVG_OPEN.sub(f"<svg {attrs}", source, count=1))
