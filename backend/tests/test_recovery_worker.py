"""Durable command queue behavior for recovery execution."""

from __future__ import annotations

from datetime import timedelta

from app.config import Settings
from app.db import Database, RecoveryCommand, utc_now
from app.recovery import RecoveryActionResult, SimulatedRecoveryAdapter
from app.recovery_worker import _claim_next, process_recovery_commands
from app.schemas import (
    ActorRequest,
    DimensionScores,
    ModelCreate,
    RecoveryCommandState,
    RecoveryExecuteRequest,
    RecoveryRollbackRequest,
    RecoveryState,
    SignalSource,
    TelemetryCreate,
)
from app.service import DriftZeroService


class ObservedVerificationAdapter(SimulatedRecoveryAdapter):
    """Applies demo actions but requires genuine telemetry for verification."""

    simulation = False

    def execute(self, *, model_id: str, plan_id: str) -> None:
        del model_id, plan_id
        return None


class FlakyAdapter(SimulatedRecoveryAdapter):
    def __init__(self) -> None:
        self.calls = 0

    def execute_action(self, **kwargs):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("temporary control-plane outage")
        return super().execute_action(**kwargs)


class RefusingAdapter(SimulatedRecoveryAdapter):
    def execute_action(self, **kwargs):
        return RecoveryActionResult(
            succeeded=False,
            affected_traffic_pct=0.0,
            detail={"provider": "shopassist", "action": kwargs["action"].code},
            error="ShopAssist recovery control refused the action.",
        )


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


def test_worker_returns_the_recovery_failure_on_the_command() -> None:
    database = Database("sqlite://")
    database.create_schema()
    service = DriftZeroService(Settings(), recovery_adapter=RefusingAdapter())
    plan_id, command_id = _queued(database, service)

    summary = process_recovery_commands(database, service, limit=1)

    assert summary.failed == 1
    assert summary.succeeded == 0
    with database.session_factory() as session:
        command = session.get(RecoveryCommand, command_id)
        assert RecoveryCommandState(command.state) is RecoveryCommandState.FAILED
        assert command.error == "ShopAssist recovery control refused the action."
        recovery = service.get_recovery(session, plan_id)
        assert recovery.state is RecoveryState.FAILED
        assert recovery.failure_reason == command.error
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


def test_real_adapter_waits_for_observed_telemetry_before_resolution() -> None:
    database = Database("sqlite://")
    database.create_schema()
    service = DriftZeroService(Settings(), recovery_adapter=ObservedVerificationAdapter())
    plan_id, _ = _queued(database, service)

    execution = process_recovery_commands(database, service, limit=1)
    assert execution.succeeded == 1
    with database.session_factory() as session:
        assert service.get_recovery(session, plan_id).state is RecoveryState.VERIFYING

        plan = service.get_recovery(session, plan_id)
        service.record_telemetry(
            session,
            plan.model_id,
            TelemetryCreate(
                observed_at=utc_now() + timedelta(seconds=1),
                dimensions=DimensionScores(
                    quality=90,
                    groundedness=90,
                    semantic_stability=90,
                    temporal_stability=90,
                    safety=95,
                    drift=90,
                    reliability=90,
                    latency=90,
                    cost=90,
                ),
                sample_size=50,
                coverage=0.95,
                source=SignalSource.OBSERVED,
            ),
        )

    verification = process_recovery_commands(database, service, limit=1)

    assert verification.succeeded == 1
    with database.session_factory() as session:
        recovered = service.get_recovery(session, plan_id)
        assert recovered.state is RecoveryState.RECOVERED
        assert recovered.verification.observed_requests == 50
        assert recovered.verification.observed_coverage == 0.95
    database.dispose()


def test_worker_retries_with_the_same_persisted_action_attempt() -> None:
    database = Database("sqlite://")
    database.create_schema()
    adapter = FlakyAdapter()
    service = DriftZeroService(Settings(), recovery_adapter=adapter)
    plan_id, command_id = _queued(database, service)

    first = process_recovery_commands(database, service, limit=1)
    assert first.retried == 1
    with database.session_factory() as session:
        command = session.get(RecoveryCommand, command_id)
        command.available_at = utc_now() - timedelta(seconds=1)
        session.commit()

    second = process_recovery_commands(database, service, limit=1)

    assert second.succeeded == 1
    with database.session_factory() as session:
        command = session.get(RecoveryCommand, command_id)
        assert command.attempt == 2
        recovery = service.get_recovery(session, plan_id)
        assert recovery.state is RecoveryState.RECOVERED
        assert len({execution.id for execution in recovery.executions}) == len(
            recovery.executions
        )
    database.dispose()


def test_rollback_is_a_separate_durable_command() -> None:
    database = Database("sqlite://")
    database.create_schema()
    service = DriftZeroService(Settings())
    plan_id, _ = _queued(database, service)
    process_recovery_commands(database, service, limit=1)

    with database.session_factory() as session:
        service.enqueue_rollback(
            session,
            plan_id,
            RecoveryRollbackRequest(
                actor="admin",
                role="admin",
                reason="Return to the previous operating mode.",
                idempotency_key="rollback-command-key",
            ),
        )
    result = process_recovery_commands(database, service, limit=1)

    assert result.succeeded == 1
    with database.session_factory() as session:
        plan = service.get_recovery(session, plan_id)
        assert plan.state is RecoveryState.ROLLED_BACK
        assert all(execution.rolled_back_at for execution in plan.executions)
    database.dispose()
