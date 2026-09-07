"""The incident lifecycle, from detection through verified recovery."""

from __future__ import annotations

from datetime import timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import HealthSnapshot, HealthState, Incident, MonitoredModel, utc_now
from app.recovery import RecoveryActionResult, RecoveryExecutionResult
from app.schemas import (
    ActorRequest,
    DimensionScores,
    IncidentState,
    Severity,
    SignalSource,
    TelemetryCreate,
)
from app.service import DriftZeroService, ResourceNotFound

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
WARNING = DimensionScores(
    quality=74.0,
    groundedness=55.0,
    semantic_stability=60.0,
    temporal_stability=74.0,
    safety=94.0,
    drift=72.0,
    reliability=90.0,
    latency=94.0,
    cost=85.0,
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


class FailingRecoveryAdapter:
    """An adapter whose actions apply cleanly but do not restore health."""

    simulation = True

    def execute_action(
        self, *, model_id: str, plan_id: str, action: object, execution_id: str
    ) -> RecoveryActionResult:
        del model_id, plan_id, action, execution_id
        return RecoveryActionResult(succeeded=True, affected_traffic_pct=50.0, detail={})

    def rollback_action(
        self, *, model_id: str, plan_id: str, action: object, execution_id: str
    ) -> RecoveryActionResult:
        del model_id, plan_id, action, execution_id
        return RecoveryActionResult(succeeded=True, affected_traffic_pct=50.0, detail={})

    def execute(self, *, model_id: str, plan_id: str) -> RecoveryExecutionResult:
        del model_id, plan_id
        return RecoveryExecutionResult(
            dimensions=CRITICAL,
            evaluated_requests=50,
            coverage=0.98,
            summary="Remediation did not take effect.",
        )


def _service(adapter: object | None = None) -> DriftZeroService:
    return DriftZeroService(Settings(), recovery_adapter=adapter)


def _record(
    service: DriftZeroService,
    session: Session,
    model: MonitoredModel,
    dimensions: DimensionScores,
    *,
    minutes_ago: int = 0,
) -> None:
    service.record_telemetry(
        session,
        model.id,
        TelemetryCreate(
            observed_at=utc_now() - timedelta(minutes=minutes_ago),
            dimensions=dimensions,
            sample_size=100,
            coverage=0.95,
            source=SignalSource.SIMULATED,
        ),
    )


def _incident(session: Session) -> Incident | None:
    return session.scalar(sa.select(Incident))


class TestOpening:
    def test_healthy_traffic_opens_nothing(
        self, session: Session, model: MonitoredModel
    ) -> None:
        _record(_service(), session, model, HEALTHY)

        assert _incident(session) is None

    def test_degradation_opens_an_incident(
        self, session: Session, model: MonitoredModel
    ) -> None:
        service = _service()
        _record(service, session, model, HEALTHY, minutes_ago=30)
        _record(service, session, model, WARNING)

        incident = _incident(session)
        assert incident is not None
        assert IncidentState(incident.state) is IncidentState.OPEN
        assert Severity(incident.severity) is Severity.MEDIUM

    def test_baseline_is_the_last_healthy_score(
        self, session: Session, model: MonitoredModel
    ) -> None:
        service = _service()
        _record(service, session, model, HEALTHY, minutes_ago=30)
        _record(service, session, model, WARNING)

        healthy_score = session.scalar(
            sa.select(HealthSnapshot.score)
            .where(HealthSnapshot.state == HealthState.HEALTHY.value)
            .order_by(HealthSnapshot.observed_at.desc())
        )
        # The score the model was holding before it started to fall.
        assert _incident(session).baseline_score == healthy_score

    def test_a_second_degraded_window_does_not_open_a_second_incident(
        self, session: Session, model: MonitoredModel
    ) -> None:
        service = _service()
        _record(service, session, model, HEALTHY, minutes_ago=30)
        _record(service, session, model, WARNING, minutes_ago=20)
        _record(service, session, model, CRITICAL, minutes_ago=10)

        assert session.scalar(sa.select(sa.func.count()).select_from(Incident)) == 1


class TestSeverityAndTrough:
    def test_severity_escalates_but_never_de_escalates(
        self, session: Session, model: MonitoredModel
    ) -> None:
        service = _service()
        _record(service, session, model, HEALTHY, minutes_ago=40)
        _record(service, session, model, WARNING, minutes_ago=30)
        assert Severity(_incident(session).severity) is Severity.MEDIUM

        _record(service, session, model, CRITICAL, minutes_ago=20)
        assert Severity(_incident(session).severity) is Severity.HIGH

        # Improving to a warning does not make the incident less severe than it
        # has already been.
        _record(service, session, model, WARNING, minutes_ago=10)
        assert Severity(_incident(session).severity) is Severity.HIGH

    def test_trough_records_the_worst_not_the_latest(
        self, session: Session, model: MonitoredModel
    ) -> None:
        service = _service()
        _record(service, session, model, HEALTHY, minutes_ago=40)
        _record(service, session, model, CRITICAL, minutes_ago=30)
        worst = _incident(session).trough_score

        _record(service, session, model, WARNING, minutes_ago=20)

        assert _incident(session).trough_score == worst


class TestLifecycle:
    @staticmethod
    def _degraded(session: Session, model: MonitoredModel, service: DriftZeroService) -> None:
        _record(service, session, model, HEALTHY, minutes_ago=30)
        _record(service, session, model, CRITICAL)

    def test_diagnosis_and_recovery_attach_to_the_incident(
        self, session: Session, model: MonitoredModel
    ) -> None:
        service = _service()
        self._degraded(session, model, service)

        diagnosis = service.diagnose_latest(session, model.id)
        recovery = service.latest_recovery(session, model.id)

        incident = _incident(session)
        assert diagnosis.incident_id == incident.id
        assert recovery.incident_id == incident.id
        assert IncidentState(incident.state) is IncidentState.DIAGNOSING

    def test_approval_starts_mitigation(
        self, session: Session, model: MonitoredModel
    ) -> None:
        service = _service()
        self._degraded(session, model, service)
        plan = service.diagnose_latest(session, model.id) and service.latest_recovery(
            session, model.id
        )

        service.approve_recovery(session, plan.id, ActorRequest(actor="operator"))

        assert IncidentState(_incident(session).state) is IncidentState.MITIGATING

    def test_successful_verification_resolves_and_closes(
        self, session: Session, model: MonitoredModel
    ) -> None:
        service = _service()
        self._degraded(session, model, service)
        service.diagnose_latest(session, model.id)
        plan = service.latest_recovery(session, model.id)
        service.approve_recovery(session, plan.id, ActorRequest(actor="operator"))

        service.execute_recovery(session, plan.id, ActorRequest(actor="operator"))

        incident = _incident(session)
        assert IncidentState(incident.state) is IncidentState.RESOLVED
        assert incident.closed_at is not None
        assert incident.closing_snapshot_id is not None
        assert "Recovered to" in incident.summary

    def test_failed_verification_marks_the_incident_failed(
        self, session: Session, model: MonitoredModel
    ) -> None:
        service = _service(FailingRecoveryAdapter())
        self._degraded(session, model, service)
        service.diagnose_latest(session, model.id)
        plan = service.latest_recovery(session, model.id)
        service.approve_recovery(session, plan.id, ActorRequest(actor="operator"))

        service.execute_recovery(session, plan.id, ActorRequest(actor="operator"))

        incident = _incident(session)
        assert IncidentState(incident.state) is IncidentState.FAILED
        assert incident.closed_at is not None

    def test_a_resolved_incident_is_not_reopened_by_later_degradation(
        self, session: Session, model: MonitoredModel
    ) -> None:
        """A closed incident stays closed; a new failure is a new incident."""

        service = _service()
        self._degraded(session, model, service)
        service.diagnose_latest(session, model.id)
        plan = service.latest_recovery(session, model.id)
        service.approve_recovery(session, plan.id, ActorRequest(actor="operator"))
        service.execute_recovery(session, plan.id, ActorRequest(actor="operator"))

        _record(service, session, model, CRITICAL)

        incidents = session.scalars(sa.select(Incident).order_by(Incident.opened_at)).all()
        assert len(incidents) == 2
        assert IncidentState(incidents[0].state) is IncidentState.RESOLVED
        assert IncidentState(incidents[1].state) is IncidentState.OPEN


class TestReads:
    def test_lists_most_recently_opened_first(
        self, session: Session, model: MonitoredModel
    ) -> None:
        service = _service()
        _record(service, session, model, HEALTHY, minutes_ago=30)
        _record(service, session, model, CRITICAL, minutes_ago=20)

        incidents = service.list_incidents(session, model.id)

        assert len(incidents) == 1
        assert incidents[0].trough_score is not None

    def test_unknown_incident_is_not_found(self, session: Session) -> None:
        with pytest.raises(ResourceNotFound):
            _service().get_incident(session, "does-not-exist")


class TestDemoScenario:
    def test_the_scenario_produces_one_incident(self, session: Session) -> None:
        demo = _service().reset_demo(session)

        assert demo.incident is not None
        assert demo.incident.baseline_score == 87.2
        assert demo.incident.trough_score == 62.5
        # Escalated when the model fell from warning into critical.
        assert demo.incident.severity is Severity.HIGH
        assert demo.diagnosis.incident_id == demo.incident.id
