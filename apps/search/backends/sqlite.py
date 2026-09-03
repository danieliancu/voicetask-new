"""Cautare pentru SQLite (dezvoltare).

Cauta pe coloana `match_text`, care este scrisa deja normalizata (litere mici, fara
diacritice). Interogarea trece prin aceeasi functie de normalizare, deci „sedinta"
gaseste „Ședință". Scorul favorizeaza potrivirile din titlu.
"""

from __future__ import annotations

from django.db.models import Q

from apps.search.normalize import normalize, tokens


class SqliteBackend:
    name = "sqlite"
    supports_ranking = False

    def filter(self, queryset, query: str, source):
        words = tokens(query)
        if not words:
            return queryset.none()
        condition = Q()
        for word in words:
            condition &= Q(**{f"{source.match_field}__contains": word})
        return queryset.filter(condition)

    def score(self, obj, query: str, source) -> float:
        """Scor simplu si stabil: titlu > continut, potrivire completa > partiala."""
        words = tokens(query)
        if not words:
            return 0.0
        title = normalize(getattr(obj, source.search_fields[0], "") or "")
        haystack = normalize(getattr(obj, source.match_field, "") or "")
        score = 0.0
        for word in words:
            if word in title:
                score += 2.0
                if title.startswith(word):
                    score += 0.5
            elif word in haystack:
                score += 1.0
        return score / (len(words) * 2.5)

    def order(self, queryset, query: str, source):
        return queryset.order_by(source.order_field())
