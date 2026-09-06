"""Alembic environment for DriftZero.

The URL comes from the application settings rather than alembic.ini, so a
migration always targets the same database the service would open.
"""

from __future__ import annotations

from logging.config import fileConfig

import sqlalchemy as sa
from sqlalchemy import engine_from_config, pool

from alembic import context
from app.config import Settings
from app.db import models  # noqa: F401  (registers every table on Base.metadata)
from app.db.base import Base, UtcDateTime

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

DATABASE_URL = Settings.from_env().database_url
config.set_main_option("sqlalchemy.url", DATABASE_URL.replace("%", "%%"))

# SQLite cannot ALTER most things in place; batch mode rebuilds the table
# instead. The metadata naming convention gives constraints stable names so the
# rebuild does not silently drop them.
RENDER_AS_BATCH = DATABASE_URL.startswith("sqlite")


def render_item(type_: str, obj: object, autogen_context: object) -> str | bool:
    """Render custom column types without importing application code.

    A migration is a historical record and has to keep replaying after the
    application is refactored. Autogenerate would otherwise emit
    ``app.db.base.UtcDateTime(...)`` -- a reference that breaks the moment the
    class moves, and which is not even importable in the generated file. Both
    custom types have exact SQL-level equivalents, so emit those instead.
    """

    if type_ != "type":
        return False
    if isinstance(obj, UtcDateTime):
        autogen_context.imports.add("import sqlalchemy as sa")  # type: ignore[attr-defined]
        return "sa.DateTime(timezone=True)"
    if isinstance(obj, sa.JSON):
        autogen_context.imports.add("import sqlalchemy as sa")  # type: ignore[attr-defined]
        autogen_context.imports.add(  # type: ignore[attr-defined]
            "from sqlalchemy.dialects import postgresql"
        )
        return "sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql')"
    return False


def run_migrations_offline() -> None:
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=RENDER_AS_BATCH,
        render_item=render_item,
        compare_type=True,
        compare_server_default=True,
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
            render_as_batch=RENDER_AS_BATCH,
            render_item=render_item,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
