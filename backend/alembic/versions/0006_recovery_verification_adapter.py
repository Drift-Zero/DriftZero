"""Persist adapter state and real-telemetry verification requirements.

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-06
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("recovery_commands") as batch_op:
        batch_op.drop_constraint("recovery_command_type", type_="check")
        batch_op.create_check_constraint(
            "recovery_command_type",
            "command_type IN ('execute', 'rollback', 'verify')",
        )
        batch_op.add_column(sa.Column("snapshot_id", sa.String(length=36), nullable=True))
        batch_op.create_foreign_key(
            "snapshot",
            "health_snapshots",
            ["snapshot_id"],
            ["id"],
            ondelete="SET NULL",
        )

    with op.batch_alter_table("recovery_executions") as batch_op:
        batch_op.add_column(
            sa.Column("external_operation_id", sa.String(length=160), nullable=True)
        )
        batch_op.add_column(
            sa.Column("configuration_verified_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(sa.Column("config_before", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("config_after", sa.JSON(), nullable=True))

    op.execute(
        sa.text(
            "UPDATE recovery_executions SET config_before = '{}', config_after = '{}' "
            "WHERE config_before IS NULL OR config_after IS NULL"
        )
    )
    with op.batch_alter_table("recovery_executions") as batch_op:
        batch_op.alter_column("config_before", existing_type=sa.JSON(), nullable=False)
        batch_op.alter_column("config_after", existing_type=sa.JSON(), nullable=False)

    with op.batch_alter_table("verification_runs") as batch_op:
        batch_op.add_column(
            sa.Column("required_coverage", sa.Float(), nullable=False, server_default="0.9")
        )
        batch_op.add_column(
            sa.Column("observed_coverage", sa.Float(), nullable=False, server_default="0")
        )
        batch_op.create_check_constraint(
            "required_coverage_range", "required_coverage >= 0 AND required_coverage <= 1"
        )
        batch_op.create_check_constraint(
            "observed_coverage_range", "observed_coverage >= 0 AND observed_coverage <= 1"
        )

    with op.batch_alter_table("verification_runs") as batch_op:
        batch_op.alter_column("required_coverage", existing_type=sa.Float(), server_default=None)
        batch_op.alter_column("observed_coverage", existing_type=sa.Float(), server_default=None)


def downgrade() -> None:
    op.execute(
        sa.text("UPDATE recovery_commands SET command_type = 'execute' WHERE command_type = 'verify'")
    )
    with op.batch_alter_table("verification_runs") as batch_op:
        batch_op.drop_constraint("observed_coverage_range", type_="check")
        batch_op.drop_constraint("required_coverage_range", type_="check")
        batch_op.drop_column("observed_coverage")
        batch_op.drop_column("required_coverage")

    with op.batch_alter_table("recovery_executions") as batch_op:
        batch_op.drop_column("config_after")
        batch_op.drop_column("config_before")
        batch_op.drop_column("configuration_verified_at")
        batch_op.drop_column("external_operation_id")

    with op.batch_alter_table("recovery_commands") as batch_op:
        batch_op.drop_constraint("snapshot", type_="foreignkey")
        batch_op.drop_column("snapshot_id")
        batch_op.drop_constraint("recovery_command_type", type_="check")
        batch_op.create_check_constraint(
            "recovery_command_type", "command_type IN ('execute', 'rollback')"
        )
