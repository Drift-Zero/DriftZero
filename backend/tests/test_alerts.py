"""Alert rules, firing, cooldown and resolution."""

from __future__ import annotations

from datetime import timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import Alert, MonitoredModel, utc_now
from app.schemas import (
    ActorRequest,
    AlertRuleCreate,
    AlertState,
    Comparator,
    DimensionScores,
    SignalSource,
    TelemetryCreate,
)
from app.service import DriftZeroService, ResourceConflict


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
    minutes_ago: int = 0,
    sample_size: int = 100,
    coverage: float = 0.95,
) -> None:
    service.record_telemetry(
        session,
        model.id,
        TelemetryCreate(
            observed_at=utc_now() - timedelta(minutes=minutes_ago),
            dimensions=_dimensions(value),
            sample_size=sample_size,
            coverage=coverage,
            source=SignalSource.SIMULATED,
        ),
    )


def _rule(**overrides: object) -> AlertRuleCreate:
    return AlertRuleCreate(
        name=overrides.pop("name", "health below 70"),
        metric=overrides.pop("metric", "score"),
        comparator=overrides.pop("comparator", Comparator.LT),
        threshold=overrides.pop("threshold", 70.0),
        cooldown_minutes=overrides.pop("cooldown_minutes", 30),
        **overrides,
    )


def _alerts(session: Session) -> list[Alert]:
    return list(session.scalars(sa.select(Alert).order_by(Alert.fired_at)).all())


class TestRules:
    def test_duplicate_rule_names_are_rejected(
        self, session: Session, model: MonitoredModel
    ) -> None:
        service = DriftZeroService(Settings())
        service.create_alert_rule(session, model.id, _rule())

        with pytest.raises(ResourceConflict):
            service.create_alert_rule(session, model.id, _rule())


class TestFiring:
    def test_a_breach_fires_an_alert(self, session: Session, model: MonitoredModel) -> None:
        service = DriftZeroService(Settings())
        service.create_alert_rule(session, model.id, _rule())

        _record(service, session, model, 61.0)

        alerts = _alerts(session)
        assert len(alerts) == 1
        assert AlertState(alerts[0].state) is AlertState.FIRING
        assert alerts[0].snapshot_id is not None

    def test_healthy_traffic_fires_nothing(
        self, session: Session, model: MonitoredModel
    ) -> None:
        service = DriftZeroService(Settings())
        service.create_alert_rule(session, model.id, _rule())

        _record(service, session, model, 92.0)

        assert _alerts(session) == []

    def test_a_sustained_breach_fires_once_not_once_per_window(
        self, session: Session, model: MonitoredModel
    ) -> None:
        """Otherwise a long outage pages someone every evaluation window."""

        service = DriftZeroService(Settings())
        service.create_alert_rule(session, model.id, _rule())

        for offset in (30, 20, 10, 0):
            _record(service, session, model, 61.0, minutes_ago=offset)

        assert len(_alerts(session)) == 1

    def test_a_disabled_rule_does_not_fire(
        self, session: Session, model: MonitoredModel
    ) -> None:
        service = DriftZeroService(Settings())
        service.create_alert_rule(session, model.id, _rule(is_enabled=False))

        _record(service, session, model, 20.0)

        assert _alerts(session) == []

    def test_missing_data_is_not_treated_as_a_breach(
        self, session: Session, model: MonitoredModel
    ) -> None:
        """An unmeasured metric would otherwise turn every gap into a page."""

        service = DriftZeroService(Settings())
        service.create_alert_rule(session, model.id, _rule())

        # Below the coverage gate, so no score is produced.
        _record(service, session, model, 61.0, sample_size=1, coverage=0.05)

        assert _alerts(session) == []

    def test_comparators_other_than_less_than_work(
        self, session: Session, model: MonitoredModel
    ) -> None:
        service = DriftZeroService(Settings())
        service.create_alert_rule(
            session,
            model.id,
            _rule(name="latency ceiling", metric="latency", comparator=Comparator.GT,
                  threshold=90.0),
        )

        _record(service, session, model, 95.0)

        assert len(_alerts(session)) == 1


class TestResolution:
    def test_recovery_resolves_an_open_alert(
        self, session: Session, model: MonitoredModel
    ) -> None:
        service = DriftZeroService(Settings())
        service.create_alert_rule(session, model.id, _rule())
        _record(service, session, model, 61.0, minutes_ago=20)

        _record(service, session, model, 92.0)

        alert = _alerts(session)[0]
        assert AlertState(alert.state) is AlertState.RESOLVED
        assert alert.resolved_at is not None

    def test_cooldown_suppresses_immediate_re_firing(
        self, session: Session, model: MonitoredModel
    ) -> None:
        service = DriftZeroService(Settings())
        service.create_alert_rule(session, model.id, _rule(cooldown_minutes=60))
        _record(service, session, model, 61.0, minutes_ago=30)
        _record(service, session, model, 92.0, minutes_ago=20)  # resolves

        _record(service, session, model, 61.0)  # breaches again, inside cooldown

        assert len(_alerts(session)) == 1

    def test_a_zero_cooldown_allows_immediate_re_firing(
        self, session: Session, model: MonitoredModel
    ) -> None:
        service = DriftZeroService(Settings())
        service.create_alert_rule(session, model.id, _rule(cooldown_minutes=0))
        _record(service, session, model, 61.0, minutes_ago=30)
        _record(service, session, model, 92.0, minutes_ago=20)

        _record(service, session, model, 61.0)

        assert len(_alerts(session)) == 2


class TestAcknowledgement:
    def test_acknowledging_records_who_and_when(
        self, session: Session, model: MonitoredModel
    ) -> None:
        service = DriftZeroService(Settings())
        service.create_alert_rule(session, model.id, _rule())
        _record(service, session, model, 61.0)
        alert = _alerts(session)[0]

        result = service.acknowledge_alert(session, alert.id, ActorRequest(actor="operator"))

        assert result.state is AlertState.ACKNOWLEDGED
        assert result.acknowledged_by == "operator"

    def test_an_acknowledged_alert_still_resolves_on_recovery(
        self, session: Session, model: MonitoredModel
    ) -> None:
        service = DriftZeroService(Settings())
        service.create_alert_rule(session, model.id, _rule())
        _record(service, session, model, 61.0, minutes_ago=10)
        alert = _alerts(session)[0]
        service.acknowledge_alert(session, alert.id, ActorRequest(actor="operator"))

        _record(service, session, model, 92.0)

        assert AlertState(_alerts(session)[0].state) is AlertState.RESOLVED

    def test_listing_can_filter_by_state(
        self, session: Session, model: MonitoredModel
    ) -> None:
        service = DriftZeroService(Settings())
        service.create_alert_rule(session, model.id, _rule())
        _record(service, session, model, 61.0)

        firing = service.list_alerts(session, model.id, state=AlertState.FIRING)
        resolved = service.list_alerts(session, model.id, state=AlertState.RESOLVED)

        assert len(firing) == 1
        assert resolved == []
