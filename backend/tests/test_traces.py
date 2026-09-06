"""Trace ingestion, redaction, and the diagnosis drill-down."""

from __future__ import annotations

from datetime import timedelta

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import (
    DiagnosisEvidence,
    KnowledgeDocument,
    MonitoredModel,
    Trace,
    ensure_health_policy,
    utc_now,
)
from app.redaction import content_hash, redact
from app.schemas import DimensionScores, SignalSource, TelemetryCreate, TraceCreate
from app.scoring import DIMENSION_WEIGHTS
from app.service import DriftZeroService


def _service() -> DriftZeroService:
    return DriftZeroService(Settings())


def _dimensions(groundedness: float = 90.0) -> DimensionScores:
    return DimensionScores(
        quality=90.0,
        groundedness=groundedness,
        semantic_stability=90.0,
        temporal_stability=90.0,
        safety=94.0,
        drift=90.0,
        reliability=92.0,
        latency=94.0,
        cost=90.0,
    )


# The diagnosis engine looks for a *pattern*, not a single falling dimension:
# groundedness, semantic stability and drift all deteriorating while safety and
# latency hold steady is what identifies a knowledge-freshness failure.
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
DEGRADED = DimensionScores(
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


def _telemetry(
    *,
    groundedness: float = 90.0,
    dimensions: DimensionScores | None = None,
    traces: list[TraceCreate] | None = None,
    minutes_ago: int = 0,
) -> TelemetryCreate:
    return TelemetryCreate(
        observed_at=utc_now() - timedelta(minutes=minutes_ago),
        dimensions=dimensions or _dimensions(groundedness),
        sample_size=100,
        coverage=0.95,
        source=SignalSource.SIMULATED,
        traces=traces or [],
    )


class TestTelemetryWithoutTraces:
    """The traces field is optional; existing callers must be unaffected."""

    def test_snapshot_still_records_a_window(
        self, session: Session, model: MonitoredModel
    ) -> None:
        response = _service().record_telemetry(session, model.id, _telemetry())

        assert response.trace_count == 0
        # A score must always state the period it covers, traces or not.
        assert response.window_start is not None
        assert response.window_end is not None
        assert response.window_start < response.window_end

    def test_policy_is_linked(self, session: Session, model: MonitoredModel) -> None:
        _service().record_telemetry(session, model.id, _telemetry())

        stored = session.scalar(sa.text("SELECT policy_id FROM health_snapshots"))
        # A score is meaningless without the weights behind it.
        assert stored is not None


class TestTraceIngestion:
    def test_traces_are_persisted_and_counted(
        self, session: Session, model: MonitoredModel
    ) -> None:
        now = utc_now()
        traces = [
            TraceCreate(occurred_at=now - timedelta(seconds=30), question="a"),
            TraceCreate(occurred_at=now - timedelta(seconds=10), question="b"),
        ]

        response = _service().record_telemetry(session, model.id, _telemetry(traces=traces))

        assert response.trace_count == 2
        assert session.scalar(sa.select(sa.func.count()).select_from(Trace)) == 2

    def test_window_spans_the_traces(self, session: Session, model: MonitoredModel) -> None:
        now = utc_now()
        first, last = now - timedelta(minutes=9), now - timedelta(minutes=1)
        traces = [
            TraceCreate(occurred_at=first, question="a"),
            TraceCreate(occurred_at=now - timedelta(minutes=5), question="b"),
            TraceCreate(occurred_at=last, question="c"),
        ]

        response = _service().record_telemetry(session, model.id, _telemetry(traces=traces))

        assert response.window_start == first
        assert response.window_end == last


class TestRedaction:
    def test_raw_text_is_never_stored(self, session: Session, model: MonitoredModel) -> None:
        question = "When is the fee due? Email me at priya@campus.edu"
        _service().record_telemetry(
            session,
            model.id,
            _telemetry(traces=[TraceCreate(question=question, answer="Due 14 February.")]),
        )

        trace = session.scalar(sa.select(Trace))
        assert "priya@campus.edu" not in (trace.question_redacted or "")
        assert trace.question_redacted == redact(question)

    def test_hash_is_taken_over_the_original(
        self, session: Session, model: MonitoredModel
    ) -> None:
        question = "When is the fee due? Email me at priya@campus.edu"
        _service().record_telemetry(
            session, model.id, _telemetry(traces=[TraceCreate(question=question)])
        )

        trace = session.scalar(sa.select(Trace))
        # Hashing the original is what keeps repeated questions correlatable.
        assert trace.prompt_hash == content_hash(question)
        assert trace.prompt_hash != content_hash(trace.question_redacted)
        assert trace.redaction_policy_version == "redact-v1"


class TestEvidenceDrilldown:
    @staticmethod
    def _degrade(session: Session, model: MonitoredModel) -> None:
        """Record a healthy window then a degraded one carrying bad traces."""

        service = _service()
        service.record_telemetry(session, model.id, _telemetry(dimensions=HEALTHY, minutes_ago=30))
        service.record_telemetry(
            session,
            model.id,
            _telemetry(
                dimensions=DEGRADED,
                traces=[
                    TraceCreate(
                        question=f"q{index}",
                        answer="The deadline is 14 February 2026.",
                        unsupported_claim_count=index + 1,
                        groundedness_score=30.0 - index,
                    )
                    for index in range(3)
                ],
            ),
        )

    def test_evidence_rows_are_written(self, session: Session, model: MonitoredModel) -> None:
        self._degrade(session, model)

        response = _service().diagnose_latest(session, model.id)

        rows = session.scalar(sa.select(sa.func.count()).select_from(DiagnosisEvidence))
        assert rows == len(response.evidence)
        assert rows > 0

    def test_groundedness_evidence_reaches_the_offending_traces(
        self, session: Session, model: MonitoredModel
    ) -> None:
        self._degrade(session, model)

        response = _service().diagnose_latest(session, model.id)

        grounded = next(item for item in response.evidence if item.metric == "groundedness")
        assert grounded.trace_ids, "a groundedness claim must reach the requests behind it"

        # Selection targets the requests that actually demonstrate the metric,
        # so the most unsupported answer must be among them. The stored link is
        # a set of relevant traces, not a ranking, so position is not asserted.
        linked = [session.get(Trace, trace_id) for trace_id in grounded.trace_ids]
        assert max(trace.unsupported_claim_count for trace in linked) == 3

    def test_contradicting_evidence_is_kept(
        self, session: Session, model: MonitoredModel
    ) -> None:
        self._degrade(session, model)

        response = _service().diagnose_latest(session, model.id)

        assert any(not item.supports_diagnosis for item in response.evidence)

    def test_safety_evidence_links_nothing_when_nothing_was_flagged(
        self, session: Session, model: MonitoredModel
    ) -> None:
        self._degrade(session, model)

        response = _service().diagnose_latest(session, model.id)

        safety = [item for item in response.evidence if item.metric == "safety"]
        # An unflagged request is not evidence of a safety regression.
        assert all(item.trace_ids == [] for item in safety)


class TestHealthPolicy:
    def test_is_idempotent_and_matches_the_scoring_module(self, session: Session) -> None:
        for _ in range(2):
            policy = ensure_health_policy(
                session,
                version="health-v1",
                weights=DIMENSION_WEIGHTS,
                thresholds={"healthy": 80.0, "warning": 65.0},
                minimum_sample_size=20,
                minimum_coverage=0.30,
            )
        session.commit()

        assert session.scalar(sa.text("SELECT count(*) FROM health_policies")) == 1
        assert policy.weights == DIMENSION_WEIGHTS


class TestDemoScenario:
    def test_seeds_traces_and_the_superseded_document(self, session: Session) -> None:
        demo = _service().reset_demo(session)

        assert all(snapshot.trace_count > 0 for snapshot in demo.health.snapshots)

        stale = session.scalar(sa.select(KnowledgeDocument).where(KnowledgeDocument.is_stale))
        assert stale is not None
        # The newer policy exists and is linked, which is what makes staleness
        # a citable fact rather than an assertion.
        assert stale.superseded_by_id is not None

    def test_diagnosis_evidence_reaches_real_requests(self, session: Session) -> None:
        demo = _service().reset_demo(session)

        linked = [item for item in demo.diagnosis.evidence if item.trace_ids]
        assert linked, "the demo diagnosis must drill down to traces"

        trace = session.get(Trace, linked[0].trace_ids[0])
        assert trace.is_simulated
        assert trace.retrieved_document_ids == ["policy/returns-2026-06-retired"]

    def test_scores_are_unchanged(self, session: Session) -> None:
        """Traces are recorded alongside the aggregates, never in place of them."""

        demo = _service().reset_demo(session)

        scores = [snapshot.score for snapshot in demo.health.snapshots if snapshot.score]
        assert scores == [92.0, 87.0, 74.0, 61.0]
        assert demo.health.forecast is not None
        assert demo.health.forecast.predicted_score == 48.0
