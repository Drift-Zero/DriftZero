"""Stored forecasts and their settlement against what actually happened."""

from __future__ import annotations

from datetime import timedelta

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import HealthForecastRecord, MonitoredModel, utc_now
from app.schemas import DimensionScores, SignalSource, TelemetryCreate
from app.service import DriftZeroService


def _dimensions(value: float) -> DimensionScores:
    return DimensionScores(
        quality=value,
        groundedness=value,
        semantic_stability=value,
        temporal_stability=value,
        safety=value,
        drift=value,
        reliability=value,
        latency=value,
        cost=value,
    )


def _record(
    service: DriftZeroService,
    session: Session,
    model: MonitoredModel,
    value: float,
    *,
    minutes_ago: int,
) -> None:
    service.record_telemetry(
        session,
        model.id,
        TelemetryCreate(
            observed_at=utc_now() - timedelta(minutes=minutes_ago),
            dimensions=_dimensions(value),
            sample_size=100,
            coverage=0.95,
            source=SignalSource.SIMULATED,
        ),
    )


class TestStoring:
    def test_a_single_snapshot_predicts_nothing(
        self, session: Session, model: MonitoredModel
    ) -> None:
        """A trajectory needs at least two points; one is not a trend."""

        _record(DriftZeroService(Settings()), session, model, 92.0, minutes_ago=0)

        assert session.scalar(sa.select(sa.func.count()).select_from(HealthForecastRecord)) == 0

    def test_forecast_is_stored_when_recorded_not_when_read(
        self, session: Session, model: MonitoredModel
    ) -> None:
        service = DriftZeroService(Settings())
        _record(service, session, model, 92.0, minutes_ago=60)
        _record(service, session, model, 74.0, minutes_ago=30)

        before = session.scalar(sa.select(sa.func.count()).select_from(HealthForecastRecord))
        # Reading a timeline must not create predictions.
        service.health_timeline(session, model.id)
        service.health_timeline(session, model.id)
        after = session.scalar(sa.select(sa.func.count()).select_from(HealthForecastRecord))

        assert before == 1
        assert after == before

    def test_stored_forecast_carries_its_interval_and_target(
        self, session: Session, model: MonitoredModel
    ) -> None:
        service = DriftZeroService(Settings())
        _record(service, session, model, 92.0, minutes_ago=60)
        _record(service, session, model, 74.0, minutes_ago=30)

        record = session.scalar(sa.select(HealthForecastRecord))
        assert record.lower_bound <= record.predicted_score <= record.upper_bound
        assert record.direction == "deteriorating"
        assert record.target_at is not None
        assert record.actual_score is None


class TestSettlement:
    def test_a_later_snapshot_settles_an_elapsed_forecast(
        self, session: Session, model: MonitoredModel
    ) -> None:
        service = DriftZeroService(Settings())
        _record(service, session, model, 92.0, minutes_ago=120)
        _record(service, session, model, 74.0, minutes_ago=90)

        first = session.scalar(sa.select(HealthForecastRecord))
        assert first.actual_score is None

        # Well past the 30-minute horizon.
        _record(service, session, model, 61.0, minutes_ago=10)
        session.refresh(first)

        assert first.actual_score == 61.0

    def test_a_forecast_inside_its_horizon_is_left_open(
        self, session: Session, model: MonitoredModel
    ) -> None:
        service = DriftZeroService(Settings())
        _record(service, session, model, 92.0, minutes_ago=20)
        _record(service, session, model, 88.0, minutes_ago=15)

        first = session.scalar(
            sa.select(HealthForecastRecord).order_by(HealthForecastRecord.created_at)
        )
        _record(service, session, model, 85.0, minutes_ago=14)
        session.refresh(first)

        assert first.actual_score is None

    def test_an_unscored_snapshot_does_not_settle_anything(
        self, session: Session, model: MonitoredModel
    ) -> None:
        """Insufficient data is not evidence that a prediction was wrong."""

        service = DriftZeroService(Settings())
        _record(service, session, model, 92.0, minutes_ago=120)
        _record(service, session, model, 74.0, minutes_ago=90)
        first = session.scalar(sa.select(HealthForecastRecord))

        service.record_telemetry(
            session,
            model.id,
            TelemetryCreate(
                observed_at=utc_now(),
                dimensions=_dimensions(60.0),
                sample_size=1,  # below the gate, so no score is produced
                coverage=0.05,
                source=SignalSource.SIMULATED,
            ),
        )
        session.refresh(first)

        assert first.actual_score is None


class TestReads:
    def test_lists_most_recent_first(self, session: Session, model: MonitoredModel) -> None:
        service = DriftZeroService(Settings())
        _record(service, session, model, 92.0, minutes_ago=60)
        _record(service, session, model, 80.0, minutes_ago=40)
        _record(service, session, model, 70.0, minutes_ago=20)

        forecasts = service.list_forecasts(session, model.id)

        assert len(forecasts) == 2
        assert forecasts[0].created_at >= forecasts[-1].created_at
