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
from app.migrations import _migration_root, upgrade_database

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


def test_startup_migration_creates_a_fresh_database(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'startup-fresh.db'}"

    upgrade_database(url)

    engine = sa.create_engine(url)
    inspector = sa.inspect(engine)
    tables = set(inspector.get_table_names())
    with engine.connect() as connection:
        current = connection.scalar(sa.text("SELECT version_num FROM alembic_version"))
    engine.dispose()

    assert set(Base.metadata.tables) <= tables
    assert current == "0012"


def test_migration_root_uses_deployment_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "alembic.ini").touch()
    (tmp_path / "alembic").mkdir()
    (tmp_path / "alembic" / "env.py").touch()
    monkeypatch.chdir(tmp_path)

    assert _migration_root() == tmp_path


def test_startup_migration_upgrades_unversioned_revision_six(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'startup-legacy.db'}"
    config = _alembic_config(url)
    command.upgrade(config, "0006")
    engine = sa.create_engine(url)
    with engine.begin() as connection:
        connection.execute(sa.text("DROP TABLE alembic_version"))
    engine.dispose()

    upgrade_database(url)

    engine = sa.create_engine(url)
    inspector = sa.inspect(engine)
    with engine.connect() as connection:
        current = connection.scalar(sa.text("SELECT version_num FROM alembic_version"))
    tables = set(inspector.get_table_names())
    snapshot_columns = {column["name"] for column in inspector.get_columns("health_snapshots")}
    engine.dispose()

    assert current == "0012"
    assert {"model_connections", "users", "tenant_memberships", "user_sessions"} <= tables
    assert {"event_id", "schema_version"} <= snapshot_columns


def test_startup_migration_repairs_mixed_create_all_schema(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'startup-mixed.db'}"
    config = _alembic_config(url)
    command.upgrade(config, "0006")
    engine = sa.create_engine(url)
    with engine.begin() as connection:
        connection.execute(sa.text("DROP TABLE alembic_version"))
    Base.metadata.create_all(engine)
    before = {column["name"] for column in sa.inspect(engine).get_columns("health_snapshots")}
    engine.dispose()

    assert "event_id" not in before
    upgrade_database(url)

    engine = sa.create_engine(url)
    inspector = sa.inspect(engine)
    after = {column["name"] for column in inspector.get_columns("health_snapshots")}
    constraints = {
        constraint["name"] for constraint in inspector.get_unique_constraints("health_snapshots")
    }
    with engine.connect() as connection:
        current = connection.scalar(sa.text("SELECT version_num FROM alembic_version"))
    engine.dispose()

    assert current == "0012"
    assert {"event_id", "schema_version"} <= after
    assert "model_event_id" in constraints


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
