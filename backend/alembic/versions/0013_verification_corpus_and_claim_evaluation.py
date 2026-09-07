"""Add the verification corpus and claim-evaluation tables.

Purely additive: trusted sources, their immutable corpus versions, retrievable
chunks, and the claim/verdict record behind every groundedness figure. No
existing table is altered.

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-07 17:52:47.820914
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the verification tables, skipping any a legacy database already has."""

    existing = set(sa.inspect(op.get_bind()).get_table_names())

    if "verification_sources" not in existing:
        op.create_table('verification_sources',
        sa.Column('name', sa.String(length=160), nullable=False),
        sa.Column('source_type', sa.Enum('pdf', 'json', 'csv', 'text', 'markdown', 'website', 'demo', name='verification_source_type', native_enum=False, create_constraint=True, length=40), nullable=False),
        sa.Column('original_filename', sa.String(length=255), nullable=True),
        sa.Column('source_url', sa.Text(), nullable=True),
        sa.Column('status', sa.Enum('awaiting_review', 'approved', 'rejected', 'retired', name='verification_source_status', native_enum=False, create_constraint=True, length=40), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_by', sa.String(length=120), nullable=False),
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('tenant_id', sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], name=op.f('fk_verification_sources_tenant_id'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_verification_sources')),
        sa.UniqueConstraint('tenant_id', 'name', name='uq_verification_source_name')
        )
        with op.batch_alter_table('verification_sources', schema=None) as batch_op:
            batch_op.create_index(batch_op.f('ix_verification_sources_created_at'), ['created_at'], unique=False)
            batch_op.create_index(batch_op.f('ix_verification_sources_status'), ['status'], unique=False)
            batch_op.create_index(batch_op.f('ix_verification_sources_tenant_id'), ['tenant_id'], unique=False)
            batch_op.create_index('ix_verification_sources_tenant_status', ['tenant_id', 'status'], unique=False)

    if "corpus_versions" not in existing:
        op.create_table('corpus_versions',
        sa.Column('source_id', sa.String(length=36), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('content_hash', sa.String(length=64), nullable=False),
        sa.Column('effective_from', sa.DateTime(timezone=True), nullable=True),
        sa.Column('imported_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('approved_by', sa.String(length=120), nullable=True),
        sa.Column('retired_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('source_metadata', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.CheckConstraint('version >= 1', name=op.f('ck_corpus_versions_corpus_version_positive')),
        sa.ForeignKeyConstraint(['source_id'], ['verification_sources.id'], name=op.f('fk_corpus_versions_source_id'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_corpus_versions')),
        sa.UniqueConstraint('source_id', 'version', name='uq_corpus_version_sequence')
        )
        with op.batch_alter_table('corpus_versions', schema=None) as batch_op:
            batch_op.create_index(batch_op.f('ix_corpus_versions_content_hash'), ['content_hash'], unique=False)
            batch_op.create_index(batch_op.f('ix_corpus_versions_imported_at'), ['imported_at'], unique=False)
            batch_op.create_index(batch_op.f('ix_corpus_versions_retired_at'), ['retired_at'], unique=False)
            batch_op.create_index(batch_op.f('ix_corpus_versions_source_id'), ['source_id'], unique=False)

    if "verification_chunks" not in existing:
        op.create_table('verification_chunks',
        sa.Column('corpus_version_id', sa.String(length=36), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('structured_facts', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
        sa.Column('sequence', sa.Integer(), nullable=False),
        sa.Column('token_count', sa.Integer(), nullable=False),
        sa.Column('chunk_metadata', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(['corpus_version_id'], ['corpus_versions.id'], name=op.f('fk_verification_chunks_corpus_version_id'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_verification_chunks'))
        )
        with op.batch_alter_table('verification_chunks', schema=None) as batch_op:
            batch_op.create_index(batch_op.f('ix_verification_chunks_corpus_version_id'), ['corpus_version_id'], unique=False)
            batch_op.create_index('ix_verification_chunks_version_sequence', ['corpus_version_id', 'sequence'], unique=False)

    if "evaluation_runs" not in existing:
        op.create_table('evaluation_runs',
        sa.Column('model_id', sa.String(length=36), nullable=False),
        sa.Column('trace_id', sa.String(length=36), nullable=True),
        sa.Column('evaluator_provider', sa.String(length=40), nullable=True),
        sa.Column('evaluator_model', sa.String(length=120), nullable=True),
        sa.Column('extractor_version', sa.String(length=40), nullable=False),
        sa.Column('verifier_version', sa.String(length=40), nullable=False),
        sa.Column('corpus_versions', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
        sa.Column('status', sa.Enum('pending', 'running', 'completed', 'failed', name='evaluation_run_status', native_enum=False, create_constraint=True, length=40), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('tenant_id', sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(['model_id'], ['monitored_models.id'], name=op.f('fk_evaluation_runs_model_id'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], name=op.f('fk_evaluation_runs_tenant_id'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['trace_id'], ['traces.id'], name=op.f('fk_evaluation_runs_trace_id'), ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_evaluation_runs'))
        )
        with op.batch_alter_table('evaluation_runs', schema=None) as batch_op:
            batch_op.create_index(batch_op.f('ix_evaluation_runs_created_at'), ['created_at'], unique=False)
            batch_op.create_index('ix_evaluation_runs_model_created', ['model_id', 'created_at'], unique=False)
            batch_op.create_index(batch_op.f('ix_evaluation_runs_model_id'), ['model_id'], unique=False)
            batch_op.create_index(batch_op.f('ix_evaluation_runs_status'), ['status'], unique=False)
            batch_op.create_index(batch_op.f('ix_evaluation_runs_tenant_id'), ['tenant_id'], unique=False)
            batch_op.create_index(batch_op.f('ix_evaluation_runs_trace_id'), ['trace_id'], unique=False)

    if "extracted_claims" not in existing:
        op.create_table('extracted_claims',
        sa.Column('evaluation_run_id', sa.String(length=36), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('claim_type', sa.Enum('policy', 'price', 'inventory', 'specification', 'date', 'identity', 'event', 'prediction', 'other', name='claim_type', native_enum=False, create_constraint=True, length=40), nullable=False),
        sa.Column('importance', sa.Enum('central', 'supporting', 'minor', name='claim_importance', native_enum=False, create_constraint=True, length=40), nullable=False),
        sa.Column('sequence', sa.Integer(), nullable=False),
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(['evaluation_run_id'], ['evaluation_runs.id'], name=op.f('fk_extracted_claims_evaluation_run_id'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_extracted_claims'))
        )
        with op.batch_alter_table('extracted_claims', schema=None) as batch_op:
            batch_op.create_index(batch_op.f('ix_extracted_claims_evaluation_run_id'), ['evaluation_run_id'], unique=False)
            batch_op.create_index('ix_extracted_claims_run_sequence', ['evaluation_run_id', 'sequence'], unique=False)

    if "claim_verdicts" not in existing:
        op.create_table('claim_verdicts',
        sa.Column('claim_id', sa.String(length=36), nullable=False),
        sa.Column('verdict', sa.Enum('supported', 'contradicted', 'insufficient_evidence', 'not_verifiable', 'not_applicable', name='claim_verdict_value', native_enum=False, create_constraint=True, length=40), nullable=False),
        sa.Column('evidence_chunk_id', sa.String(length=36), nullable=True),
        sa.Column('explanation', sa.Text(), nullable=True),
        sa.Column('verifier_confidence', sa.Float(), nullable=True),
        sa.Column('deterministic_match', sa.Boolean(), nullable=False),
        sa.Column('method', sa.Enum('deterministic', 'llm_verifier', 'no_evidence', name='verification_method', native_enum=False, create_constraint=True, length=40), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(['claim_id'], ['extracted_claims.id'], name=op.f('fk_claim_verdicts_claim_id'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['evidence_chunk_id'], ['verification_chunks.id'], name=op.f('fk_claim_verdicts_evidence_chunk_id'), ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_claim_verdicts'))
        )
        with op.batch_alter_table('claim_verdicts', schema=None) as batch_op:
            batch_op.create_index(batch_op.f('ix_claim_verdicts_claim_id'), ['claim_id'], unique=True)
            batch_op.create_index(batch_op.f('ix_claim_verdicts_verdict'), ['verdict'], unique=False)

def downgrade() -> None:
    """Drop the verification tables, children first."""

    existing = set(sa.inspect(op.get_bind()).get_table_names())

    if "claim_verdicts" in existing:
        with op.batch_alter_table('claim_verdicts', schema=None) as batch_op:
            batch_op.drop_index(batch_op.f('ix_claim_verdicts_verdict'))
            batch_op.drop_index(batch_op.f('ix_claim_verdicts_claim_id'))
        op.drop_table('claim_verdicts')

    if "extracted_claims" in existing:
        with op.batch_alter_table('extracted_claims', schema=None) as batch_op:
            batch_op.drop_index('ix_extracted_claims_run_sequence')
            batch_op.drop_index(batch_op.f('ix_extracted_claims_evaluation_run_id'))
        op.drop_table('extracted_claims')

    if "evaluation_runs" in existing:
        with op.batch_alter_table('evaluation_runs', schema=None) as batch_op:
            batch_op.drop_index(batch_op.f('ix_evaluation_runs_trace_id'))
            batch_op.drop_index(batch_op.f('ix_evaluation_runs_tenant_id'))
            batch_op.drop_index(batch_op.f('ix_evaluation_runs_status'))
            batch_op.drop_index(batch_op.f('ix_evaluation_runs_model_id'))
            batch_op.drop_index('ix_evaluation_runs_model_created')
            batch_op.drop_index(batch_op.f('ix_evaluation_runs_created_at'))
        op.drop_table('evaluation_runs')

    if "verification_chunks" in existing:
        with op.batch_alter_table('verification_chunks', schema=None) as batch_op:
            batch_op.drop_index('ix_verification_chunks_version_sequence')
            batch_op.drop_index(batch_op.f('ix_verification_chunks_corpus_version_id'))
        op.drop_table('verification_chunks')

    if "corpus_versions" in existing:
        with op.batch_alter_table('corpus_versions', schema=None) as batch_op:
            batch_op.drop_index(batch_op.f('ix_corpus_versions_source_id'))
            batch_op.drop_index(batch_op.f('ix_corpus_versions_retired_at'))
            batch_op.drop_index(batch_op.f('ix_corpus_versions_imported_at'))
            batch_op.drop_index(batch_op.f('ix_corpus_versions_content_hash'))
        op.drop_table('corpus_versions')

    if "verification_sources" in existing:
        with op.batch_alter_table('verification_sources', schema=None) as batch_op:
            batch_op.drop_index('ix_verification_sources_tenant_status')
            batch_op.drop_index(batch_op.f('ix_verification_sources_tenant_id'))
            batch_op.drop_index(batch_op.f('ix_verification_sources_status'))
            batch_op.drop_index(batch_op.f('ix_verification_sources_created_at'))
        op.drop_table('verification_sources')
