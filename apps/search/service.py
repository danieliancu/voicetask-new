"""Serviciul de cautare unificata."""

from __future__ import annotations

from dataclasses import dataclass

from apps.search.backends.base import get_backend
from apps.search.registry import SearchHit, all_sources, get_source

MAX_PER_SOURCE = 40


@dataclass(frozen=True)
class SearchResults:
    query: str
    hits: list[SearchHit]
    counts: dict[str, int]
    backend: str

    @property
    def total(self) -> int:
        return len(self.hits)


SORT_CHOICES = (
    ("relevanta", "Relevanță"),
    ("recente", "Cele mai recente"),
    ("data", "După dată"),
)


def search(
    user,
    query: str,
    *,
    sources: list[str] | None = None,
    sort: str = "relevanta",
    limit: int = 60,
) -> SearchResults:
    backend = get_backend()
    selected = [get_source(key) for key in sources] if sources else all_sources()
    selected = [source for source in selected if source is not None]

    hits: list[SearchHit] = []
    counts: dict[str, int] = {}
    for source in selected:
        queryset = source.queryset(user)
        matched = backend.filter(queryset, query, source)
        matched = backend.order(matched, query, source)[:MAX_PER_SOURCE]
        found = list(matched)
        counts[source.key] = len(found)
        for obj in found:
            hits.append(source.to_hit(obj, score=backend.score(obj, query, source)))

    hits = _sort(hits, sort)
    return SearchResults(query=query, hits=hits[:limit], counts=counts, backend=backend.name)


def _sort(hits: list[SearchHit], sort: str) -> list[SearchHit]:
    if sort == "recente":
        return sorted(hits, key=lambda h: (h.when is None, h.when), reverse=True)
    if sort == "data":
        with_date = sorted([h for h in hits if h.when], key=lambda h: h.when)
        return with_date + [h for h in hits if not h.when]
    return sorted(hits, key=lambda h: h.score, reverse=True)


def source_filters() -> list[tuple[str, str, str]]:
    """(cheie, eticheta, icon) pentru chipsurile de filtrare."""
    return [(source.key, source.label, source.icon) for source in all_sources()]
