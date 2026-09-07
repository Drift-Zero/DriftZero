"""Add encrypted credentials and connection check evidence.

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("model_connections") as batch_op:
        batch_op.add_column(sa.Column("credential_ciphertext", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("ingest_key_hash", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("discovered_metadata", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("last_status_code", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("last_latency_ms", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("last_error", sa.Text(), nullable=True))
        batch_op.create_unique_constraint("ingest_key", ["ingest_key_hash"])

    op.execute(sa.text("UPDATE model_connections SET discovered_metadata = '{}'"))
    with op.batch_alter_table("model_connections") as batch_op:
        batch_op.alter_column(
            "discovered_metadata", existing_type=sa.JSON(), nullable=False
        )


def downgrade() -> None:
    with op.batch_alter_table("model_connections") as batch_op:
        batch_op.drop_constraint("ingest_key", type_="unique")
        batch_op.drop_column("last_error")
        batch_op.drop_column("last_latency_ms")
        batch_op.drop_column("last_status_code")
        batch_op.drop_column("discovered_metadata")
        batch_op.drop_column("ingest_key_hash")
        batch_op.drop_column("credential_ciphertext")
