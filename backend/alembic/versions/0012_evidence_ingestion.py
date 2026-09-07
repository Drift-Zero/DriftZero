"""Add trusted evidence sources and exact, locatable chunks.

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Some early DriftZero deployments called Base.metadata.create_all before
    # adopting startup migrations. In that mixed state the current application
    # model has already created both tables even though Alembic is at 0011.
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if {"evidence_sources", "evidence_chunks"} <= existing:
        return
    if existing & {"evidence_sources", "evidence_chunks"}:
        raise RuntimeError("Partial evidence schema detected; manual repair is required.")
    op.create_table(
        "evidence_sources",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("model_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("media_type", sa.String(100), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("corpus_version", sa.String(80), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("extraction_method", sa.String(40), nullable=False),
        sa.Column("llm_provider", sa.String(40), nullable=True),
        sa.Column("llm_model", sa.String(120), nullable=True),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column("approved_by", sa.String(120), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.CheckConstraint(
            "status IN ('awaiting_review', 'approved', 'rejected', 'retired')",
            name=op.f("ck_evidence_sources_evidence_status"),
        ),
        sa.CheckConstraint(
            "chunk_count >= 0",
            name=op.f("ck_evidence_sources_evidence_chunk_count_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["model_id"],
            ["monitored_models.id"],
            ondelete="CASCADE",
            name=op.f("fk_evidence_sources_model_id"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            ondelete="CASCADE",
            name=op.f("fk_evidence_sources_tenant_id"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_evidence_sources")),
        sa.UniqueConstraint("model_id", "content_hash", name="model_evidence_hash"),
    )
    op.create_index(op.f("ix_evidence_sources_model_id"), "evidence_sources", ["model_id"])
    op.create_index(
        op.f("ix_evidence_sources_content_hash"), "evidence_sources", ["content_hash"]
    )
    op.create_index(
        op.f("ix_evidence_sources_corpus_version"), "evidence_sources", ["corpus_version"]
    )
    op.create_index(op.f("ix_evidence_sources_status"), "evidence_sources", ["status"])
    op.create_index(op.f("ix_evidence_sources_tenant_id"), "evidence_sources", ["tenant_id"])

    op.create_table(
        "evidence_chunks",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("source_id", sa.String(36), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("evidence_quote", sa.Text(), nullable=False),
        sa.Column("locator", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("validation_status", sa.String(24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "ordinal >= 0", name=op.f("ck_evidence_chunks_evidence_ordinal_non_negative")
        ),
        sa.CheckConstraint(
            "validation_status IN ('deterministic', 'exact_match')",
            name=op.f("ck_evidence_chunks_evidence_validation_status"),
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["evidence_sources.id"],
            ondelete="CASCADE",
            name=op.f("fk_evidence_chunks_source_id"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_evidence_chunks")),
        sa.UniqueConstraint("source_id", "ordinal", name="evidence_source_ordinal"),
    )
    op.create_index(op.f("ix_evidence_chunks_source_id"), "evidence_chunks", ["source_id"])
    op.create_index(
        op.f("ix_evidence_chunks_content_hash"), "evidence_chunks", ["content_hash"]
    )


def downgrade() -> None:
    op.drop_table("evidence_chunks")
    op.drop_table("evidence_sources")
