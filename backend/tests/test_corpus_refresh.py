"""A recovery that says it refreshed the corpus must actually refresh it."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import KnowledgeDocument, KnowledgeSource, KnowledgeStatus, ModelVersion
from app.recovery import RecoveryActionResult, RecoveryExecutionResult
from app.schemas import (
    DimensionScores,
    RecoveryDecisionRequest,
    RecoveryExecuteRequest,
)
from app.service import DriftZeroService

UNRECOVERED = DimensionScores(
    quality=61.0,
    groundedness=30.0,
    semantic_stability=35.0,
    temporal_stability=61.0,
    safety=94.0,
    drift=58.0,
    reliability=88.0,
    latency=94.0,
    cost=85.0,
)


class FailingAdapter:
    """Actions apply, but health is not restored, so verification fails."""

    simulation = True

    def execute_action(
        self, *, model_id: str, plan_id: str, action: object
    ) -> RecoveryActionResult:
        del model_id, plan_id, action
        return RecoveryActionResult(succeeded=True, affected_traffic_pct=100.0, detail={})

    def rollback_action(
        self, *, model_id: str, plan_id: str, action: object
    ) -> RecoveryActionResult:
        del model_id, plan_id, action
        return RecoveryActionResult(succeeded=True, affected_traffic_pct=100.0, detail={})

    def execute(self, *, model_id: str, plan_id: str) -> RecoveryExecutionResult:
        del model_id, plan_id
        return RecoveryExecutionResult(
            dimensions=UNRECOVERED,
            evaluated_requests=50,
            coverage=0.98,
            summary="did not take effect",
        )


class RefusingAdapter(FailingAdapter):
    """The corpus refresh step itself refuses."""

    def execute_action(
        self, *, model_id: str, plan_id: str, action: object
    ) -> RecoveryActionResult:
        if action.code == "refresh_retrieval_index":
            return RecoveryActionResult(
                succeeded=False, affected_traffic_pct=0.0, detail={}, error="refused"
            )
        return super().execute_action(model_id=model_id, plan_id=plan_id, action=action)


def _run_demo_recovery(session: Session, adapter: object | None = None) -> DriftZeroService:
    """Seed the CampusGPT scenario and drive it through recovery."""

    service = DriftZeroService(Settings(), recovery_adapter=adapter)
    demo = service.reset_demo(session)
    plan_id = demo.recovery.id
    service.approve_recovery(session, plan_id, RecoveryDecisionRequest(actor="operator"))
    service.execute_recovery(
        session,
        plan_id,
        RecoveryExecuteRequest(actor="operator", idempotency_key="execute-0001"),
    )
    return service


def _source(session: Session) -> KnowledgeSource:
    return session.scalars(sa.select(KnowledgeSource)).one()


def _superseding(session: Session) -> KnowledgeDocument:
    return session.scalars(
        sa.select(KnowledgeDocument).where(KnowledgeDocument.is_stale.is_(False))
    ).one()


def _superseded(session: Session) -> KnowledgeDocument:
    return session.scalars(
        sa.select(KnowledgeDocument).where(KnowledgeDocument.is_stale.is_(True))
    ).one()


class TestSuccessfulRefresh:
    def test_the_source_becomes_fresh(self, session: Session) -> None:
        _run_demo_recovery(session)

        source = _source(session)
        assert KnowledgeStatus(source.status) is KnowledgeStatus.FRESH
        assert source.last_refreshed_at is not None

    def test_the_superseding_document_is_finally_indexed(self, session: Session) -> None:
        """This is the actual fix: it was never indexed, which is why the
        retriever kept returning the older policy."""

        service = DriftZeroService(Settings())
        demo = service.reset_demo(session)
        assert _superseding(session).indexed_at is None, "precondition: the bug"

        service.approve_recovery(
            session, demo.recovery.id, RecoveryDecisionRequest(actor="operator")
        )
        service.execute_recovery(
            session,
            demo.recovery.id,
            RecoveryExecuteRequest(actor="operator", idempotency_key="execute-0002"),
        )

        assert _superseding(session).indexed_at is not None

    def test_the_corpus_version_moves(self, session: Session) -> None:
        _run_demo_recovery(session)

        # The seeded stale corpus; refreshing must leave it behind.
        assert _source(session).corpus_version != "2026-01-14"

    def test_the_superseded_document_stays_stale(self, session: Session) -> None:
        """It really was superseded. That is a fact about the document, not a
        symptom to be cleared by a recovery."""

        _run_demo_recovery(session)

        superseded = _superseded(session)
        assert superseded.is_stale is True
        assert superseded.superseded_by_id is not None

    def test_the_refresh_is_audited(self, session: Session) -> None:
        service = _run_demo_recovery(session)

        model_id = _source(session).model_id
        events = [event.event_type for event in service.audit_events(session, model_id)]
        assert "knowledge.refreshed" in events


class TestRefreshIsNotClaimedFalsely:
    def test_a_refused_refresh_leaves_the_corpus_alone(self, session: Session) -> None:
        """No recording a fix that the adapter declined to make."""

        _run_demo_recovery(session, RefusingAdapter())

        source = _source(session)
        assert KnowledgeStatus(source.status) is KnowledgeStatus.STALE
        assert _superseding(session).indexed_at is None

    def test_a_failed_verification_still_refreshed_what_was_applied(
        self, session: Session
    ) -> None:
        """The refresh step itself succeeded, so the corpus really did change;
        the overall recovery failing does not un-index a document."""

        _run_demo_recovery(session, FailingAdapter())

        assert _superseding(session).indexed_at is not None


class TestControlledInputs:
    def test_no_active_version_refreshes_without_raising(self, session: Session) -> None:
        """The demo model registers no version; refreshing must still work."""

        _run_demo_recovery(session)

        assert KnowledgeStatus(_source(session).status) is KnowledgeStatus.FRESH
        assert session.scalar(sa.select(sa.func.count()).select_from(ModelVersion)) == 0
