"""Groundedness and drift are computed from trace evidence when a caller
doesn't already supply them, rather than being left as a missing dimension."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy.orm import Session

from app.config import Settings
from app.db import MonitoredModel, utc_now
from app.schemas import DimensionScores, SignalSource, TelemetryCreate, TraceCreate
from app.service import DriftZeroService


def _service() -> DriftZeroService:
    return DriftZeroService(Settings())


def _dimensions_without(*missing: str) -> DimensionScores:
    values = {
        "quality": 90.0,
        "groundedness": 90.0,
        "semantic_stability": 90.0,
        "temporal_stability": 90.0,
        "safety": 94.0,
        "drift": 90.0,
        "reliability": 92.0,
        "latency": 94.0,
        "cost": 90.0,
    }
    for name in missing:
        values[name] = None
    return DimensionScores(**values)


class TestGroundednessInference:
    def test_computed_from_citation_and_unsupported_claim_counts(
        self, session: Session, model: MonitoredModel
    ) -> None:
        now = utc_now()
        traces = [
            TraceCreate(
                occurred_at=now - timedelta(minutes=1),
                citation_count=2,
                unsupported_claim_count=0,
                retrieved_document_ids=["doc-1"],
            ),
            TraceCreate(
                occurred_at=now,
                citation_count=0,
                unsupported_claim_count=2,
                retrieved_document_ids=[],
            ),
        ]
        response = _service().record_telemetry(
            session,
            model.id,
            TelemetryCreate(
                observed_at=now,
                dimensions=_dimensions_without("groundedness"),
                sample_size=100,
                coverage=0.95,
                source=SignalSource.SIMULATED,
                traces=traces,
            ),
        )

        # Fully-cited trace scores 100, fully-unsupported-with-no-retrieval scores 0.
        assert response.dimensions.groundedness == 50.0
        assert "groundedness" not in response.missing_dimensions

    def test_explicit_dimension_score_is_never_overridden(
        self, session: Session, model: MonitoredModel
    ) -> None:
        now = utc_now()
        response = _service().record_telemetry(
            session,
            model.id,
            TelemetryCreate(
                observed_at=now,
                dimensions=_dimensions_without(),  # groundedness explicitly 90.0
                sample_size=100,
                coverage=0.95,
                source=SignalSource.SIMULATED,
                traces=[
                    TraceCreate(
                        occurred_at=now,
                        citation_count=0,
                        unsupported_claim_count=5,
                        retrieved_document_ids=[],
                    )
                ],
            ),
        )

        assert response.dimensions.groundedness == 90.0

    def test_no_usable_trace_signal_leaves_dimension_missing(
        self, session: Session, model: MonitoredModel
    ) -> None:
        now = utc_now()
        response = _service().record_telemetry(
            session,
            model.id,
            TelemetryCreate(
                observed_at=now,
                dimensions=_dimensions_without("groundedness"),
                sample_size=100,
                coverage=0.95,
                source=SignalSource.SIMULATED,
                traces=[TraceCreate(occurred_at=now)],
            ),
        )

        assert response.dimensions.groundedness is None
        assert "groundedness" in response.missing_dimensions


class TestDriftInference:
    def test_stable_retrieval_distribution_scores_high(
        self, session: Session, model: MonitoredModel
    ) -> None:
        # The baseline lookup mirrors the length of the window being scored, so
        # the fixture places the preceding snapshot's traces inside that
        # equal-length lookback rather than at an arbitrary earlier time.
        service = _service()
        now = utc_now()
        service.record_telemetry(
            session,
            model.id,
            TelemetryCreate(
                observed_at=now - timedelta(minutes=6),
                dimensions=_dimensions_without(),
                sample_size=100,
                coverage=0.95,
                source=SignalSource.SIMULATED,
                traces=[
                    TraceCreate(
                        occurred_at=now - timedelta(minutes=6), retrieved_document_ids=["doc-1"]
                    )
                ],
            ),
        )

        current_traces = [
            TraceCreate(occurred_at=now - timedelta(minutes=4), retrieved_document_ids=["doc-1"]),
            TraceCreate(occurred_at=now - timedelta(minutes=1), retrieved_document_ids=["doc-1"]),
        ]
        response = service.record_telemetry(
            session,
            model.id,
            TelemetryCreate(
                observed_at=now,
                dimensions=_dimensions_without("drift"),
                sample_size=100,
                coverage=0.95,
                source=SignalSource.SIMULATED,
                traces=current_traces,
            ),
        )

        assert response.dimensions.drift == 100.0

    def test_shifted_retrieval_distribution_scores_low(
        self, session: Session, model: MonitoredModel
    ) -> None:
        service = _service()
        now = utc_now()
        service.record_telemetry(
            session,
            model.id,
            TelemetryCreate(
                observed_at=now - timedelta(minutes=6),
                dimensions=_dimensions_without(),
                sample_size=100,
                coverage=0.95,
                source=SignalSource.SIMULATED,
                traces=[
                    TraceCreate(
                        occurred_at=now - timedelta(minutes=6), retrieved_document_ids=["doc-old"]
                    )
                ],
            ),
        )

        response = service.record_telemetry(
            session,
            model.id,
            TelemetryCreate(
                observed_at=now,
                dimensions=_dimensions_without("drift"),
                sample_size=100,
                coverage=0.95,
                source=SignalSource.SIMULATED,
                traces=[
                    TraceCreate(
                        occurred_at=now - timedelta(minutes=4), retrieved_document_ids=["doc-new"]
                    ),
                    TraceCreate(
                        occurred_at=now - timedelta(minutes=1), retrieved_document_ids=["doc-new"]
                    ),
                ],
            ),
        )

        assert response.dimensions.drift == 0.0

    def test_no_baseline_history_leaves_dimension_missing(
        self, session: Session, model: MonitoredModel
    ) -> None:
        now = utc_now()
        response = _service().record_telemetry(
            session,
            model.id,
            TelemetryCreate(
                observed_at=now,
                dimensions=_dimensions_without("drift"),
                sample_size=100,
                coverage=0.95,
                source=SignalSource.SIMULATED,
                traces=[
                    TraceCreate(occurred_at=now, retrieved_document_ids=["doc-1"]),
                ],
            ),
        )

        assert response.dimensions.drift is None
        assert "drift" in response.missing_dimensions
