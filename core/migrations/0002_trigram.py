"""PostgreSQL-only: pg_trgm extension + GIN index for fuzzy name matching in
the duplicate-person detector. Skipped entirely on SQLite, where the dedup
service degrades to substring matching."""

from django.db import connection, migrations

operations = []
if connection.vendor == "postgresql":
    from django.contrib.postgres.operations import TrigramExtension

    operations = [
        TrigramExtension(),
        migrations.RunSQL(
            sql=(
                "CREATE INDEX IF NOT EXISTS person_name_trgm ON core_person "
                "USING gin (last_name gin_trgm_ops, first_name gin_trgm_ops);"
            ),
            reverse_sql="DROP INDEX IF EXISTS person_name_trgm;",
        ),
    ]


class Migration(migrations.Migration):
    dependencies = [("core", "0001_initial")]
    operations = operations
