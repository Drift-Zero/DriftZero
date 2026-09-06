"""Add the durable recovery command queue.

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-06
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "recovery_commands",
        sa.Column("plan_id", sa.String(length=36), nullable=False),
        sa.Column(
            "command_type",
            sa.Enum(
                "execute",
                "rollback",
                name="recovery_command_type",
                native_enum=False,
                create_constraint=True,
                length=40,
            ),
            nullable=False,
        ),
        sa.Column(
            "state",
            sa.Enum(
                "pending",
                "running",
                "succeeded",
                "failed",
                "canceled",
                name="recovery_command_state",
                native_enum=False,
                create_constraint=True,
                length=40,
            ),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(length=120), nullable=False),
        sa.Column("actor", sa.String(length=120), nullable=False),
        sa.Column("actor_role", sa.String(length=40), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("max_traffic_pct", sa.Float(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.CheckConstraint("attempt >= 0", name=op.f("ck_recovery_commands_attempt_non_negative")),
        sa.CheckConstraint(
            "max_attempts >= 1", name=op.f("ck_recovery_commands_max_attempts_positive")
        ),
        sa.CheckConstraint(
            "max_traffic_pct >= 0 AND max_traffic_pct <= 100",
            name=op.f("ck_recovery_commands_max_traffic_range"),
        ),
        sa.ForeignKeyConstraint(
            ["plan_id"],
            ["recovery_plans.id"],
            name=op.f("fk_recovery_commands_plan_id"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_recovery_commands")),
        sa.UniqueConstraint("idempotency_key", name="idempotency_key"),
    )
    with op.batch_alter_table("recovery_commands") as batch_op:
        batch_op.create_index("ix_recovery_commands_claim", ["state", "available_at"])
        batch_op.create_index(batch_op.f("ix_recovery_commands_plan_id"), ["plan_id"])
        batch_op.create_index(batch_op.f("ix_recovery_commands_state"), ["state"])


def downgrade() -> None:
    with op.batch_alter_table("recovery_commands") as batch_op:
        batch_op.drop_index(batch_op.f("ix_recovery_commands_state"))
        batch_op.drop_index(batch_op.f("ix_recovery_commands_plan_id"))
        batch_op.drop_index("ix_recovery_commands_claim")
    op.drop_table("recovery_commands")
