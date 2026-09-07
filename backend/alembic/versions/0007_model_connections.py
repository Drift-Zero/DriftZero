"""Add unified model connection descriptors.

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "model_connections",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("model_id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("url", sa.String(length=2000), nullable=True),
        sa.Column("repository", sa.String(length=240), nullable=True),
        sa.Column("branch", sa.String(length=160), nullable=True),
        sa.Column("api_endpoint", sa.String(length=2000), nullable=True),
        sa.Column("auth_scheme", sa.String(length=40), nullable=True),
        sa.Column("credential_configured", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="needs_setup"),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["model_id"], ["monitored_models.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("model_id", "kind", "name", name="model_connection_identity"),
    )
    op.create_index("ix_model_connections_model_id", "model_connections", ["model_id"])
    op.create_index("ix_model_connections_tenant_id", "model_connections", ["tenant_id"])
    op.create_index("ix_model_connections_kind", "model_connections", ["kind"])


def downgrade() -> None:
    op.drop_index("ix_model_connections_kind", table_name="model_connections")
    op.drop_index("ix_model_connections_tenant_id", table_name="model_connections")
    op.drop_index("ix_model_connections_model_id", table_name="model_connections")
    op.drop_table("model_connections")
