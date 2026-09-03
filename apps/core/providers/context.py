"""Contextul transmis parserului de intentii."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class KnownItem:
    """Un obiect existent al utilizatorului, candidat pentru modificare sau stergere."""

    kind: str
    pk: int
    title: str


@dataclass(frozen=True)
class IntentContext:
    """Tot ce are nevoie parserul ca sa interpreteze o comanda, fara acces la DB."""

    now: datetime
    timezone_name: str = "Europe/Bucharest"
    known_items: list[KnownItem] = field(default_factory=list)
    known_people: list[str] = field(default_factory=list)
    default_reminder_offset: int = 30
    #: "create" pentru ecranul Adaugă, "edit" cand exista deja o tinta.
    mode: str = "create"
    target_kind: str | None = None
    target_id: int | None = None
