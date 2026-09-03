"""Selectarea backendului de cautare in functie de baza de date."""

from __future__ import annotations

from django.db import connection


def get_backend():
    """PostgreSQL foloseste full-text search; SQLite are un fallback pentru dezvoltare."""
    if connection.vendor == "postgresql":
        from apps.search.backends.postgres import PostgresBackend

        return PostgresBackend()
    from apps.search.backends.sqlite import SqliteBackend

    return SqliteBackend()
