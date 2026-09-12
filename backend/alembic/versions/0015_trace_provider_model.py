"""Store the provider model used for an observed interaction.

Revision ID: 0015
Revises: 0014
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("traces")}
    if "model_name" not in columns:
        op.add_column("traces", sa.Column("model_name", sa.String(length=160), nullable=True))


def downgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("traces")}
    if "model_name" in columns:
        op.drop_column("traces", "model_name")
