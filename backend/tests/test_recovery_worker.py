"""Durable command queue behavior for recovery execution."""

from __future__ import annotations

from datetime import timedelta

from app.config import Settings
from app.db import Database, RecoveryCommand, utc_now
from app.recovery_worker import _claim_next, process_recovery_commands
from app.schemas import (
    ActorRequest,
    DimensionScores,
    ModelCreate,
    RecoveryCommandState,
    RecoveryExecuteRequest,
    RecoveryState,
    SignalSource,
    TelemetryCreate,
)
from app.service import DriftZeroService


def _queued(database: Database, service: DriftZeroService):
    scores = DimensionScores(
        quality=90,
        groundedness=90,
        semantic_stability=90,
        temporal_stability=90,
        safety=95,
        drift=90,
        reliability=90,
        latency=90,
        cost=90,
    )
    with database.session_factory() as session:
        model = service.create_model(session, ModelCreate(name="QueuedModel"))
        for offset, dimensions in (
            (30, scores),
            (0, scores.model_copy(update={"groundedness": 20, "quality": 30})),
        ):
            service.record_telemetry(
                session,
                model.id,
                TelemetryCreate(
                    observed_at=utc_now() - timedelta(minutes=offset),
                    dimensions=dimensions,
                    sample_size=100,
                    coverage=0.95,
                    source=SignalSource.SIMULATED,
                ),
            )
        service.diagnose_latest(session, model.id)
        plan = service.latest_recovery(session, model.id)
        service.approve_recovery(session, plan.id, ActorRequest(actor="operator"))
        command = service.enqueue_recovery(
            session,
            plan.id,
            RecoveryExecuteRequest(
                actor="operator",
                idempotency_key="durable-worker-command",
            ),
        )
        return plan.id, command.id


def test_worker_executes_a_persisted_command() -> None:
    database = Database("sqlite://")
    database.create_schema()
    service = DriftZeroService(Settings())
    plan_id, command_id = _queued(database, service)

    summary = process_recovery_commands(database, service, limit=1)

    assert summary.processed == 1
    assert summary.succeeded == 1
    with database.session_factory() as session:
        command = session.get(RecoveryCommand, command_id)
        assert RecoveryCommandState(command.state) is RecoveryCommandState.SUCCEEDED
        assert service.get_recovery(session, plan_id).state is RecoveryState.RECOVERED
    database.dispose()


def test_expired_worker_lease_can_be_reclaimed() -> None:
    settings = Settings(recovery_command_lease_seconds=5)
    database = Database("sqlite://")
    database.create_schema()
    service = DriftZeroService(settings)
    _, command_id = _queued(database, service)
    assert _claim_next(database, settings) == command_id

    with database.session_factory() as session:
        command = session.get(RecoveryCommand, command_id)
        command.lease_expires_at = utc_now() - timedelta(seconds=1)
        session.commit()

    assert _claim_next(database, settings) == command_id
    database.dispose()


def test_enqueue_is_idempotent() -> None:
    database = Database("sqlite://")
    database.create_schema()
    service = DriftZeroService(Settings())
    plan_id, command_id = _queued(database, service)

    with database.session_factory() as session:
        replay = service.enqueue_recovery(
            session,
            plan_id,
            RecoveryExecuteRequest(
                actor="operator",
                idempotency_key="durable-worker-command",
            ),
        )

    assert replay.id == command_id
    database.dispose()
