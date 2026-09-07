"""Add synchronized URL metadata to evidence sources.

Revision ID: 0014
Revises: 0013
Create Date: 2026-09-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {str(column["name"]) for column in inspector.get_columns("evidence_sources")}
    additions: list[tuple[str, sa.Column]] = [
        ("source_url", sa.Column("source_url", sa.String(2048), nullable=True)),
        ("etag", sa.Column("etag", sa.String(255), nullable=True)),
        ("last_modified", sa.Column("last_modified", sa.String(255), nullable=True)),
        ("fetched_at", sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True)),
        (
            "last_checked_at",
            sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        ),
        (
            "refresh_interval_minutes",
            sa.Column("refresh_interval_minutes", sa.Integer(), nullable=True),
        ),
        (
            "auto_refresh",
            sa.Column("auto_refresh", sa.Boolean(), nullable=False, server_default=sa.false()),
        ),
        (
            "supersedes_source_id",
            sa.Column("supersedes_source_id", sa.String(36), nullable=True),
        ),
    ]
    for name, column in additions:
        if name not in columns:
            op.add_column("evidence_sources", column)
    indexes = {index["name"] for index in inspector.get_indexes("evidence_sources")}
    if op.f("ix_evidence_sources_source_url") not in indexes:
        op.create_index(op.f("ix_evidence_sources_source_url"), "evidence_sources", ["source_url"])
    if op.f("ix_evidence_sources_supersedes_source_id") not in indexes:
        op.create_index(
            op.f("ix_evidence_sources_supersedes_source_id"),
            "evidence_sources",
            ["supersedes_source_id"],
        )
    foreign_keys = {
        constraint.get("name") for constraint in inspector.get_foreign_keys("evidence_sources")
    }
    name = op.f("fk_evidence_sources_supersedes_source_id")
    if name not in foreign_keys:
        if op.get_context().dialect.name == "sqlite":
            with op.batch_alter_table("evidence_sources") as batch_op:
                batch_op.create_foreign_key(
                    name,
                    "evidence_sources",
                    ["supersedes_source_id"],
                    ["id"],
                    ondelete="SET NULL",
                )
        else:
            op.create_foreign_key(
                name,
                "evidence_sources",
                "evidence_sources",
                ["supersedes_source_id"],
                ["id"],
                ondelete="SET NULL",
            )


def downgrade() -> None:
    name = op.f("fk_evidence_sources_supersedes_source_id")
    if op.get_context().dialect.name == "sqlite":
        with op.batch_alter_table("evidence_sources") as batch_op:
            batch_op.drop_constraint(name, type_="foreignkey")
    else:
        op.drop_constraint(name, "evidence_sources", type_="foreignkey")
    op.drop_index(op.f("ix_evidence_sources_supersedes_source_id"), table_name="evidence_sources")
    op.drop_index(op.f("ix_evidence_sources_source_url"), table_name="evidence_sources")
    for column in (
        "supersedes_source_id",
        "auto_refresh",
        "refresh_interval_minutes",
        "last_checked_at",
        "fetched_at",
        "last_modified",
        "etag",
        "source_url",
    ):
        op.drop_column("evidence_sources", column)
