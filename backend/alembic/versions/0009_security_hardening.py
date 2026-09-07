"""Add replay-resistant telemetry identifiers.

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("health_snapshots") as batch_op:
        batch_op.add_column(sa.Column("event_id", sa.String(length=128), nullable=True))
        batch_op.add_column(
            sa.Column(
                "schema_version",
                sa.String(length=16),
                nullable=False,
                server_default="1.0",
            )
        )
        batch_op.create_unique_constraint("model_event_id", ["model_id", "event_id"])


def downgrade() -> None:
    with op.batch_alter_table("health_snapshots") as batch_op:
        batch_op.drop_constraint("model_event_id", type_="unique")
        batch_op.drop_column("schema_version")
        batch_op.drop_column("event_id")
