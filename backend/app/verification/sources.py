"""Source lifecycle: import, review, approve, retire.

A source is inert until an operator approves it, and re-importing never
overwrites -- it creates the next version and retires the previous one. Both
rules exist so that "what did the model check against, and who vouched for it?"
always has an answer.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import CorpusVersion, VerificationChunk, VerificationSource
from app.schemas import VerificationSourceStatus, VerificationSourceType
from app.verification.shopassist_corpus import (
    CORPUS_NAME,
    CURRENT_CHUNKS,
    RETIRED_CHUNKS,
    RETIRED_CORPUS_NAME,
)


class SourceError(RuntimeError):
    """A source operation was rejected."""


@dataclass(frozen=True, slots=True)
class ImportedChunk:
    text: str
    structured_facts: dict[str, Any]
    metadata: dict[str, Any]


def content_hash(chunks: list[ImportedChunk]) -> str:
    """Stable digest of imported content, so a re-import that changed nothing is visible."""

    payload = json.dumps(
        [
            {"text": chunk.text, "structured_facts": chunk.structured_facts}
            for chunk in chunks
        ],
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _estimate_tokens(text: str) -> int:
    return max(1, len(text.split()))


def create_source(
    session: Session,
    *,
    tenant_id: str,
    name: str,
    source_type: VerificationSourceType,
    created_by: str,
    description: str | None = None,
    original_filename: str | None = None,
    source_url: str | None = None,
) -> VerificationSource:
    existing = session.scalar(
        select(VerificationSource).where(
            VerificationSource.tenant_id == tenant_id, VerificationSource.name == name
        )
    )
    if existing is not None:
        raise SourceError(f"A verification source named {name!r} already exists.")

    source = VerificationSource(
        name=name,
        source_type=source_type,
        description=description,
        original_filename=original_filename,
        source_url=source_url,
        status=VerificationSourceStatus.AWAITING_REVIEW,
        created_by=created_by,
    )
    source.tenant_id = tenant_id
    session.add(source)
    session.flush()
    return source


def add_version(
    session: Session,
    *,
    source: VerificationSource,
    chunks: list[ImportedChunk],
    effective_from: datetime | None = None,
    metadata: dict[str, Any] | None = None,
    retire_previous: bool = True,
) -> CorpusVersion:
    """Import content as the next immutable version of a source."""

    if not chunks:
        raise SourceError("A corpus version needs at least one evidence chunk.")

    highest = session.scalar(
        select(func.max(CorpusVersion.version)).where(CorpusVersion.source_id == source.id)
    )
    next_version = (highest or 0) + 1

    if retire_previous:
        # Only one version of a source is current at a time.
        for previous in source.versions:
            if previous.retired_at is None:
                previous.retired_at = datetime.now(UTC)

    version = CorpusVersion(
        source_id=source.id,
        version=next_version,
        content_hash=content_hash(chunks),
        effective_from=effective_from,
        source_metadata=metadata or {},
    )
    session.add(version)
    session.flush()

    for sequence, chunk in enumerate(chunks):
        session.add(
            VerificationChunk(
                corpus_version_id=version.id,
                text=chunk.text,
                structured_facts=chunk.structured_facts,
                sequence=sequence,
                token_count=_estimate_tokens(chunk.text),
                chunk_metadata=chunk.metadata,
            )
        )
    session.flush()
    # The relationship was loaded while retiring the previous versions, so the
    # cached collection predates this one. Expire it or the caller approves a
    # source that appears to have no current version.
    session.expire(source, ["versions"])
    return version


def approve_source(
    session: Session, *, source: VerificationSource, actor: str
) -> VerificationSource:
    """Approve the source and its newest version. Nothing verifies until this runs."""

    if source.status is VerificationSourceStatus.REJECTED:
        raise SourceError("A rejected source must be re-imported before it can be approved.")

    candidates = [version for version in source.versions if version.retired_at is None]
    if not candidates:
        raise SourceError("This source has no current version to approve.")

    now = datetime.now(UTC)
    source.status = VerificationSourceStatus.APPROVED
    for version in candidates:
        if version.approved_at is None:
            version.approved_at = now
            version.approved_by = actor
    session.flush()
    return source


def reject_source(
    session: Session, *, source: VerificationSource, actor: str
) -> VerificationSource:
    source.status = VerificationSourceStatus.REJECTED
    for version in source.versions:
        version.approved_at = None
        version.approved_by = None
    session.flush()
    return source


def retire_source(
    session: Session, *, source: VerificationSource, actor: str
) -> VerificationSource:
    """Retire every version. The content stays readable; it stops being truth."""

    now = datetime.now(UTC)
    source.status = VerificationSourceStatus.RETIRED
    for version in source.versions:
        if version.retired_at is None:
            version.retired_at = now
    session.flush()
    return source


def seed_shopassist_corpus(
    session: Session, *, tenant_id: str, actor: str = "demo-seeder", approve: bool = False
) -> tuple[VerificationSource, VerificationSource]:
    """Load the built-in ShopAssist sources.

    Left ``awaiting_review`` by default: the point of the demo is that an
    operator has to approve a source before it can be used.
    """

    current = session.scalar(
        select(VerificationSource).where(
            VerificationSource.tenant_id == tenant_id, VerificationSource.name == CORPUS_NAME
        )
    )
    if current is None:
        current = create_source(
            session,
            tenant_id=tenant_id,
            name=CORPUS_NAME,
            source_type=VerificationSourceType.DEMO,
            created_by=actor,
            description="Store policies, catalogue, inventory and orders for ShopAssist.",
        )
        add_version(
            session,
            source=current,
            chunks=[
                ImportedChunk(
                    text=entry["text"],
                    structured_facts=entry["structured_facts"],
                    metadata=entry.get("metadata", {}),
                )
                for entry in CURRENT_CHUNKS
            ],
            metadata={"origin": "built-in", "policy_version": "v2.1"},
        )

    retired = session.scalar(
        select(VerificationSource).where(
            VerificationSource.tenant_id == tenant_id,
            VerificationSource.name == RETIRED_CORPUS_NAME,
        )
    )
    if retired is None:
        retired = create_source(
            session,
            tenant_id=tenant_id,
            name=RETIRED_CORPUS_NAME,
            source_type=VerificationSourceType.DEMO,
            created_by=actor,
            description="Superseded returns policy, kept for historical comparison only.",
        )
        version = add_version(
            session,
            source=retired,
            chunks=[
                ImportedChunk(
                    text=entry["text"],
                    structured_facts=entry["structured_facts"],
                    metadata=entry.get("metadata", {}),
                )
                for entry in RETIRED_CHUNKS
            ],
            metadata={"origin": "built-in", "policy_version": "v1.4"},
        )
        # Retired on arrival: history, never current truth.
        version.retired_at = datetime.now(UTC)
        retired.status = VerificationSourceStatus.RETIRED

    if approve:
        approve_source(session, source=current, actor=actor)

    session.flush()
    return current, retired
