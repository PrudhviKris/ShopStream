"""Alembic environment.

The URL and the model metadata both come from the application itself, so
`alembic upgrade head` always targets the database the service is configured
to use (fastapi_backend/.env), and autogenerate always compares against the
live models.

Override the target for one command with ALEMBIC_DATABASE_URL, e.g. to build
a fresh schema somewhere else:

    ALEMBIC_DATABASE_URL=sqlite:///./scratch.db alembic upgrade head
"""
import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402
from app.database import Base  # noqa: E402
import app.models  # noqa: E402,F401  (import for the side effect: registers every table)

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option(
    "sqlalchemy.url",
    (os.getenv("ALEMBIC_DATABASE_URL") or settings.DATABASE_URL).replace("%", "%%"),
)

target_metadata = Base.metadata


def include_object(obj, name, type_, reflected, compare_to):
    """Only manage the tables this application owns.

    The same MySQL database also holds Django's tables (auth_user,
    django_session, ...), created by `manage.py migrate`. They aren't in
    Base.metadata, so without this filter autogenerate would cheerfully write
    a migration that DROPS every one of them.
    """
    table = name if type_ == "table" else getattr(obj, "table", None)
    table_name = table if isinstance(table, str) else getattr(table, "name", None)
    if table_name is None:
        return True
    return table_name in target_metadata.tables


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of running it (`alembic upgrade head --sql`)."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,          # notice column type changes too
            include_object=include_object,
            render_as_batch=connection.dialect.name == "sqlite",
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
