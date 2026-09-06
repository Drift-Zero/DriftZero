"""Per-action recovery execution, verification, and rollback."""

from __future__ import annotations

from datetime import timedelta

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import (
    AuditEvent,
    Incident,
    IncidentState,
    MonitoredModel,
    RecoveryActionRecord,
    RecoveryExecution,
    VerificationRun,
    utc_now,
)
from app.recovery import RecoveryActionResult, RecoveryExecutionResult, SimulatedRecoveryAdapter
from app.schemas import (
    ActorRequest,
    DimensionScores,
    ExecutionState,
    RecoveryState,
    SignalSource,
    TelemetryCreate,
)
from app.service import DriftZeroService

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
# Health clears the threshold, but safety has collapsed: recovery must not be
# allowed to trade one failure for another.
REGRESSED_SAFETY = DimensionScores(
    quality=90.0,
    groundedness=90.0,
    semantic_stability=90.0,
    temporal_stability=90.0,
    safety=40.0,
    drift=90.0,
    reliability=90.0,
    latency=94.0,
    cost=90.0,
)


class _AdapterBase(SimulatedRecoveryAdapter):
    """Reuses the simulated per-action behaviour, overriding the verdict."""

    dimensions = HEALTHY

    def execute(self, *, model_id: str, plan_id: str) -> RecoveryExecutionResult:
        del model_id, plan_id
        return RecoveryExecutionResult(
            dimensions=self.dimensions,
            evaluated_requests=50,
            coverage=0.98,
            summary="test adapter",
        )


class RegressingAdapter(_AdapterBase):
    dimensions = REGRESSED_SAFETY


class SecondActionFailsAdapter(_AdapterBase):
    """Fails the second step, so the rest of the playbook must not run."""

    def execute_action(
        self, *, model_id: str, plan_id: str, action: object, execution_id: str
    ) -> RecoveryActionResult:
        if action.order == 2:
            return RecoveryActionResult(
                succeeded=False,
                affected_traffic_pct=0.0,
                detail={},
                error="adapter refused",
            )
        return super().execute_action(
            model_id=model_id,
            plan_id=plan_id,
            action=action,
            execution_id=execution_id,
        )


class IrreversibleAdapter(_AdapterBase):
    """Applies everything, but nothing can be undone."""

    dimensions = CRITICAL

    def rollback_action(
        self, *, model_id: str, plan_id: str, action: object, execution_id: str
    ) -> RecoveryActionResult:
        del model_id, plan_id, action, execution_id
        return RecoveryActionResult(
            succeeded=False,
            affected_traffic_pct=0.0,
            detail={},
            error="Action is not reversible.",
        )


def _prepare(session: Session, model: MonitoredModel, adapter: object | None = None):
    """Degrade the model, diagnose, and approve the resulting plan."""

    service = DriftZeroService(Settings(), recovery_adapter=adapter)
    for offset, dimensions in ((30, HEALTHY), (0, CRITICAL)):
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
    return service, plan


class TestActionRecords:
    def test_playbook_is_persisted_as_rows(
        self, session: Session, model: MonitoredModel
    ) -> None:
        service, plan = _prepare(session, model)

        records = session.scalars(
            sa.select(RecoveryActionRecord).order_by(RecoveryActionRecord.order)
        ).all()

        assert [record.order for record in records] == list(range(1, len(plan.actions) + 1))
        assert all(record.is_simulated for record in records)


class TestExecution:
    def test_one_execution_row_per_action(
        self, session: Session, model: MonitoredModel
    ) -> None:
        service, plan = _prepare(session, model)

        response = service.execute_recovery(session, plan.id, ActorRequest(actor="operator"))

        assert len(response.executions) == len(plan.actions)
        assert all(
            execution.state is ExecutionState.SUCCEEDED for execution in response.executions
        )
        assert all(execution.timeout_seconds == 10 for execution in response.executions)

    def test_blast_radius_is_recorded_per_action(
        self, session: Session, model: MonitoredModel
    ) -> None:
        service, plan = _prepare(session, model)

        response = service.execute_recovery(session, plan.id, ActorRequest(actor="operator"))

        # Actions touch different shares of traffic; a single plan-level number
        # could not express that.
        shares = {execution.affected_traffic_pct for execution in response.executions}
        assert len(shares) > 1
        assert all(execution.actor == "operator" for execution in response.executions)

    def test_a_failed_step_stops_the_playbook_and_the_rest_are_skipped(
        self, session: Session, model: MonitoredModel
    ) -> None:
        service, plan = _prepare(session, model, SecondActionFailsAdapter())

        response = service.execute_recovery(session, plan.id, ActorRequest(actor="operator"))

        states = [execution.state for execution in response.executions]
        assert states[0] in {ExecutionState.SUCCEEDED, ExecutionState.ROLLED_BACK}
        assert ExecutionState.FAILED in states
        assert ExecutionState.SKIPPED in states
        assert response.state is RecoveryState.FAILED
        assert response.verification is None
        incident = session.scalar(sa.select(Incident))
        assert IncidentState(incident.state) is IncidentState.FAILED


class TestVerification:
    def test_records_what_recovery_was_judged_against(
        self, session: Session, model: MonitoredModel
    ) -> None:
        service, plan = _prepare(session, model)

        response = service.execute_recovery(session, plan.id, ActorRequest(actor="operator"))

        run = response.verification
        assert run is not None
        assert run.passed is True
        assert run.threshold == 80.0
        assert run.required_requests == 50
        assert run.observed_requests == 50
        assert run.required_coverage == 0.9
        assert run.observed_coverage == 0.98
        assert {check["metric"] for check in run.no_regression_checks} == {
            "quality",
            "safety",
            "latency",
            "reliability",
            "cost",
        }

    def test_a_safety_regression_fails_recovery_despite_a_good_score(
        self, session: Session, model: MonitoredModel
    ) -> None:
        """Clearing the threshold is not enough if something else broke."""

        service, plan = _prepare(session, model, RegressingAdapter())

        response = service.execute_recovery(session, plan.id, ActorRequest(actor="operator"))

        run = response.verification
        assert run.post_score >= run.threshold
        assert run.passed is False
        assert response.state is RecoveryState.FAILED
        safety = next(c for c in run.no_regression_checks if c["metric"] == "safety")
        assert safety["passed"] is False

        events = session.scalars(
            sa.select(AuditEvent.event_type).where(AuditEvent.model_id == model.id)
        ).all()
        assert "incident.resolved" not in events
        assert events.count("incident.failed") == 1

    def test_verification_run_is_persisted(
        self, session: Session, model: MonitoredModel
    ) -> None:
        service, plan = _prepare(session, model)
        service.execute_recovery(session, plan.id, ActorRequest(actor="operator"))

        assert session.scalar(sa.select(sa.func.count()).select_from(VerificationRun)) == 1


class TestRollback:
    def test_failed_recovery_rolls_back_applied_actions(
        self, session: Session, model: MonitoredModel
    ) -> None:
        service, plan = _prepare(session, model, RegressingAdapter())

        response = service.execute_recovery(session, plan.id, ActorRequest(actor="operator"))

        assert any(
            execution.state is ExecutionState.ROLLED_BACK for execution in response.executions
        )
        assert all(
            execution.rolled_back_at is not None
            for execution in response.executions
            if execution.state is ExecutionState.ROLLED_BACK
        )

    def test_an_irreversible_action_is_not_claimed_as_rolled_back(
        self, session: Session, model: MonitoredModel
    ) -> None:
        """Saying an action was undone when it wasn't would misstate the deployment."""

        service, plan = _prepare(session, model, IrreversibleAdapter())

        service.execute_recovery(session, plan.id, ActorRequest(actor="operator"))

        executions = session.scalars(sa.select(RecoveryExecution)).all()
        assert all(
            ExecutionState(execution.state) is not ExecutionState.ROLLED_BACK
            for execution in executions
        )
        assert any(execution.rollback_result.get("error") for execution in executions)

    def test_successful_recovery_is_not_rolled_back(
        self, session: Session, model: MonitoredModel
    ) -> None:
        service, plan = _prepare(session, model)

        response = service.execute_recovery(session, plan.id, ActorRequest(actor="operator"))

        assert all(execution.rolled_back_at is None for execution in response.executions)
