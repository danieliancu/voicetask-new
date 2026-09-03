"""Indexuri de cautare full-text, numai pe PostgreSQL.

Pe SQLite migratia nu face nimic: `RunPython` verifica `connection.vendor`.
Nu poate fi verificata pe masina de dezvoltare (nu exista PostgreSQL instalat).
"""

from django.db import connection, migrations

EXTENSIONS = """
CREATE EXTENSION IF NOT EXISTS unaccent;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
"""

INDEXES = """
CREATE INDEX IF NOT EXISTS notes_note_fts
    ON notes_note USING GIN (
        setweight(to_tsvector('romanian', coalesce(title, '')), 'A') ||
        setweight(to_tsvector('romanian', coalesce(content, '')), 'B')
    );
CREATE INDEX IF NOT EXISTS notes_note_trgm ON notes_note USING GIN (title gin_trgm_ops);

CREATE INDEX IF NOT EXISTS scheduling_appointment_fts
    ON scheduling_appointment USING GIN (
        setweight(to_tsvector('romanian', coalesce(title, '')), 'A') ||
        setweight(to_tsvector('romanian', coalesce(description, '')), 'B') ||
        setweight(to_tsvector('romanian', coalesce(location, '')), 'B')
    );
CREATE INDEX IF NOT EXISTS scheduling_appointment_trgm
    ON scheduling_appointment USING GIN (title gin_trgm_ops);

CREATE INDEX IF NOT EXISTS scheduling_reminder_fts
    ON scheduling_reminder USING GIN (
        setweight(to_tsvector('romanian', coalesce(title, '')), 'A') ||
        setweight(to_tsvector('romanian', coalesce(description, '')), 'B')
    );

CREATE INDEX IF NOT EXISTS documents_scanneddocument_fts
    ON documents_scanneddocument USING GIN (
        setweight(to_tsvector('romanian', coalesce(title, '')), 'A') ||
        setweight(to_tsvector('romanian', coalesce(extracted_text, '')), 'B')
    );

CREATE INDEX IF NOT EXISTS integrations_emailreference_fts
    ON integrations_emailreference USING GIN (
        setweight(to_tsvector('romanian', coalesce(subject, '')), 'A') ||
        setweight(to_tsvector('romanian', coalesce(sender, '')), 'B') ||
        setweight(to_tsvector('romanian', coalesce(snippet, '')), 'B')
    );
"""

DROP_INDEXES = """
DROP INDEX IF EXISTS notes_note_fts;
DROP INDEX IF EXISTS notes_note_trgm;
DROP INDEX IF EXISTS scheduling_appointment_fts;
DROP INDEX IF EXISTS scheduling_appointment_trgm;
DROP INDEX IF EXISTS scheduling_reminder_fts;
DROP INDEX IF EXISTS documents_scanneddocument_fts;
DROP INDEX IF EXISTS integrations_emailreference_fts;
"""


def apply_postgres(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(EXTENSIONS)
        cursor.execute(INDEXES)


def revert_postgres(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(DROP_INDEXES)


class Migration(migrations.Migration):
    dependencies = [
        ("search", "0001_initial"),
        ("notes", "0001_initial"),
        ("scheduling", "0001_initial"),
        ("documents", "0001_initial"),
        ("integrations", "0001_initial"),
    ]

    operations = [migrations.RunPython(apply_postgres, revert_postgres)]
