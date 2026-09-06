"""Retention enforcement: the configured window is actually applied."""

from __future__ import annotations

from datetime import timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import AuditEvent, Database, MonitoredModel, Trace, utc_now
from app.retention_worker import purge_all_models, run_worker
from app.service import DriftZeroService


def _trace(model_id: str, *, days_ago: int) -> Trace:
    return Trace(model_id=model_id, occurred_at=utc_now() - timedelta(days=days_ago))


def _count(session: Session, entity: type) -> int:
    return session.execute(sa.select(sa.func.count()).select_from(entity)).scalar() or 0


class TestPurge:
    def test_only_traces_past_the_window_are_removed(
        self, session: Session, model: MonitoredModel
    ) -> None:
        model.retention_days = 7
        session.add_all([_trace(model.id, days_ago=30), _trace(model.id, days_ago=1)])
        session.commit()

        removed = DriftZeroService(Settings()).purge_expired_traces(session, model.id)

        assert removed == 1
        assert _count(session, Trace) == 1

    def test_each_model_keeps_its_own_window(self, session: Session) -> None:
        """Retention is per model so a noisy demo and a regulated system differ."""

        service = DriftZeroService(Settings())
        short = MonitoredModel(name="short", retention_days=1)
        long = MonitoredModel(name="long", retention_days=365)
        session.add_all([short, long])
        session.commit()
        session.add_all([_trace(short.id, days_ago=10), _trace(long.id, days_ago=10)])
        session.commit()

        assert service.purge_expired_traces(session, short.id) == 1
        assert service.purge_expired_traces(session, long.id) == 0

    def test_nothing_to_purge_removes_nothing(
        self, session: Session, model: MonitoredModel
    ) -> None:
        session.add(_trace(model.id, days_ago=1))
        session.commit()

        assert DriftZeroService(Settings()).purge_expired_traces(session, model.id) == 0
        assert _count(session, Trace) == 1


class TestAudit:
    def test_a_deletion_is_recorded(self, session: Session, model: MonitoredModel) -> None:
        """Deleting user data unaudited would defeat having an audit log."""

        model.retention_days = 7
        session.add(_trace(model.id, days_ago=30))
        session.commit()

        DriftZeroService(Settings()).purge_expired_traces(session, model.id)

        events = session.scalars(
            sa.select(AuditEvent).where(AuditEvent.event_type == "retention.purged")
        ).all()
        assert len(events) == 1
        assert events[0].details["removed_traces"] == 1

    def test_a_purge_that_removes_nothing_writes_no_event(
        self, session: Session, model: MonitoredModel
    ) -> None:
        """The trail records deletions, not the fact that a worker ran."""

        session.add(_trace(model.id, days_ago=1))
        session.commit()
        before = _count(session, AuditEvent)

        DriftZeroService(Settings()).purge_expired_traces(session, model.id)

        assert _count(session, AuditEvent) == before


class TestWorker:
    @pytest.fixture
    def database(self) -> Database:
        database = Database("sqlite://")
        database.create_schema()
        yield database
        database.dispose()

    def test_purges_every_active_model(self, database: Database) -> None:
        service = DriftZeroService(Settings())
        with database.session_factory() as session:
            models = [MonitoredModel(name=f"m{i}", retention_days=7) for i in range(3)]
            session.add_all(models)
            session.commit()
            session.add_all([_trace(m.id, days_ago=30) for m in models])
            session.commit()

        summary = purge_all_models(database, service)

        assert summary.models == 3
        assert summary.removed_traces == 3
        assert summary.failed_models == 0

    def test_one_failing_model_does_not_stop_the_others(self, database: Database) -> None:
        service = DriftZeroService(Settings())
        with database.session_factory() as session:
            good = MonitoredModel(name="good", retention_days=7)
            bad = MonitoredModel(name="bad", retention_days=7)
            session.add_all([good, bad])
            session.commit()
            session.add_all([_trace(good.id, days_ago=30), _trace(bad.id, days_ago=30)])
            session.commit()
            bad_id = bad.id

        original = service.purge_expired_traces

        def explode(session: Session, model_id: str) -> int:
            if model_id == bad_id:
                raise RuntimeError("purge failed")
            return original(session, model_id)

        service.purge_expired_traces = explode  # type: ignore[method-assign]
        summary = purge_all_models(database, service)

        assert summary.failed_models == 1
        assert summary.removed_traces == 1, "the healthy model was still purged"

    def test_once_runs_a_single_pass_and_returns(self, tmp_path) -> None:
        """A worker opens an existing database; it does not create the schema.

        So the test gives it a migrated file rather than an empty in-memory one,
        matching how the worker is actually run.
        """

        url = f"sqlite:///{tmp_path / 'retention.db'}"
        prepared = Database(url)
        prepared.create_schema()
        with prepared.session_factory() as session:
            model = MonitoredModel(name="campus", retention_days=7)
            session.add(model)
            session.commit()
            session.add(_trace(model.id, days_ago=30))
            session.commit()
        prepared.dispose()

        # Returns rather than looping on the interval.
        run_worker(Settings(database_url=url), once=True)

        after = Database(url)
        with after.session_factory() as session:
            assert _count(session, Trace) == 0
        after.dispose()
