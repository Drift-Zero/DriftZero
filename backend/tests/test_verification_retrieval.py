"""Retrieval must only ever reach approved, current, same-tenant evidence."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session

from app.db import Tenant
from app.db.models import CorpusVersion, EvidenceChunk, VerificationSource
from app.schemas import VerificationSourceStatus
from app.verification.retrieval import retrieve_evidence

CURRENT_POLICY = "Electronics can be returned within 14 days with a receipt."
RETIRED_POLICY = "Electronics can be returned within 30 days with a receipt."

RETURN_FACT = {
    "facts": [
        {
            "key": "electronics_return_window_days",
            "label": "Electronics return window",
            "value": 14,
            "unit": "days",
            "terms": ["return", "electronics"],
        }
    ]
}


def build_source(
    session: Session,
    *,
    name: str,
    text: str,
    tenant_id: str | None = None,
    status: VerificationSourceStatus = VerificationSourceStatus.APPROVED,
    approved: bool = True,
    retired: bool = False,
    facts: dict | None = None,
) -> VerificationSource:
    source = VerificationSource(name=name, source_type="demo", status=status, created_by="test")
    if tenant_id is not None:
        source.tenant_id = tenant_id
    session.add(source)
    session.flush()

    version = CorpusVersion(
        source_id=source.id,
        version=1,
        content_hash=f"hash-{name}",
        approved_at=datetime.now(UTC) if approved else None,
        retired_at=datetime.now(UTC) if retired else None,
    )
    session.add(version)
    session.flush()

    session.add(
        EvidenceChunk(
            corpus_version_id=version.id,
            text=text,
            structured_facts=facts or {},
            sequence=0,
            token_count=len(text.split()),
        )
    )
    session.flush()
    return source


@pytest.fixture
def tenant_id(session: Session) -> str:
    from app.db.base import DEFAULT_TENANT_ID

    return DEFAULT_TENANT_ID


def test_approved_evidence_is_returned(session: Session, tenant_id: str) -> None:
    build_source(session, name="Returns policy", text=CURRENT_POLICY, facts=RETURN_FACT)

    found = retrieve_evidence(
        session, tenant_id=tenant_id, claim_text="Can electronics be returned within 30 days?"
    )

    assert [item.text for item in found] == [CURRENT_POLICY]
    assert found[0].exact_fact_match is True
    assert found[0].source_name == "Returns policy"


def test_an_unapproved_source_is_never_searched(session: Session, tenant_id: str) -> None:
    """A source awaiting review is inert -- nobody has vouched for it yet."""

    build_source(
        session,
        name="Draft policy",
        text=CURRENT_POLICY,
        status=VerificationSourceStatus.AWAITING_REVIEW,
        approved=False,
        facts=RETURN_FACT,
    )

    assert retrieve_evidence(session, tenant_id=tenant_id, claim_text="electronics returns") == []


def test_an_approved_source_with_an_unapproved_version_is_excluded(
    session: Session, tenant_id: str
) -> None:
    build_source(session, name="Half-approved", text=CURRENT_POLICY, approved=False)

    assert retrieve_evidence(session, tenant_id=tenant_id, claim_text="electronics returns") == []


def test_retired_evidence_is_excluded_from_current_verification(
    session: Session, tenant_id: str
) -> None:
    """The superseded policy is history, not truth."""

    build_source(
        session, name="Old returns policy", text=RETIRED_POLICY, retired=True, facts=RETURN_FACT
    )

    assert retrieve_evidence(session, tenant_id=tenant_id, claim_text="electronics returns") == []


def test_retired_evidence_is_reachable_for_explicit_historical_comparison(
    session: Session, tenant_id: str
) -> None:
    build_source(
        session, name="Old returns policy", text=RETIRED_POLICY, retired=True, facts=RETURN_FACT
    )

    found = retrieve_evidence(
        session,
        tenant_id=tenant_id,
        claim_text="electronics returns",
        include_retired=True,
    )

    assert [item.text for item in found] == [RETIRED_POLICY]
    assert found[0].retired is True


def test_another_tenants_corpus_is_never_searched(session: Session, tenant_id: str) -> None:
    other = Tenant(name="Other", slug="other")
    session.add(other)
    session.flush()
    build_source(
        session,
        name="Other tenant policy",
        text=CURRENT_POLICY,
        tenant_id=other.id,
        facts=RETURN_FACT,
    )

    assert retrieve_evidence(session, tenant_id=tenant_id, claim_text="electronics returns") == []


def test_at_most_three_chunks_are_returned(session: Session, tenant_id: str) -> None:
    for index in range(6):
        build_source(session, name=f"Policy {index}", text=f"{CURRENT_POLICY} Note {index}.")

    found = retrieve_evidence(session, tenant_id=tenant_id, claim_text="electronics returned")

    assert len(found) == 3


def test_structured_fact_matches_outrank_mere_word_overlap(
    session: Session, tenant_id: str
) -> None:
    build_source(
        session,
        name="Chatty page",
        text="Returns for electronics are a common question about returns and electronics.",
    )
    build_source(
        session, name="Returns policy", text=CURRENT_POLICY, facts=RETURN_FACT
    )

    found = retrieve_evidence(
        session, tenant_id=tenant_id, claim_text="electronics returns within 30 days"
    )

    assert found[0].source_name == "Returns policy"
    assert found[0].exact_fact_match is True


def test_an_irrelevant_claim_retrieves_nothing(session: Session, tenant_id: str) -> None:
    """No relevant approved evidence must surface as absence, not a weak guess."""

    build_source(session, name="Returns policy", text=CURRENT_POLICY, facts=RETURN_FACT)

    assert retrieve_evidence(session, tenant_id=tenant_id, claim_text="quantum tunnelling") == []
