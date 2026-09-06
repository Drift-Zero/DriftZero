"""Policy, lifecycle, and idempotency behavior for recovery control."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import MonitoredModel, utc_now
from app.schemas import (
    ActorRequest,
    ActorRole,
    DimensionScores,
    RecoveryExecuteRequest,
    RecoveryState,
    SignalSource,
    TelemetryCreate,
)
from app.service import DriftZeroService, InvalidTransition, ResourceConflict

HEALTHY = DimensionScores(
    quality=92,
    groundedness=92,
    semantic_stability=92,
    temporal_stability=92,
    safety=92,
    drift=92,
    reliability=92,
    latency=92,
    cost=92,
)
CRITICAL = HEALTHY.model_copy(update={"groundedness": 20, "quality": 35, "drift": 30})


def _plan(session: Session, model: MonitoredModel):
    service = DriftZeroService(Settings())
    for offset, scores in ((30, HEALTHY), (0, CRITICAL)):
        service.record_telemetry(
            session,
            model.id,
            TelemetryCreate(
                observed_at=utc_now() - timedelta(minutes=offset),
                dimensions=scores,
                sample_size=100,
                coverage=0.95,
                source=SignalSource.SIMULATED,
            ),
        )
    service.diagnose_latest(session, model.id)
    return service, service.latest_recovery(session, model.id)


def test_viewer_cannot_approve_recovery(session: Session, model: MonitoredModel) -> None:
    service, plan = _plan(session, model)

    with pytest.raises(InvalidTransition, match="requires the operator role"):
        service.approve_recovery(
            session,
            plan.id,
            ActorRequest(actor="reader", role=ActorRole.VIEWER),
        )


def test_stale_plan_version_is_rejected(session: Session, model: MonitoredModel) -> None:
    service, plan = _plan(session, model)

    with pytest.raises(ResourceConflict, match="version changed"):
        service.approve_recovery(
            session,
            plan.id,
            RecoveryExecuteRequest(
                actor="operator",
                idempotency_key="unused-key",
                expected_version=plan.version + 1,
            ),
        )


def test_reject_records_decision(session: Session, model: MonitoredModel) -> None:
    service, plan = _plan(session, model)

    rejected = service.reject_recovery(
        session,
        plan.id,
        ActorRequest(actor="operator", reason="Fallback is unhealthy."),
    )

    assert rejected.state is RecoveryState.REJECTED
    assert rejected.rejected_by == "operator"
    assert rejected.rejected_reason == "Fallback is unhealthy."


def test_execute_is_idempotent(session: Session, model: MonitoredModel) -> None:
    service, plan = _plan(session, model)
    service.approve_recovery(session, plan.id, ActorRequest(actor="operator"))
    request = RecoveryExecuteRequest(
        actor="operator",
        idempotency_key="same-command-key",
    )

    first = service.execute_recovery(session, plan.id, request)
    replay = service.execute_recovery(session, plan.id, request)

    assert first.state is RecoveryState.RECOVERED
    assert replay.state is RecoveryState.RECOVERED
    assert len(replay.executions) == len(first.executions)


def test_different_execute_key_conflicts(session: Session, model: MonitoredModel) -> None:
    service, plan = _plan(session, model)
    service.approve_recovery(session, plan.id, ActorRequest(actor="operator"))
    service.execute_recovery(
        session,
        plan.id,
        RecoveryExecuteRequest(actor="operator", idempotency_key="first-run-key"),
    )

    with pytest.raises(ResourceConflict, match="different idempotency key"):
        service.execute_recovery(
            session,
            plan.id,
            RecoveryExecuteRequest(actor="operator", idempotency_key="second-run-key"),
        )


def test_blast_radius_limit_is_checked_before_execution(
    session: Session, model: MonitoredModel
) -> None:
    service, plan = _plan(session, model)
    service.approve_recovery(session, plan.id, ActorRequest(actor="operator"))

    with pytest.raises(InvalidTransition, match="would affect"):
        service.execute_recovery(
            session,
            plan.id,
            RecoveryExecuteRequest(
                actor="operator",
                idempotency_key="limited-run-key",
                max_traffic_pct=1,
            ),
        )

    current = service.get_recovery(session, plan.id)
    assert current.state is RecoveryState.APPROVED
    assert current.executions == []
