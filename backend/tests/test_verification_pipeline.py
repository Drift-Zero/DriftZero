"""The stale-policy scenario, end to end, with no evaluator configured."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.db.base import DEFAULT_TENANT_ID
from app.db.models import MonitoredModel
from app.schemas import ClaimVerdictValue, EvaluationRunStatus, VerificationMethod
from app.verification.pipeline import evaluate_response
from app.verification.sources import seed_shopassist_corpus

QUESTION = "Can I return headphones after 20 days?"
STALE_ANSWER = "Yes. Headphones can be returned within 30 days."
RECOVERED_ANSWER = "Electronics can be returned within 14 days with a receipt."


@pytest.fixture
def shop_model(session: Session) -> MonitoredModel:
    model = MonitoredModel(name="ShopAssist", provider="demo-adapter", environment="simulation")
    session.add(model)
    session.flush()
    return model


def test_an_unapproved_corpus_verifies_nothing(session: Session, shop_model) -> None:
    """The source is loaded but not approved, so nothing may be checked against it."""

    seed_shopassist_corpus(session, tenant_id=DEFAULT_TENANT_ID, approve=False)

    result = evaluate_response(
        session,
        tenant_id=DEFAULT_TENANT_ID,
        model_id=shop_model.id,
        question=QUESTION,
        answer=STALE_ANSWER,
    )

    assert result.claims
    assert all(
        claim.verdict is ClaimVerdictValue.INSUFFICIENT_EVIDENCE for claim in result.claims
    )
    # Unverifiable is not a hallucination.
    assert result.groundedness.confirmed_hallucination_rate == 0.0


def test_the_stale_answer_is_contradicted_once_the_source_is_approved(
    session: Session, shop_model
) -> None:
    seed_shopassist_corpus(session, tenant_id=DEFAULT_TENANT_ID, approve=True)

    result = evaluate_response(
        session,
        tenant_id=DEFAULT_TENANT_ID,
        model_id=shop_model.id,
        question=QUESTION,
        answer=STALE_ANSWER,
    )

    contradicted = [
        claim for claim in result.claims if claim.verdict is ClaimVerdictValue.CONTRADICTED
    ]
    assert contradicted, [claim.verdict for claim in result.claims]

    claim = contradicted[0]
    assert claim.method is VerificationMethod.DETERMINISTIC
    assert "14 days" in claim.explanation
    assert "30 days" in claim.explanation
    assert claim.evidence_chunk_id is not None

    assert result.groundedness.groundedness == 0.0
    assert result.groundedness.confirmed_hallucination_rate == 100.0
    assert "100 x 0 /" in result.groundedness.formula


def test_the_recovered_answer_is_supported(session: Session, shop_model) -> None:
    seed_shopassist_corpus(session, tenant_id=DEFAULT_TENANT_ID, approve=True)

    result = evaluate_response(
        session,
        tenant_id=DEFAULT_TENANT_ID,
        model_id=shop_model.id,
        question=QUESTION,
        answer=RECOVERED_ANSWER,
    )

    assert any(claim.verdict is ClaimVerdictValue.SUPPORTED for claim in result.claims)
    assert result.groundedness.groundedness == 100.0
    assert result.groundedness.confirmed_hallucination_rate == 0.0


def test_recovery_improves_the_metrics(session: Session, shop_model) -> None:
    """The before/after the demo turns on."""

    seed_shopassist_corpus(session, tenant_id=DEFAULT_TENANT_ID, approve=True)

    before = evaluate_response(
        session,
        tenant_id=DEFAULT_TENANT_ID,
        model_id=shop_model.id,
        question=QUESTION,
        answer=STALE_ANSWER,
    )
    after = evaluate_response(
        session,
        tenant_id=DEFAULT_TENANT_ID,
        model_id=shop_model.id,
        question=QUESTION,
        answer=RECOVERED_ANSWER,
    )

    assert before.groundedness.groundedness is not None
    assert after.groundedness.groundedness is not None
    assert after.groundedness.groundedness > before.groundedness.groundedness


def test_the_retired_policy_is_never_used_as_current_truth(
    session: Session, shop_model
) -> None:
    """The retired 30-day rule would make the stale answer look correct."""

    seed_shopassist_corpus(session, tenant_id=DEFAULT_TENANT_ID, approve=True)

    result = evaluate_response(
        session,
        tenant_id=DEFAULT_TENANT_ID,
        model_id=shop_model.id,
        question=QUESTION,
        answer=STALE_ANSWER,
    )

    cited = {
        item.source_name
        for claim in result.claims
        for item in claim.evidence
    }
    assert not any("retired" in name.lower() for name in cited)


def test_the_run_and_its_reasoning_chain_are_persisted(session: Session, shop_model) -> None:
    seed_shopassist_corpus(session, tenant_id=DEFAULT_TENANT_ID, approve=True)

    result = evaluate_response(
        session,
        tenant_id=DEFAULT_TENANT_ID,
        model_id=shop_model.id,
        question=QUESTION,
        answer=STALE_ANSWER,
    )

    from app.db.models import EvaluationRun

    run = session.get(EvaluationRun, result.run_id)
    assert run is not None
    assert run.status is EvaluationRunStatus.COMPLETED
    assert run.corpus_versions
    assert len(run.claims) == len(result.claims)
    assert all(claim.verdict is not None for claim in run.claims)


def test_no_evaluator_is_required(session: Session, shop_model) -> None:
    """The whole path runs offline, so a demo cannot fail on a provider outage."""

    seed_shopassist_corpus(session, tenant_id=DEFAULT_TENANT_ID, approve=True)

    result = evaluate_response(
        session,
        tenant_id=DEFAULT_TENANT_ID,
        model_id=shop_model.id,
        question=QUESTION,
        answer=STALE_ANSWER,
        provider=None,
    )

    assert result.evaluator_provider is None
    assert result.groundedness.groundedness is not None
