"""Reconcile telemetry columns in databases previously managed by create_all.

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Repair mixed schemas left by startup ``create_all`` calls.

    ``create_all`` added new tables from revisions 0007-0010 but could not add
    revision 0009's columns to an existing ``health_snapshots`` table. This
    migration is deliberately idempotent so both normal and legacy databases
    converge on the same schema.
    """

    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("health_snapshots")}
    with op.batch_alter_table("health_snapshots") as batch_op:
        if "event_id" not in columns:
            batch_op.add_column(sa.Column("event_id", sa.String(length=128), nullable=True))
        if "schema_version" not in columns:
            batch_op.add_column(
                sa.Column(
                    "schema_version",
                    sa.String(length=16),
                    nullable=False,
                    server_default="1.0",
                )
            )

    inspector = sa.inspect(op.get_bind())
    unique_constraints = {
        constraint["name"] for constraint in inspector.get_unique_constraints("health_snapshots")
    }
    if "model_event_id" not in unique_constraints:
        with op.batch_alter_table("health_snapshots") as batch_op:
            batch_op.create_unique_constraint("model_event_id", ["model_id", "event_id"])


def downgrade() -> None:
    # Revision 0011 only restores columns already required by revision 0010's
    # expected schema, so downgrading must preserve them.
    pass
