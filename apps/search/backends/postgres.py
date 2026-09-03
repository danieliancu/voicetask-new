"""Cautare full-text pentru PostgreSQL.

Foloseste configuratia „romanian" pentru stemming, `unaccent` pentru diacritice si
similaritatea trigram ca plasa de siguranta pentru greseli de tastare. Titlul are
ponderea A, restul continutului ponderea B.

Aceasta cale nu poate fi executata pe masina de dezvoltare (nu exista PostgreSQL
instalat); testele care o acopera sunt marcate `pg_only` si se sar automat.
"""

from __future__ import annotations

from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector, TrigramSimilarity
from django.db.models import F, FloatField, Q, Value
from django.db.models.functions import Coalesce, Greatest

from apps.search.normalize import normalize

CONFIG = "romanian"


class PostgresBackend:
    name = "postgresql"
    supports_ranking = True

    def _vector(self, source):
        primary, *rest = source.search_fields
        vector = SearchVector(primary, weight="A", config=CONFIG)
        for name in rest:
            vector = vector + SearchVector(name, weight="B", config=CONFIG)
        return vector

    def filter(self, queryset, query: str, source):
        normalized = normalize(query)
        if not normalized:
            return queryset.none()
        search_query = SearchQuery(normalized, config=CONFIG, search_type="websearch")
        vector = self._vector(source)
        primary = source.search_fields[0]
        return (
            queryset.annotate(
                rank=SearchRank(vector, search_query),
                similarity=Coalesce(
                    TrigramSimilarity(primary, normalized), Value(0.0), output_field=FloatField()
                ),
            )
            .filter(Q(rank__gt=0.01) | Q(similarity__gt=0.25))
            .annotate(relevance=Greatest(F("rank"), F("similarity")))
        )

    def score(self, obj, query: str, source) -> float:
        return float(getattr(obj, "relevance", 0.0) or 0.0)

    def order(self, queryset, query: str, source):
        return queryset.order_by("-relevance", source.order_field())
