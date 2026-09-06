"""Application service coordinating scoring, diagnosis, recovery, and storage."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import (
    AuditEvent,
    Diagnosis,
    HealthSnapshot,
    MonitoredModel,
    RecoveryPlan,
)
from app.diagnosis import diagnose_change
from app.recovery import RecoveryAdapter, SimulatedRecoveryAdapter, build_playbook
from app.schemas import (
    ActorRequest,
    AuditEventResponse,
    DemoResetResponse,
    DiagnosisResponse,
    DiagnosisStatus,
    DimensionScores,
    EvidenceItem,
    HealthSnapshotResponse,
    HealthState,
    HealthTimelineResponse,
    ModelCreate,
    ModelResponse,
    RecoveryAction,
    RecoveryPlanResponse,
    RecoveryState,
    RiskLevel,
    SignalSource,
    TelemetryCreate,
)
from app.scoring import calculate_health, forecast_health


class ServiceError(Exception):
    pass


class ResourceNotFound(ServiceError):
    pass


class ResourceConflict(ServiceError):
    pass


class InvalidTransition(ServiceError):
    pass


class DriftZeroService:
    def __init__(
        self,
        settings: Settings,
        recovery_adapter: RecoveryAdapter | None = None,
    ) -> None:
        self.settings = settings
        self.recovery_adapter = recovery_adapter or SimulatedRecoveryAdapter()

    def create_model(self, session: Session, payload: ModelCreate) -> ModelResponse:
        existing = session.scalar(select(MonitoredModel).where(MonitoredModel.name == payload.name))
        if existing:
            raise ResourceConflict(f"A monitored model named '{payload.name}' already exists.")

        record = MonitoredModel(**payload.model_dump())
        session.add(record)
        session.flush()
        self._audit(session, record.id, "model.created", "system", payload.model_dump())
        session.commit()
        return self._model_response(record)

    def list_models(self, session: Session) -> list[ModelResponse]:
        records = session.scalars(select(MonitoredModel).order_by(MonitoredModel.name)).all()
        return [self._model_response(record) for record in records]

    def get_model(self, session: Session, model_id: str) -> ModelResponse:
        return self._model_response(self._require_model(session, model_id))

    def record_telemetry(
        self,
        session: Session,
        model_id: str,
        payload: TelemetryCreate,
    ) -> HealthSnapshotResponse:
        self._require_model(session, model_id)
        record = self._record_telemetry(session, model_id, payload)
        self._audit(
            session,
            model_id,
            "telemetry.recorded",
            "ingestion",
            {
                "snapshot_id": record.id,
                "score": record.score,
                "state": record.state,
                "source": record.source,
            },
        )
        session.commit()
        return self._snapshot_response(record)

    def health_timeline(
        self,
        session: Session,
        model_id: str,
        *,
        limit: int = 50,
    ) -> HealthTimelineResponse:
        model = self._require_model(session, model_id)
        records = list(
            session.scalars(
                select(HealthSnapshot)
                .where(HealthSnapshot.model_id == model_id)
                .order_by(HealthSnapshot.observed_at.desc())
                .limit(limit)
            ).all()
        )
        records.reverse()
        points = [
            (record.observed_at, record.score)
            for record in records
            if record.score is not None
        ]
        return HealthTimelineResponse(
            model=self._model_response(model),
            snapshots=[self._snapshot_response(record) for record in records],
            forecast=forecast_health(
                points,
                horizon_minutes=self.settings.forecast_horizon_minutes,
            ),
        )

    def diagnose_latest(self, session: Session, model_id: str) -> DiagnosisResponse:
        self._require_model(session, model_id)
        snapshots = list(
            session.scalars(
                select(HealthSnapshot)
                .where(
                    HealthSnapshot.model_id == model_id,
                    HealthSnapshot.score.is_not(None),
                )
                .order_by(HealthSnapshot.observed_at)
            ).all()
        )
        if len(snapshots) < 2:
            raise InvalidTransition("At least two scored snapshots are required for diagnosis.")

        baseline, latest = snapshots[0], snapshots[-1]
        existing = session.scalar(
            select(Diagnosis).where(Diagnosis.snapshot_id == latest.id).limit(1)
        )
        if existing:
            return self._diagnosis_response(existing)

        result = diagnose_change(
            self._dimensions_from_record(baseline),
            self._dimensions_from_record(latest),
        )
        diagnosis = Diagnosis(
            model_id=model_id,
            snapshot_id=latest.id,
            probable_cause=result.probable_cause,
            confidence=result.confidence,
            status=DiagnosisStatus.OPEN.value,
            evidence=[item.model_dump(mode="json") for item in result.evidence],
        )
        session.add(diagnosis)
        session.flush()

        playbook = build_playbook(result.probable_cause)
        plan = RecoveryPlan(
            model_id=model_id,
            diagnosis_id=diagnosis.id,
            state=RecoveryState.RECOMMENDED.value,
            risk=playbook.risk.value,
            actions=[action.model_dump(mode="json") for action in playbook.actions],
            simulation=self.recovery_adapter.simulation,
        )
        session.add(plan)
        session.flush()
        self._audit(
            session,
            model_id,
            "diagnosis.created",
            "diagnosis-engine",
            {
                "diagnosis_id": diagnosis.id,
                "probable_cause": diagnosis.probable_cause,
                "confidence": diagnosis.confidence,
                "recovery_plan_id": plan.id,
            },
        )
        session.commit()
        return self._diagnosis_response(diagnosis)

    def latest_diagnosis(self, session: Session, model_id: str) -> DiagnosisResponse:
        self._require_model(session, model_id)
        record = session.scalar(
            select(Diagnosis)
            .where(Diagnosis.model_id == model_id)
            .order_by(Diagnosis.created_at.desc())
            .limit(1)
        )
        if not record:
            raise ResourceNotFound("No diagnosis exists for this model.")
        return self._diagnosis_response(record)

    def latest_recovery(self, session: Session, model_id: str) -> RecoveryPlanResponse:
        self._require_model(session, model_id)
        record = session.scalar(
            select(RecoveryPlan)
            .where(RecoveryPlan.model_id == model_id)
            .order_by(RecoveryPlan.created_at.desc())
            .limit(1)
        )
        if not record:
            raise ResourceNotFound("No recovery plan exists for this model.")
        return self._recovery_response(record)

    def approve_recovery(
        self,
        session: Session,
        plan_id: str,
        payload: ActorRequest,
    ) -> RecoveryPlanResponse:
        plan = self._require_plan(session, plan_id)
        if plan.state in {RecoveryState.APPROVED.value, RecoveryState.RECOVERED.value}:
            return self._recovery_response(plan)
        if plan.state != RecoveryState.RECOMMENDED.value:
            raise InvalidTransition(f"Cannot approve a plan in '{plan.state}' state.")

        plan.state = RecoveryState.APPROVED.value
        plan.approved_at = datetime.now(timezone.utc)
        plan.approved_by = payload.actor
        self._audit(
            session,
            plan.model_id,
            "recovery.approved",
            payload.actor,
            {"plan_id": plan.id, "risk": plan.risk, "simulation": plan.simulation},
        )
        session.commit()
        return self._recovery_response(plan)

    def execute_recovery(
        self,
        session: Session,
        plan_id: str,
        payload: ActorRequest,
    ) -> RecoveryPlanResponse:
        plan = self._require_plan(session, plan_id)
        if plan.state == RecoveryState.RECOVERED.value:
            return self._recovery_response(plan)
        if plan.state != RecoveryState.APPROVED.value:
            raise InvalidTransition("Recovery must be approved before execution.")

        plan.state = RecoveryState.EXECUTING.value
        plan.executed_at = datetime.now(timezone.utc)
        self._audit(
            session,
            plan.model_id,
            "recovery.execution_started",
            payload.actor,
            {"plan_id": plan.id, "simulation": plan.simulation},
        )
        session.flush()

        try:
            result = self.recovery_adapter.execute(model_id=plan.model_id, plan_id=plan.id)
            snapshot = self._record_telemetry(
                session,
                plan.model_id,
                TelemetryCreate(
                    observed_at=datetime.now(timezone.utc) + timedelta(seconds=1),
                    dimensions=result.dimensions,
                    sample_size=result.evaluated_requests,
                    coverage=result.coverage,
                    source=SignalSource.SIMULATED,
                ),
            )
            recovered = snapshot.score is not None and snapshot.score >= 80
            plan.state = (
                RecoveryState.RECOVERED.value if recovered else RecoveryState.FAILED.value
            )
            plan.verified_at = datetime.now(timezone.utc)
            if recovered:
                diagnosis = session.get(Diagnosis, plan.diagnosis_id)
                if diagnosis:
                    diagnosis.status = DiagnosisStatus.RESOLVED.value
            self._audit(
                session,
                plan.model_id,
                "recovery.verified",
                "verification-engine",
                {
                    "plan_id": plan.id,
                    "resulting_snapshot_id": snapshot.id,
                    "resulting_score": snapshot.score,
                    "evaluated_requests": result.evaluated_requests,
                    "outcome": plan.state,
                    "summary": result.summary,
                },
            )
            session.commit()
        except Exception:
            session.rollback()
            failed_plan = self._require_plan(session, plan_id)
            failed_plan.state = RecoveryState.FAILED.value
            self._audit(
                session,
                failed_plan.model_id,
                "recovery.failed",
                "recovery-adapter",
                {"plan_id": failed_plan.id},
            )
            session.commit()
            raise

        return self._recovery_response(plan)

    def audit_events(self, session: Session, model_id: str) -> list[AuditEventResponse]:
        self._require_model(session, model_id)
        records = session.scalars(
            select(AuditEvent)
            .where(AuditEvent.model_id == model_id)
            .order_by(AuditEvent.created_at)
        ).all()
        return [self._audit_response(record) for record in records]

    def reset_demo(self, session: Session) -> DemoResetResponse:
        existing = session.scalar(
            select(MonitoredModel).where(MonitoredModel.name == "CampusGPT")
        )
        if existing:
            session.execute(delete(MonitoredModel).where(MonitoredModel.id == existing.id))
            session.commit()

        model = MonitoredModel(
            name="CampusGPT",
            provider="demo-adapter",
            environment="simulation",
        )
        session.add(model)
        session.flush()
        now = datetime.now(timezone.utc)
        demo_points = [
            (
                now - timedelta(minutes=90),
                DimensionScores(
                    quality=90.4,
                    groundedness=92,
                    semantic_stability=92,
                    temporal_stability=92,
                    safety=94,
                    drift=92,
                    reliability=92,
                    latency=94,
                    cost=91,
                ),
            ),
            (
                now - timedelta(minutes=60),
                DimensionScores(
                    quality=87,
                    groundedness=81,
                    semantic_stability=82,
                    temporal_stability=87,
                    safety=94,
                    drift=86,
                    reliability=92,
                    latency=94,
                    cost=90,
                ),
            ),
            (
                now - timedelta(minutes=30),
                DimensionScores(
                    quality=74,
                    groundedness=55,
                    semantic_stability=60,
                    temporal_stability=74,
                    safety=94,
                    drift=72,
                    reliability=90,
                    latency=94,
                    cost=85,
                ),
            ),
            (
                now,
                DimensionScores(
                    quality=61,
                    groundedness=30,
                    semantic_stability=35,
                    temporal_stability=61,
                    safety=94,
                    drift=58,
                    reliability=88,
                    latency=94,
                    cost=85,
                ),
            ),
        ]
        for observed_at, dimensions in demo_points:
            self._record_telemetry(
                session,
                model.id,
                TelemetryCreate(
                    observed_at=observed_at,
                    dimensions=dimensions,
                    sample_size=100,
                    coverage=0.95,
                    source=SignalSource.SIMULATED,
                ),
            )
        self._audit(
            session,
            model.id,
            "demo.reset",
            "demo-seeder",
            {"scenario": "knowledge_freshness_failure", "snapshots": 4},
        )
        session.commit()

        diagnosis = self.diagnose_latest(session, model.id)
        return DemoResetResponse(
            model=self._model_response(model),
            health=self.health_timeline(session, model.id),
            diagnosis=diagnosis,
            recovery=self.latest_recovery(session, model.id),
        )

    def _record_telemetry(
        self,
        session: Session,
        model_id: str,
        payload: TelemetryCreate,
    ) -> HealthSnapshot:
        score = calculate_health(
            payload.dimensions,
            sample_size=payload.sample_size,
            coverage=payload.coverage,
            minimum_sample_size=self.settings.minimum_sample_size,
            minimum_coverage=self.settings.minimum_coverage,
        )
        record = HealthSnapshot(
            model_id=model_id,
            observed_at=payload.observed_at,
            **payload.dimensions.model_dump(),
            score=score.score,
            state=score.state.value,
            confidence=score.confidence,
            sample_size=payload.sample_size,
            coverage=payload.coverage,
            policy_version=score.policy_version,
            source=payload.source.value,
            missing_dimensions=score.missing_dimensions,
        )
        session.add(record)
        session.flush()
        return record

    @staticmethod
    def _require_model(session: Session, model_id: str) -> MonitoredModel:
        record = session.get(MonitoredModel, model_id)
        if not record:
            raise ResourceNotFound("Monitored model not found.")
        return record

    @staticmethod
    def _require_plan(session: Session, plan_id: str) -> RecoveryPlan:
        record = session.get(RecoveryPlan, plan_id)
        if not record:
            raise ResourceNotFound("Recovery plan not found.")
        return record

    @staticmethod
    def _audit(
        session: Session,
        model_id: str,
        event_type: str,
        actor: str,
        details: dict[str, object],
    ) -> None:
        session.add(
            AuditEvent(
                model_id=model_id,
                event_type=event_type,
                actor=actor,
                details=details,
            )
        )

    @staticmethod
    def _model_response(record: MonitoredModel) -> ModelResponse:
        return ModelResponse.model_validate(record)

    @classmethod
    def _snapshot_response(cls, record: HealthSnapshot) -> HealthSnapshotResponse:
        return HealthSnapshotResponse(
            id=record.id,
            model_id=record.model_id,
            observed_at=record.observed_at,
            dimensions=cls._dimensions_from_record(record),
            score=record.score,
            state=HealthState(record.state),
            confidence=record.confidence,
            sample_size=record.sample_size,
            coverage=record.coverage,
            policy_version=record.policy_version,
            source=SignalSource(record.source),
            missing_dimensions=record.missing_dimensions,
        )

    @staticmethod
    def _dimensions_from_record(record: HealthSnapshot) -> DimensionScores:
        return DimensionScores(
            **{
                name: getattr(record, name)
                for name in DimensionScores.model_fields
            }
        )

    @staticmethod
    def _diagnosis_response(record: Diagnosis) -> DiagnosisResponse:
        return DiagnosisResponse(
            id=record.id,
            model_id=record.model_id,
            snapshot_id=record.snapshot_id,
            probable_cause=record.probable_cause,
            confidence=record.confidence,
            status=DiagnosisStatus(record.status),
            evidence=[EvidenceItem.model_validate(item) for item in record.evidence],
            created_at=record.created_at,
        )

    @staticmethod
    def _recovery_response(record: RecoveryPlan) -> RecoveryPlanResponse:
        return RecoveryPlanResponse(
            id=record.id,
            model_id=record.model_id,
            diagnosis_id=record.diagnosis_id,
            state=RecoveryState(record.state),
            risk=RiskLevel(record.risk),
            actions=[RecoveryAction.model_validate(item) for item in record.actions],
            simulation=record.simulation,
            created_at=record.created_at,
            approved_at=record.approved_at,
            approved_by=record.approved_by,
            executed_at=record.executed_at,
            verified_at=record.verified_at,
        )

    @staticmethod
    def _audit_response(record: AuditEvent) -> AuditEventResponse:
        return AuditEventResponse(
            id=record.id,
            model_id=record.model_id,
            event_type=record.event_type,
            actor=record.actor,
            details=record.details,
            created_at=record.created_at,
        )

