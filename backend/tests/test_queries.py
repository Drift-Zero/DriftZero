"""The persistence helpers, including the hand-off to the scoring engine."""

from __future__ import annotations

from datetime import timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.db import (
    Database,
    HealthState,
    MonitoredModel,
    Tenant,
    Trace,
    latest_snapshot,
    purge_expired_traces,
    reset_all_data,
    snapshot_timeline,
    utc_now,
)
from app.scoring import forecast_health
from tests.conftest import make_snapshot


def _count(session: Session, entity: type) -> int:
    return session.execute(sa.select(sa.func.count()).select_from(entity)).scalar() or 0


class TestSnapshotTimeline:
    def test_returns_points_oldest_first(self, session: Session, model: MonitoredModel) -> None:
        now = utc_now()
        for offset, score in ((30, 92.0), (20, 87.0), (10, 74.0)):
            session.add(
                make_snapshot(model.id, observed_at=now - timedelta(minutes=offset), score=score)
            )
        session.commit()

        points = snapshot_timeline(session, model.id)

        assert [score for _, score in points] == [92.0, 87.0, 74.0]
        assert points[0][0] < points[-1][0]

    def test_excludes_unscored_snapshots(self, session: Session, model: MonitoredModel) -> None:
        """An insufficient-data snapshot must not be read as a health of zero."""

        now = utc_now()
        session.add(make_snapshot(model.id, observed_at=now - timedelta(minutes=10), score=88.0))
        session.add(
            make_snapshot(
                model.id, observed_at=now, score=None, state=HealthState.INSUFFICIENT_DATA
            )
        )
        session.commit()

        assert [score for _, score in snapshot_timeline(session, model.id)] == [88.0]

    def test_feeds_the_forecast_engine(self, session: Session, model: MonitoredModel) -> None:
        """End-to-end: stored snapshots drive a real forecast.

        This is the integration that fails outright if timestamps come back
        naive, because forecast_health subtracts two of them.
        """

        now = utc_now()
        for offset, score in ((45, 92.0), (30, 87.0), (15, 74.0), (0, 61.0)):
            session.add(
                make_snapshot(model.id, observed_at=now - timedelta(minutes=offset), score=score)
            )
        session.commit()

        forecast = forecast_health(snapshot_timeline(session, model.id), horizon_minutes=30)

        assert forecast is not None
        assert forecast.direction == "deteriorating"
        assert forecast.predicted_score < 61.0
        assert forecast.lower_bound <= forecast.predicted_score <= forecast.upper_bound


class TestLatestSnapshot:
    def test_returns_the_most_recent(self, session: Session, model: MonitoredModel) -> None:
        now = utc_now()
        session.add(make_snapshot(model.id, observed_at=now - timedelta(minutes=5), score=90.0))
        session.add(make_snapshot(model.id, observed_at=now, score=61.0))
        session.commit()

        found = latest_snapshot(session, model.id)
        assert found is not None
        assert found.score == 61.0

    def test_returns_none_for_a_model_without_snapshots(
        self, session: Session, model: MonitoredModel
    ) -> None:
        assert latest_snapshot(session, model.id) is None


class TestRetention:
    def test_purges_only_traces_past_the_window(
        self, session: Session, model: MonitoredModel
    ) -> None:
        model.retention_days = 7
        now = utc_now()
        session.add(Trace(model_id=model.id, occurred_at=now - timedelta(days=30)))
        session.add(Trace(model_id=model.id, occurred_at=now - timedelta(days=1)))
        session.commit()

        removed = purge_expired_traces(session, model, now=now)
        session.commit()

        assert removed == 1
        assert _count(session, Trace) == 1


class TestReset:
    def test_clears_every_table_but_keeps_the_tenant(
        self, session: Session, model: MonitoredModel
    ) -> None:
        session.add(make_snapshot(model.id))
        session.add(Trace(model_id=model.id, occurred_at=utc_now()))
        session.commit()

        reset_all_data(session)
        session.commit()

        assert _count(session, MonitoredModel) == 0
        assert _count(session, Trace) == 0
        assert _count(session, Tenant) == 1

    def test_is_safe_to_run_on_an_empty_database(self, session: Session) -> None:
        reset_all_data(session)
        session.commit()

        assert _count(session, Tenant) == 1


class TestSessionDependency:
    def test_session_rolls_back_when_the_caller_raises(self, database: Database) -> None:
        generator = database.session()
        session = next(generator)
        session.add(MonitoredModel(name="Rollback"))

        with pytest.raises(RuntimeError):
            generator.throw(RuntimeError("handler failed"))

        with database.session_factory() as fresh:
            assert _count(fresh, MonitoredModel) == 0
