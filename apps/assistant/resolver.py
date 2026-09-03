"""Gasirea obiectului la care se refera o comanda de modificare sau stergere."""

from __future__ import annotations

from dataclasses import dataclass

from apps.core.enums import ItemKind
from apps.core.providers.context import KnownItem
from apps.search.normalize import normalize, tokens

#: Sub acest scor nu consideram ca am gasit obiectul.
MIN_SCORE = 0.45
#: Diferenta minima fata de urmatorul candidat, ca alegerea sa fie neambigua.
MIN_MARGIN = 0.15
MAX_CANDIDATES = 5


@dataclass(frozen=True)
class Candidate:
    kind: str
    pk: int
    title: str
    score: float

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "pk": self.pk,
            "title": self.title,
            "score": round(self.score, 3),
        }


def known_items(user, *, limit: int = 60) -> list[KnownItem]:
    """Obiectele recente ale utilizatorului, transmise parserului ca context."""
    from apps.documents.models import ScannedDocument
    from apps.integrations.models import EmailReference
    from apps.notes.models import Note
    from apps.scheduling.models import Appointment, Reminder

    items: list[KnownItem] = []
    for model, kind in (
        (Note, ItemKind.NOTE),
        (Appointment, ItemKind.APPOINTMENT),
        (Reminder, ItemKind.REMINDER),
        (ScannedDocument, ItemKind.DOCUMENT),
        (EmailReference, ItemKind.EMAIL),
    ):
        for obj in model.objects.for_user(user).order_by("-created_at")[: limit // 5]:
            items.append(KnownItem(kind=kind, pk=obj.pk, title=str(obj)))
    return items


def score_title(query: str, title: str) -> float:
    """Cate cuvinte din comanda apar in titlu, ponderat de lungimea titlului."""
    query_tokens = [token for token in tokens(query) if len(token) > 2]
    if not query_tokens:
        return 0.0
    title_normalized = normalize(title)
    title_tokens = set(tokens(title))
    matched = sum(1 for token in query_tokens if token in title_tokens)
    partial = sum(
        0.5
        for token in query_tokens
        if token not in title_tokens and token in title_normalized
    )
    return min(1.0, (matched + partial) / len(query_tokens))


def resolve(
    user, text: str, *, kind: str | None = None
) -> tuple[int | None, str | None, list[Candidate]]:
    """Returneaza (target_id, target_kind, candidati).

    `target_id` este completat doar cand un singur obiect se detaseaza clar.
    In rest, decizia ramane la utilizator.
    """
    items = known_items(user)
    if kind:
        items = [item for item in items if item.kind == kind]

    scored = [
        Candidate(
            kind=item.kind,
            pk=item.pk,
            title=item.title,
            score=score_title(text, item.title),
        )
        for item in items
    ]
    scored = [candidate for candidate in scored if candidate.score >= MIN_SCORE]
    scored.sort(key=lambda candidate: candidate.score, reverse=True)
    candidates = scored[:MAX_CANDIDATES]

    if not candidates:
        return None, kind, []
    if len(candidates) == 1:
        return candidates[0].pk, candidates[0].kind, candidates
    if candidates[0].score - candidates[1].score >= MIN_MARGIN:
        return candidates[0].pk, candidates[0].kind, candidates
    return None, kind, candidates
