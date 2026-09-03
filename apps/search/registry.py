"""Registrul surselor de cautare.

Fiecare aplicatie isi inregistreaza propria sursa la pornire (`AppConfig.ready`).
Serviciul de cautare nu cunoaste modelele: primeste doar `SearchHit`-uri normalizate.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class SearchHit:
    """Un rezultat, indiferent din ce aplicatie provine."""

    kind: str
    pk: int
    title: str
    subtitle: str = ""
    #: Eticheta vizibila a sursei: „Notiță", „Document scanat", „Gmail", ...
    source_label: str = ""
    source_icon: str = "note"
    color_token: str = "violet"
    url: str = ""
    when: datetime | None = None
    tab_label: str = ""
    score: float = 0.0
    extra: dict[str, Any] = field(default_factory=dict)


class SearchSource(abc.ABC):
    """Contractul pe care il implementeaza fiecare aplicatie cautabila."""

    #: Cheia din filtrele interfetei: notite, programari, emailuri, documente, alarme.
    key: str = ""
    label: str = ""
    icon: str = "note"
    #: Campurile de model folosite la cautare; primul are pondere mai mare.
    search_fields: tuple[str, ...] = ("title",)
    match_field: str = "match_text"

    @abc.abstractmethod
    def queryset(self, user):
        """Toate obiectele vizibile ale utilizatorului, inainte de filtrarea textuala."""

    @abc.abstractmethod
    def to_hit(self, obj, *, score: float = 0.0) -> SearchHit:
        ...

    def order_field(self) -> str:
        return "-created_at"


_REGISTRY: dict[str, SearchSource] = {}


def register(source: SearchSource) -> SearchSource:
    if not source.key:
        raise ValueError("Sursa de căutare trebuie să aibă o cheie.")
    _REGISTRY[source.key] = source
    return source


def all_sources() -> list[SearchSource]:
    return list(_REGISTRY.values())


def get_source(key: str) -> SearchSource | None:
    return _REGISTRY.get(key)


def source_keys() -> list[str]:
    return list(_REGISTRY.keys())
