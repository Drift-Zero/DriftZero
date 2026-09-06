"""The human-review queue and feedback on automated judgements."""

from __future__ import annotations

from datetime import timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import EvaluationFeedback, MonitoredModel, ReviewQueueItem, utc_now
from app.schemas import (
    ActorRequest,
    DimensionScores,
    EvaluationFeedbackCreate,
    FeedbackTarget,
    FeedbackVerdict,
    ReviewDecisionRequest,
    ReviewState,
    SignalSource,
    TelemetryCreate,
)
from app.service import DriftZeroService, InvalidTransition, ResourceNotFound

HEALTHY = DimensionScores(
    quality=90.4,
    groundedness=92.0,
    semantic_stability=92.0,
    temporal_stability=92.0,
    safety=94.0,
    drift=92.0,
    reliability=92.0,
    latency=94.0,
    cost=91.0,
)
CRITICAL = DimensionScores(
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


def _run_recovery(session: Session, model: MonitoredModel) -> DriftZeroService:
    """Drive a full degradation → diagnosis → approved recovery → execution."""

    service = DriftZeroService(Settings())
    for offset, dimensions in ((30, HEALTHY), (0, CRITICAL)):
        service.record_telemetry(
            session,
            model.id,
            TelemetryCreate(
                observed_at=utc_now() - timedelta(minutes=offset),
                dimensions=dimensions,
                sample_size=100,
                coverage=0.95,
                source=SignalSource.SIMULATED,
            ),
        )
    service.diagnose_latest(session, model.id)
    plan = service.latest_recovery(session, model.id)
    service.approve_recovery(session, plan.id, ActorRequest(actor="operator"))
    service.execute_recovery(session, plan.id, ActorRequest(actor="operator"))
    return service


def _items(session: Session) -> list[ReviewQueueItem]:
    return list(session.scalars(sa.select(ReviewQueueItem)).all())


class TestQueueing:
    def test_a_review_action_actually_queues_work(
        self, session: Session, model: MonitoredModel
    ) -> None:
        """"Send conflicts to human review" only means something if it lands."""

        _run_recovery(session, model)

        items = _items(session)
        assert items, "the knowledge-freshness playbook routes conflicts to a human"
        assert all(ReviewState(item.state) is ReviewState.PENDING for item in items)

    def test_queued_work_links_to_its_incident(
        self, session: Session, model: MonitoredModel
    ) -> None:
        _run_recovery(session, model)

        assert all(item.incident_id is not None for item in _items(session))


class TestDecisions:
    def test_claiming_an_item_assigns_without_deciding(
        self, session: Session, model: MonitoredModel
    ) -> None:
        service = _run_recovery(session, model)
        item = _items(session)[0]

        result = service.decide_review_item(
            session,
            item.id,
            ReviewDecisionRequest(actor="reviewer", state=ReviewState.IN_REVIEW),
        )

        assert result.assigned_to == "reviewer"
        assert result.decided_by is None
        assert result.decided_at is None

    def test_a_terminal_decision_records_who_and_when(
        self, session: Session, model: MonitoredModel
    ) -> None:
        service = _run_recovery(session, model)
        item = _items(session)[0]

        result = service.decide_review_item(
            session,
            item.id,
            ReviewDecisionRequest(
                actor="reviewer", state=ReviewState.APPROVED, notes="answer was correct"
            ),
        )

        assert result.state is ReviewState.APPROVED
        assert result.decided_by == "reviewer"
        assert result.decided_at is not None
        assert result.notes == "answer was correct"

    def test_a_decided_item_cannot_be_decided_again(
        self, session: Session, model: MonitoredModel
    ) -> None:
        service = _run_recovery(session, model)
        item = _items(session)[0]
        service.decide_review_item(
            session, item.id, ReviewDecisionRequest(actor="a", state=ReviewState.REJECTED)
        )

        with pytest.raises(InvalidTransition):
            service.decide_review_item(
                session, item.id, ReviewDecisionRequest(actor="b", state=ReviewState.APPROVED)
            )

    def test_the_queue_can_be_filtered_by_state(
        self, session: Session, model: MonitoredModel
    ) -> None:
        service = _run_recovery(session, model)
        item = _items(session)[0]
        service.decide_review_item(
            session, item.id, ReviewDecisionRequest(actor="a", state=ReviewState.APPROVED)
        )

        pending = service.list_review_queue(session, model.id, state=ReviewState.PENDING)
        approved = service.list_review_queue(session, model.id, state=ReviewState.APPROVED)

        assert len(approved) == 1
        assert all(entry.state is ReviewState.PENDING for entry in pending)


class TestFeedback:
    def test_disagreement_with_a_diagnosis_is_recorded(
        self, session: Session, model: MonitoredModel
    ) -> None:
        """Evaluator output is fallible, so dissent is captured as data."""

        service = _run_recovery(session, model)
        diagnosis = service.latest_diagnosis(session, model.id)

        result = service.record_feedback(
            session,
            EvaluationFeedbackCreate(
                target_type=FeedbackTarget.DIAGNOSIS,
                target_id=diagnosis.id,
                actor="reviewer",
                verdict=FeedbackVerdict.DISAGREE,
                note="retrieval was fine; the prompt changed",
            ),
        )

        assert result.verdict is FeedbackVerdict.DISAGREE
        assert session.scalar(sa.select(sa.func.count()).select_from(EvaluationFeedback)) == 1

    def test_feedback_against_a_missing_target_is_rejected(self, session: Session) -> None:
        with pytest.raises(ResourceNotFound):
            DriftZeroService(Settings()).record_feedback(
                session,
                EvaluationFeedbackCreate(
                    target_type=FeedbackTarget.DIAGNOSIS,
                    target_id="does-not-exist",
                    actor="reviewer",
                    verdict=FeedbackVerdict.AGREE,
                ),
            )

    def test_feedback_can_be_read_back_for_a_target(
        self, session: Session, model: MonitoredModel
    ) -> None:
        service = _run_recovery(session, model)
        diagnosis = service.latest_diagnosis(session, model.id)
        for actor, verdict in (("a", FeedbackVerdict.AGREE), ("b", FeedbackVerdict.DISAGREE)):
            service.record_feedback(
                session,
                EvaluationFeedbackCreate(
                    target_type=FeedbackTarget.DIAGNOSIS,
                    target_id=diagnosis.id,
                    actor=actor,
                    verdict=verdict,
                ),
            )

        entries = service.list_feedback(session, "diagnosis", diagnosis.id)

        assert len(entries) == 2
        assert {entry.actor for entry in entries} == {"a", "b"}
