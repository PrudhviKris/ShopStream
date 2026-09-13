"""Add columns introduced after a table was first created.

`Base.metadata.create_all` only creates missing *tables* — it never alters an
existing one, so a column added to a model later is simply absent in a
database that already had that table, and every query touching it fails.
There's no migration tool in this project, so this adds exactly those
columns, idempotently, at startup. Only additive, nullable (or defaulted)
columns belong here: it must be safe to run against live data every boot.
"""
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

# table -> [(column, DDL type)] — kept in step with app/models.py
ADDED_COLUMNS = {
    "notifications": [
        ("order_id", "INTEGER NULL"),
    ],
    "development_emails": [
        ("html_body", "TEXT NULL"),
        ("notification_type", "VARCHAR(50) NULL"),
        ("status", "VARCHAR(20) NOT NULL DEFAULT 'stored'"),
        ("error", "TEXT NULL"),
        ("sent_at", "DATETIME NULL"),
    ],
}


def upgrade_schema(engine: Engine) -> list:
    """Add any missing columns; returns what was added (empty when current)."""
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    added = []
    with engine.begin() as conn:
        for table, columns in ADDED_COLUMNS.items():
            if table not in tables:
                continue  # create_all makes it fresh, with every column
            existing = {c["name"] for c in inspector.get_columns(table)}
            for name, ddl in columns:
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
                    added.append(f"{table}.{name}")
    return added
