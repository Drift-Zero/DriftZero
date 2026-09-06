"""Complete the alert rule and alert runtime schema.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-06
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("alert_rules") as batch_op:
        batch_op.add_column(
            sa.Column("rule_type", sa.String(length=40), nullable=False, server_default="threshold")
        )
        batch_op.add_column(sa.Column("target_state", sa.String(length=40), nullable=True))
        batch_op.add_column(
            sa.Column(
                "minimum_consecutive_windows",
                sa.Integer(),
                nullable=False,
                server_default="1",
            )
        )
        batch_op.add_column(sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.alter_column("comparator", existing_type=sa.String(length=10), nullable=True)
        batch_op.alter_column("threshold", existing_type=sa.Float(), nullable=True)
        batch_op.create_check_constraint("cooldown_non_negative", "cooldown_minutes >= 0")
        batch_op.create_check_constraint(
            "consecutive_windows_positive", "minimum_consecutive_windows > 0"
        )

    op.execute(sa.text("UPDATE alert_rules SET updated_at = created_at WHERE updated_at IS NULL"))
    with op.batch_alter_table("alert_rules") as batch_op:
        batch_op.alter_column("updated_at", existing_type=sa.DateTime(timezone=True), nullable=False)

    with op.batch_alter_table("alerts") as batch_op:
        batch_op.drop_constraint("fk_alerts_rule_id", type_="foreignkey")
        batch_op.add_column(sa.Column("observed_value", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("details", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("resolution_reason", sa.Text(), nullable=True))
        batch_op.create_foreign_key(
            "fk_alerts_rule_id",
            "alert_rules",
            ["rule_id"],
            ["id"],
            ondelete="SET NULL",
        )

    op.execute(sa.text("UPDATE alerts SET details = '{}' WHERE details IS NULL"))
    with op.batch_alter_table("alerts") as batch_op:
        batch_op.alter_column("details", existing_type=sa.JSON(), nullable=False)


def downgrade() -> None:
    with op.batch_alter_table("alerts") as batch_op:
        batch_op.drop_constraint("fk_alerts_rule_id", type_="foreignkey")
        batch_op.create_foreign_key(
            "fk_alerts_rule_id",
            "alert_rules",
            ["rule_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.drop_column("resolution_reason")
        batch_op.drop_column("details")
        batch_op.drop_column("observed_value")

    with op.batch_alter_table("alert_rules") as batch_op:
        batch_op.drop_constraint("consecutive_windows_positive", type_="check")
        batch_op.drop_constraint("cooldown_non_negative", type_="check")
        batch_op.alter_column("threshold", existing_type=sa.Float(), nullable=False)
        batch_op.alter_column("comparator", existing_type=sa.String(length=10), nullable=False)
        batch_op.drop_column("updated_at")
        batch_op.drop_column("minimum_consecutive_windows")
        batch_op.drop_column("target_state")
        batch_op.drop_column("rule_type")
