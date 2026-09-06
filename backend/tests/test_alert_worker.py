"""Unattended alert evaluation for traffic-independent freshness rules."""

from __future__ import annotations

from datetime import timedelta

import sqlalchemy as sa

from app.alert_worker import evaluate_all_models
from app.config import Settings
from app.db import Alert, Database, ModelStatus, MonitoredModel, utc_now
from app.schemas import (
    AlertMetric,
    AlertRuleCreate,
    AlertRuleType,
    Comparator,
    ModelCreate,
)
from app.service import DriftZeroService


def _freshness_rule() -> AlertRuleCreate:
    return AlertRuleCreate(
        name="evaluation stopped",
        rule_type=AlertRuleType.EVALUATION_FRESHNESS,
        metric=AlertMetric.EVALUATION_AGE_MINUTES,
        comparator=Comparator.GT,
        threshold=30,
    )


def test_worker_fires_freshness_alert_and_skips_paused_models() -> None:
    database = Database("sqlite://")
    database.create_schema()
    service = DriftZeroService(Settings())
    with database.session_factory() as session:
        active = service.create_model(session, ModelCreate(name="ActiveModel"))
        paused = service.create_model(session, ModelCreate(name="PausedModel"))
        paused_record = session.get(MonitoredModel, paused.id)
        paused_record.status = ModelStatus.PAUSED.value
        session.commit()
        service.create_alert_rule(session, active.id, _freshness_rule())
        service.create_alert_rule(session, paused.id, _freshness_rule())
        active_record = session.get(MonitoredModel, active.id)
        evaluated_at = active_record.created_at + timedelta(minutes=31)

    summary = evaluate_all_models(database, service, evaluated_at=evaluated_at)

    assert summary.models == 1
    assert summary.rules == 1
    assert summary.fired == 1
    assert summary.failed_models == 0
    with database.session_factory() as session:
        alerts = list(session.scalars(sa.select(Alert)).all())
        assert len(alerts) == 1
        assert alerts[0].model_id == active.id
        assert alerts[0].notified_at == evaluated_at
    database.dispose()


def test_worker_deduplicates_alerts_across_polling_cycles() -> None:
    database = Database("sqlite://")
    database.create_schema()
    service = DriftZeroService(Settings())
    with database.session_factory() as session:
        model = service.create_model(session, ModelCreate(name="PolledModel"))
        service.create_alert_rule(session, model.id, _freshness_rule())
        created_at = session.get(MonitoredModel, model.id).created_at

    first = evaluate_all_models(
        database,
        service,
        evaluated_at=created_at + timedelta(minutes=31),
    )
    second = evaluate_all_models(
        database,
        service,
        evaluated_at=created_at + timedelta(minutes=32),
    )

    assert first.fired == 1
    assert second.fired == 0
    with database.session_factory() as session:
        assert session.scalar(sa.select(sa.func.count()).select_from(Alert)) == 1
    database.dispose()


def test_worker_interval_has_a_safe_minimum(monkeypatch) -> None:
    monkeypatch.setenv("DRIFTZERO_ALERT_EVALUATION_INTERVAL_SECONDS", "0")

    settings = Settings.from_env()

    assert settings.alert_evaluation_interval_seconds == 1


def test_worker_handles_an_empty_fleet() -> None:
    database = Database("sqlite://")
    database.create_schema()

    summary = evaluate_all_models(
        database,
        DriftZeroService(Settings()),
        evaluated_at=utc_now(),
    )

    assert summary.models == 0
    assert summary.rules == 0
    assert summary.fired == 0
    assert summary.resolved == 0
    assert summary.failed_models == 0
    database.dispose()
