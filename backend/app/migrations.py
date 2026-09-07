"""Apply database migrations before long-running services start."""

from __future__ import annotations

import os
from pathlib import Path

import sqlalchemy as sa
from alembic.config import Config

from alembic import command
from app.config import Settings
from app.db.session import normalize_database_url

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _alembic_config() -> Config:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return config


def _column_names(inspector: sa.Inspector, table: str) -> set[str]:
    return {str(column["name"]) for column in inspector.get_columns(table)}


def _infer_unversioned_revision(inspector: sa.Inspector) -> str:
    """Identify schemas created directly by older ``create_all`` releases.

    Early demo deployments predated startup migrations, so their schema has no
    ``alembic_version`` row. Refuse unknown shapes rather than stamping them at
    an unsafe revision.
    """

    tables = set(inspector.get_table_names())
    if {"users", "tenant_memberships", "user_sessions"} <= tables:
        return "0010"
    if "event_id" in _column_names(inspector, "health_snapshots"):
        return "0009"
    if "model_connections" in tables:
        columns = _column_names(inspector, "model_connections")
        return "0008" if "credential_ciphertext" in columns else "0007"

    revision_six_tables = {
        "tenants",
        "monitored_models",
        "health_snapshots",
        "recovery_commands",
        "recovery_executions",
        "verification_runs",
    }
    if revision_six_tables <= tables:
        command_columns = _column_names(inspector, "recovery_commands")
        execution_columns = _column_names(inspector, "recovery_executions")
        verification_columns = _column_names(inspector, "verification_runs")
        if (
            "snapshot_id" in command_columns
            and {
                "external_operation_id",
                "configuration_verified_at",
                "config_before",
                "config_after",
            }
            <= execution_columns
            and {"required_coverage", "observed_coverage"} <= verification_columns
        ):
            return "0006"

    raise RuntimeError(
        "Existing database has no Alembic revision and does not match a supported "
        "legacy DriftZero schema."
    )


def upgrade_database(database_url: str | None = None) -> None:
    """Bring a fresh, versioned, or supported legacy database to migration head."""

    normalized_url = normalize_database_url(database_url or Settings.from_env().database_url)
    engine = sa.create_engine(normalized_url)
    try:
        inspector = sa.inspect(engine)
        tables = set(inspector.get_table_names())
        baseline = None
        if tables and "alembic_version" not in tables:
            baseline = _infer_unversioned_revision(inspector)
    finally:
        engine.dispose()

    previous_url = os.environ.get("DRIFTZERO_DATABASE_URL")
    os.environ["DRIFTZERO_DATABASE_URL"] = normalized_url
    try:
        config = _alembic_config()
        if baseline is not None:
            command.stamp(config, baseline)
        command.upgrade(config, "head")
    finally:
        if previous_url is None:
            os.environ.pop("DRIFTZERO_DATABASE_URL", None)
        else:
            os.environ["DRIFTZERO_DATABASE_URL"] = previous_url


if __name__ == "__main__":
    upgrade_database()
