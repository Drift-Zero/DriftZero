"""Expand recovery lifecycle and persist policy decisions.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-06
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_NEW_STATES = (
    "recommended",
    "approved",
    "queued",
    "executing",
    "verifying",
    "recovered",
    "failed",
    "rejected",
    "canceled",
    "rolled_back",
)
_OLD_STATES = ("recommended", "approved", "executing", "recovered", "failed")


def _state_check(values: tuple[str, ...]) -> str:
    allowed = ", ".join(f"'{value}'" for value in values)
    return f"state IN ({allowed})"


def upgrade() -> None:
    with op.batch_alter_table("recovery_plans") as batch_op:
        batch_op.drop_constraint("recovery_state", type_="check")
        batch_op.create_check_constraint("recovery_state", _state_check(_NEW_STATES))
        batch_op.add_column(
            sa.Column("version", sa.Integer(), nullable=False, server_default="1")
        )
        batch_op.add_column(sa.Column("approved_role", sa.String(length=40), nullable=True))
        batch_op.add_column(sa.Column("approval_reason", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("rejected_reason", sa.Text(), nullable=True))

    with op.batch_alter_table("recovery_plans") as batch_op:
        batch_op.alter_column("version", existing_type=sa.Integer(), server_default=None)


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE recovery_plans SET state = 'executing' "
            "WHERE state IN ('queued', 'verifying')"
        )
    )
    op.execute(
        sa.text(
            "UPDATE recovery_plans SET state = 'failed' "
            "WHERE state IN ('rejected', 'canceled', 'rolled_back')"
        )
    )
    with op.batch_alter_table("recovery_plans") as batch_op:
        batch_op.drop_constraint("recovery_state", type_="check")
        batch_op.create_check_constraint("recovery_state", _state_check(_OLD_STATES))
        batch_op.drop_column("rejected_reason")
        batch_op.drop_column("approval_reason")
        batch_op.drop_column("approved_role")
        batch_op.drop_column("version")
