"""Complete alert rule strategies, lifecycle behavior, and HTTP surface."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import Alert, AuditEvent, HealthSnapshot, MonitoredModel, utc_now
from app.main import create_app
from app.schemas import (
    ActorRequest,
    AlertEvaluationRequest,
    AlertMetric,
    AlertResolveRequest,
    AlertRuleCreate,
    AlertRuleType,
    AlertRuleUpdate,
    AlertState,
    Comparator,
    DimensionScores,
    HealthState,
    SignalSource,
    TelemetryCreate,
)
from app.service import DriftZeroService, InvalidTransition


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
    observed_at: datetime,
    *,
    coverage: float = 0.95,
) -> None:
    service.record_telemetry(
        session,
        model.id,
        TelemetryCreate(
            observed_at=observed_at,
            dimensions=_dimensions(value),
            sample_size=100,
            coverage=coverage,
            source=SignalSource.SIMULATED,
        ),
    )


def _stored_alerts(session: Session) -> list[Alert]:
    return list(session.scalars(sa.select(Alert).order_by(Alert.fired_at)).all())


@pytest.mark.parametrize(
    "payload",
    [
        {
            "name": "bad transition",
            "rule_type": "transition",
            "metric": "score",
            "target_state": "critical",
            "comparator": None,
        },
        {
            "name": "bad coverage",
            "rule_type": "coverage",
            "metric": "coverage",
            "comparator": "lt",
            "threshold": 50,
        },
        {
            "name": "missing trajectory threshold",
            "rule_type": "trajectory",
            "metric": "forecast_score",
        },
    ],
)
def test_rule_contract_rejects_incompatible_strategy(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        AlertRuleCreate.model_validate(payload)


def test_threshold_requires_consecutive_breaches(
    session: Session,
    model: MonitoredModel,
) -> None:
    service = DriftZeroService(Settings())
    service.create_alert_rule(
        session,
        model.id,
        AlertRuleCreate(
            name="sustained critical health",
            metric=AlertMetric.SCORE,
            comparator=Comparator.LT,
            threshold=65,
            window_minutes=60,
            minimum_consecutive_windows=2,
        ),
    )
    now = utc_now()

    _record(service, session, model, 61, now - timedelta(minutes=10))
    assert _stored_alerts(session) == []

    _record(service, session, model, 60, now)
    alert = _stored_alerts(session)[0]
    assert alert.observed_value == 60
    assert alert.details["recent_values"] == [61.0, 60.0]


def test_rule_creation_and_update_evaluate_existing_evidence(
    session: Session,
    model: MonitoredModel,
) -> None:
    service = DriftZeroService(Settings())
    _record(service, session, model, 61, utc_now())

    rule = service.create_alert_rule(
        session,
        model.id,
        AlertRuleCreate(name="existing degradation", threshold=70),
    )

    alert = _stored_alerts(session)[0]
    assert AlertState(alert.state) is AlertState.FIRING
    assert alert.observed_value == 61

    service.update_alert_rule(
        session,
        rule.id,
        AlertRuleUpdate(threshold=50, actor="operator"),
    )
    assert AlertState(alert.state) is AlertState.RESOLVED
    assert alert.resolution_reason == "condition_cleared"


def test_transition_alert_links_incident_and_resolves_after_state_exit(
    session: Session,
    model: MonitoredModel,
) -> None:
    service = DriftZeroService(Settings())
    service.create_alert_rule(
        session,
        model.id,
        AlertRuleCreate(
            name="entered critical",
            rule_type=AlertRuleType.TRANSITION,
            metric=AlertMetric.STATE,
            comparator=None,
            threshold=None,
            target_state=HealthState.CRITICAL,
            window_minutes=60,
            severity="high",
        ),
    )
    now = utc_now()
    _record(service, session, model, 92, now - timedelta(minutes=20))
    _record(service, session, model, 61, now - timedelta(minutes=10))

    alert = _stored_alerts(session)[0]
    assert alert.incident_id is not None
    assert alert.details["previous_state"] == "healthy"
    assert alert.details["current_state"] == "critical"

    _record(service, session, model, 60, now - timedelta(minutes=5))
    assert len(_stored_alerts(session)) == 1
    assert AlertState(alert.state) is AlertState.FIRING

    _record(service, session, model, 92, now)
    assert AlertState(alert.state) is AlertState.RESOLVED
    assert alert.resolution_reason == "condition_cleared"


def test_trajectory_alert_includes_forecast_evidence(
    session: Session,
    model: MonitoredModel,
) -> None:
    service = DriftZeroService(Settings(forecast_horizon_minutes=30))
    service.create_alert_rule(
        session,
        model.id,
        AlertRuleCreate(
            name="forecasted critical health",
            rule_type=AlertRuleType.TRAJECTORY,
            metric=AlertMetric.FORECAST_SCORE,
            comparator=Comparator.LT,
            threshold=50,
            window_minutes=60,
        ),
    )
    now = utc_now()
    _record(service, session, model, 92, now - timedelta(minutes=30))
    _record(service, session, model, 61, now)

    alert = _stored_alerts(session)[0]
    forecast = alert.details["forecast"]
    assert alert.observed_value == forecast["predicted_score"]
    assert forecast["predicted_score"] < 50
    assert forecast["direction"] == "deteriorating"
    assert forecast["lower_bound"] <= forecast["predicted_score"]


def test_coverage_rule_can_fire_when_score_is_suppressed(
    session: Session,
    model: MonitoredModel,
) -> None:
    service = DriftZeroService(Settings())
    service.create_alert_rule(
        session,
        model.id,
        AlertRuleCreate(
            name="coverage too low",
            rule_type=AlertRuleType.COVERAGE,
            metric=AlertMetric.COVERAGE,
            comparator=Comparator.LT,
            threshold=0.5,
        ),
    )

    _record(service, session, model, 92, utc_now(), coverage=0.1)

    alert = _stored_alerts(session)[0]
    assert alert.observed_value == 0.1
    assert session.get(HealthSnapshot, alert.snapshot_id).score is None


def test_freshness_rule_fires_without_telemetry_and_new_data_resolves_it(
    session: Session,
    model: MonitoredModel,
) -> None:
    service = DriftZeroService(Settings())
    service.create_alert_rule(
        session,
        model.id,
        AlertRuleCreate(
            name="evaluation is stale",
            rule_type=AlertRuleType.EVALUATION_FRESHNESS,
            metric=AlertMetric.EVALUATION_AGE_MINUTES,
            comparator=Comparator.GT,
            threshold=30,
        ),
    )
    evaluated_at = model.created_at + timedelta(minutes=31)

    result = service.evaluate_alerts(
        session,
        model.id,
        AlertEvaluationRequest(evaluated_at=evaluated_at),
    )

    assert result.evaluated_rules == 1
    assert len(result.fired) == 1
    assert result.fired[0].snapshot_id is None
    assert result.fired[0].notified_at == evaluated_at

    _record(service, session, model, 92, evaluated_at + timedelta(minutes=1))
    alert = _stored_alerts(session)[0]
    assert AlertState(alert.state) is AlertState.RESOLVED
    assert alert.resolution_reason == "condition_cleared"


def test_rule_disable_and_delete_resolve_alert_but_preserve_history(
    session: Session,
    model: MonitoredModel,
) -> None:
    service = DriftZeroService(Settings())
    rule = service.create_alert_rule(
        session,
        model.id,
        AlertRuleCreate(name="health warning", threshold=70),
    )
    _record(service, session, model, 61, utc_now())
    alert_id = _stored_alerts(session)[0].id

    updated = service.update_alert_rule(
        session,
        rule.id,
        AlertRuleUpdate(is_enabled=False, actor="operator"),
    )
    assert updated.is_enabled is False
    alert = session.get(Alert, alert_id)
    assert AlertState(alert.state) is AlertState.RESOLVED
    assert alert.resolution_reason == "rule_disabled"

    service.delete_alert_rule(session, rule.id, ActorRequest(actor="operator"))
    session.expire_all()
    preserved = session.get(Alert, alert_id)
    assert preserved is not None
    assert preserved.rule_id is None
    events = set(session.scalars(sa.select(AuditEvent.event_type)).all())
    assert {"alert_rule.updated", "alert_rule.deleted", "alert.resolved"} <= events


def test_manual_lifecycle_and_notification_feed(
    session: Session,
    model: MonitoredModel,
) -> None:
    service = DriftZeroService(Settings())
    service.create_alert_rule(
        session,
        model.id,
        AlertRuleCreate(name="critical score", threshold=70),
    )
    _record(service, session, model, 61, utc_now())
    alert_id = _stored_alerts(session)[0].id

    acknowledged = service.acknowledge_alert(
        session, alert_id, ActorRequest(actor="on-call")
    )
    assert acknowledged.state is AlertState.ACKNOWLEDGED
    feed = service.alert_feed(session)
    assert feed.total == 1
    assert feed.firing == 0
    assert feed.acknowledged == 1
    assert feed.items[0].notified_at is not None

    resolved = service.resolve_alert(
        session,
        alert_id,
        AlertResolveRequest(actor="on-call", reason="False positive confirmed."),
    )
    assert resolved.state is AlertState.RESOLVED
    assert resolved.resolution_reason == "False positive confirmed."
    with pytest.raises(InvalidTransition):
        service.acknowledge_alert(session, alert_id, ActorRequest(actor="on-call"))


def test_complete_alert_http_journey() -> None:
    app = create_app(Settings(database_url="sqlite://", environment="test"))
    with TestClient(app) as client:
        model = client.post(
            "/api/v1/models",
            json={"name": "AlertedModel", "actor": "owner"},
        ).json()
        rule_response = client.post(
            f"/api/v1/models/{model['id']}/alert-rules",
            json={
                "name": "critical score",
                "metric": "score",
                "comparator": "lt",
                "threshold": 65,
                "actor": "owner",
            },
        )
        assert rule_response.status_code == 201
        rule = rule_response.json()
        assert rule["rule_type"] == "threshold"

        telemetry = client.post(
            f"/api/v1/models/{model['id']}/telemetry",
            json={
                "dimensions": _dimensions(61).model_dump(),
                "sample_size": 100,
                "coverage": 0.95,
            },
        )
        assert telemetry.status_code == 201

        feed = client.get("/api/v1/alerts")
        assert feed.status_code == 200
        assert feed.json()["firing"] == 1
        alert = feed.json()["items"][0]
        assert alert["incident_id"] is not None
        assert alert["notified_at"] is not None

        acknowledged = client.post(
            f"/api/v1/alerts/{alert['id']}/acknowledge",
            json={"actor": "on-call"},
        )
        assert acknowledged.json()["state"] == "acknowledged"
        resolved = client.post(
            f"/api/v1/alerts/{alert['id']}/resolve",
            json={"actor": "on-call", "reason": "Investigated and accepted."},
        )
        assert resolved.json()["state"] == "resolved"

        updated = client.patch(
            f"/api/v1/alert-rules/{rule['id']}",
            json={"threshold": 60, "actor": "owner"},
        )
        assert updated.status_code == 200
        assert updated.json()["threshold"] == 60
        deleted = client.request(
            "DELETE",
            f"/api/v1/alert-rules/{rule['id']}",
            json={"actor": "owner"},
        )
        assert deleted.status_code == 204
        assert client.get(f"/api/v1/alerts/{alert['id']}").status_code == 200

        audit = client.get(f"/api/v1/models/{model['id']}/audit").json()
        events = {item["event_type"] for item in audit}
        assert {
            "alert_rule.created",
            "alert.fired",
            "alert.acknowledged",
            "alert.resolved",
            "alert_rule.updated",
            "alert_rule.deleted",
        } <= events
