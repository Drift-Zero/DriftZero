"""Migrations must agree with the models, on both supported backends."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy.schema import CreateTable

from alembic import command
from app.db import models  # noqa: F401  (registers every table)
from app.db.base import Base

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _alembic_config(database_url: str) -> Config:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    # env.py reads the URL from the environment, so migrations and the
    # application can never disagree about the target.
    os.environ["DRIFTZERO_DATABASE_URL"] = database_url
    return config


@pytest.fixture
def migrated_url(tmp_path: Path) -> str:
    url = f"sqlite:///{tmp_path / 'migrated.db'}"
    command.upgrade(_alembic_config(url), "head")
    return url


def test_migration_matches_the_models(migrated_url: str) -> None:
    """The classic way a schema rots is migrations drifting from the models."""

    engine = sa.create_engine(migrated_url)
    with engine.connect() as connection:
        differences = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    engine.dispose()

    assert differences == [], f"migration and models disagree: {differences}"


def test_migration_creates_every_table(migrated_url: str) -> None:
    engine = sa.create_engine(migrated_url)
    tables = set(sa.inspect(engine).get_table_names())
    engine.dispose()

    assert set(Base.metadata.tables) <= tables


def test_downgrade_removes_every_table(migrated_url: str) -> None:
    command.downgrade(_alembic_config(migrated_url), "base")

    engine = sa.create_engine(migrated_url)
    tables = set(sa.inspect(engine).get_table_names())
    engine.dispose()

    assert tables == {"alembic_version"}


def _postgres_ddl() -> str:
    dialect = sa.dialects.postgresql.dialect()
    return "\n".join(
        str(CreateTable(table).compile(dialect=dialect)) for table in Base.metadata.tables.values()
    )


def test_schema_compiles_for_postgresql() -> None:
    """Catch PostgreSQL incompatibilities without needing a server."""

    ddl = _postgres_ddl()

    assert "JSONB" in ddl, "JSON columns should become JSONB on PostgreSQL"
    assert "TIMESTAMP WITH TIME ZONE" in ddl, "timestamps should be timezone-aware"


def test_enum_checks_use_wire_values() -> None:
    """The database stores the same strings the API emits, not enum member names."""

    dialect = sa.dialects.postgresql.dialect()
    ddl = str(CreateTable(Base.metadata.tables["health_snapshots"]).compile(dialect=dialect))

    assert "'insufficient_data'" in ddl
    assert "INSUFFICIENT_DATA" not in ddl
