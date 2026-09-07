"""Application service coordinating scoring, diagnosis, recovery, and storage."""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta
from inspect import signature
from math import ceil
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.alerting import AlertEvaluation, AlertEvaluator
from app.config import Settings
from app.connections import ConnectionCheckError, ConnectionInspector, CredentialVault
from app.database import (
    AuditEvent,
    Diagnosis,
    HealthSnapshot,
    MonitoredModel,
    RecoveryPlan,
)
from app.db import (
    DEFAULT_TENANT_ID,
    Alert,
    AlertRule,
    DiagnosisEvidence,
    EvaluationFeedback,
    EvaluatorVersion,
    HealthForecastRecord,
    Incident,
    KnowledgeDocument,
    KnowledgeSource,
    KnowledgeStatus,
    ModelConnection,
    ModelStatus,
    ModelVersion,
    RecoveryActionRecord,
    RecoveryCommand,
    RecoveryExecution,
    ReviewQueueItem,
    StabilityClaim,
    StabilityTest,
    StabilityVariant,
    Trace,
    VerificationRun,
    baseline_traces_before,
    ensure_health_policy,
    latest_snapshot,
    purge_expired_traces,
    snapshot_timeline,
    traces_for_metric,
)
from app.diagnosis import diagnose_change
from app.drift import score_drift
from app.evaluation import EvaluatorAdapter, SimulatedEvaluator
from app.hallucination import score_groundedness
from app.observability import get_request_id
from app.recovery import RecoveryAdapter, RecoveryPolicy, build_playbook, build_recovery_adapter
from app.redaction import REDACTION_POLICY_VERSION, content_hash, redact
from app.schemas import (
    ActorRequest,
    ActorRole,
    ActorType,
    AlertEvaluationRequest,
    AlertEvaluationResponse,
    AlertFeedResponse,
    AlertResolveRequest,
    AlertResponse,
    AlertRuleCreate,
    AlertRuleDefinition,
    AlertRuleResponse,
    AlertRuleUpdate,
    AlertState,
    AuditEventResponse,
    ConnectionCheckResponse,
    ConnectionCreate,
    ConnectionCreatedResponse,
    ConnectionResponse,
    ConnectionUpdate,
    DemoResetResponse,
    DiagnosisResponse,
    DiagnosisStatus,
    DimensionScores,
    EvaluationFeedbackCreate,
    EvaluationFeedbackResponse,
    EvaluatorKind,
    EvidenceItem,
    ExecutionState,
    HealthForecastRecordResponse,
    HealthSnapshotResponse,
    HealthState,
    HealthTimelineResponse,
    IncidentResponse,
    IncidentState,
    ModelCreate,
    ModelLifecycleUpdate,
    ModelResponse,
    ModelUpdate,
    ModelVersionCreate,
    ModelVersionResponse,
    RecoveryAction,
    RecoveryCommandResponse,
    RecoveryCommandState,
    RecoveryCommandType,
    RecoveryExecuteRequest,
    RecoveryExecutionResponse,
    RecoveryPlanResponse,
    RecoveryRollbackRequest,
    RecoveryState,
    RecoveryVerifyRequest,
    RegistrationCheck,
    RegistrationStatusResponse,
    ReviewDecisionRequest,
    ReviewQueueItemResponse,
    ReviewState,
    RiskLevel,
    Severity,
    ShopAssistTelemetryCreate,
    SignalSource,
    StabilityKind,
    StabilityRunRequest,
    StabilityTestResponse,
    StabilityVerdict,
    TelemetryCreate,
    TraceCreate,
    VerificationRunResponse,
)
from app.scoring import DIMENSION_WEIGHTS, calculate_health, forecast_health

# Mirrors the boundaries in scoring.classify_health so a stored snapshot can
# show the thresholds it was judged against.
HEALTH_THRESHOLDS = {"healthy": 80.0, "warning": 65.0}


class ServiceError(Exception):
    pass


class ResourceNotFound(ServiceError):
    pass


class ResourceConflict(ServiceError):
    pass


class InvalidTransition(ServiceError):
    pass


class AuthorizationDenied(ServiceError):
    pass


class TelemetryIngestionError(ServiceError):
    pass


class ConnectionConfigurationError(ServiceError):
    pass


class DriftZeroService:
    def __init__(
        self,
        settings: Settings,
        recovery_adapter: RecoveryAdapter | None = None,
        evaluator: EvaluatorAdapter | None = None,
    ) -> None:
        self.settings = settings
        self.recovery_adapter = recovery_adapter or build_recovery_adapter(settings)
        self.recovery_policy = RecoveryPolicy()
        self.evaluator = evaluator or SimulatedEvaluator()
        self.alert_evaluator = AlertEvaluator()
        self.credential_vault = CredentialVault(settings.connection_secret_key)
        self.connection_inspector = ConnectionInspector(settings)

    def create_model(self, session: Session, payload: ModelCreate) -> ModelResponse:
        tenant_id = self._tenant_id(session)
        existing = session.scalar(
            select(MonitoredModel).where(
                MonitoredModel.tenant_id == tenant_id,
                MonitoredModel.name == payload.name,
            )
        )
        if existing:
            raise ResourceConflict(f"A monitored model named '{payload.name}' already exists.")

        record = MonitoredModel(
            **payload.model_dump(exclude={"actor", "initial_version"}),
            tenant_id=tenant_id,
        )
        session.add(record)
        session.flush()
        version = None
        if payload.initial_version is not None:
            version = self._create_model_version(session, record, payload.initial_version)
        self._audit(
            session,
            record.id,
            "model.created",
            payload.actor,
            {
                "name": record.name,
                "provider": record.provider,
                "environment": record.environment,
                "retention_days": record.retention_days,
                "initial_version_id": version.id if version else None,
            },
        )
        session.commit()
        return self._model_response(record)

    def list_models(self, session: Session) -> list[ModelResponse]:
        tenant_id = self._tenant_id(session)
        records = session.scalars(
            select(MonitoredModel)
            .where(MonitoredModel.tenant_id == tenant_id)
            .order_by(MonitoredModel.name)
        ).all()
        return [self._model_response(record) for record in records]

    def create_connection(
        self, session: Session, model_id: str, payload: ConnectionCreate
    ) -> ConnectionCreatedResponse:
        model = self._require_model(session, model_id)
        existing = session.scalar(
            select(ModelConnection).where(
                ModelConnection.model_id == model_id,
                ModelConnection.kind == payload.kind.value,
                ModelConnection.name == payload.name,
            )
        )
        if existing:
            raise ResourceConflict("A connection with this name and type already exists.")
        values = payload.model_dump(exclude={"actor", "api_key"})
        values["kind"] = payload.kind.value
        if payload.kind.value == "telemetry":
            values["url"] = f"/api/v1/models/{model.id}/telemetry"
        credential = payload.api_key.get_secret_value() if payload.api_key else None
        try:
            values["credential_ciphertext"] = (
                self.credential_vault.encrypt(credential) if credential else None
            )
        except ConnectionCheckError as exc:
            raise ConnectionConfigurationError(str(exc)) from exc
        values["credential_configured"] = bool(credential)
        ingestion_key = None
        if payload.kind.value == "telemetry":
            ingestion_key = f"dz_ing_{secrets.token_urlsafe(32)}"
            values["ingest_key_hash"] = hashlib.sha256(ingestion_key.encode()).hexdigest()
        needs_credential = payload.kind.value == "api" and bool(payload.auth_scheme)
        values["status"] = "needs_setup" if needs_credential and not credential else "configured"
        record = ModelConnection(model_id=model.id, tenant_id=model.tenant_id, **values)
        session.add(record)
        self._audit(
            session,
            model.id,
            "model.connection_created",
            payload.actor,
            {
                "connection_id": record.id,
                "kind": payload.kind.value,
                "credential_configured": record.credential_configured,
            },
        )
        session.commit()
        response = ConnectionResponse.model_validate(record)
        return ConnectionCreatedResponse(**response.model_dump(), ingestion_key=ingestion_key)

    def list_connections(self, session: Session, model_id: str) -> list[ConnectionResponse]:
        self._require_model(session, model_id)
        records = session.scalars(
            select(ModelConnection)
            .where(ModelConnection.model_id == model_id)
            .order_by(ModelConnection.created_at)
        ).all()
        return [ConnectionResponse.model_validate(record) for record in records]

    def get_connection(self, session: Session, connection_id: str) -> ConnectionResponse:
        return ConnectionResponse.model_validate(self._require_connection(session, connection_id))

    def update_connection(
        self, session: Session, connection_id: str, payload: ConnectionUpdate
    ) -> ConnectionResponse:
        record = self._require_connection(session, connection_id)
        if payload.api_key is not None:
            credential = payload.api_key.get_secret_value()
            try:
                record.credential_ciphertext = self.credential_vault.encrypt(credential)
            except ConnectionCheckError as exc:
                raise ConnectionConfigurationError(str(exc)) from exc
            record.credential_configured = True
        if payload.config is not None:
            record.config = payload.config
        if payload.status is not None:
            record.status = payload.status
        record.last_error = None
        self._audit(
            session,
            record.model_id,
            "model.connection_updated",
            payload.actor,
            {"connection_id": record.id, "credential_rotated": payload.api_key is not None},
        )
        session.commit()
        return ConnectionResponse.model_validate(record)

    def check_connection(
        self, session: Session, connection_id: str, *, actor: str
    ) -> ConnectionCheckResponse:
        record = self._require_connection(session, connection_id)
        if record.status == "paused":
            raise InvalidTransition("Paused connections cannot be checked.")
        credential = self.credential_vault.decrypt(record.credential_ciphertext)
        checked_at = datetime.now(UTC)
        try:
            result = self.connection_inspector.check(record, credential)
        except ConnectionCheckError as exc:
            record.status = "error"
            record.last_checked_at = checked_at
            record.last_error = str(exc)
            self._audit(
                session,
                record.model_id,
                "model.connection_check_failed",
                actor,
                {"connection_id": record.id, "kind": record.kind, "error": str(exc)},
            )
            session.commit()
            return ConnectionCheckResponse(
                connection=ConnectionResponse.model_validate(record), healthy=False
            )

        record.status = "connected"
        record.last_checked_at = checked_at
        record.last_status_code = result.status_code
        record.last_latency_ms = result.latency_ms
        record.last_error = None
        record.discovered_metadata = result.metadata
        self._audit(
            session,
            record.model_id,
            "model.connection_checked",
            actor,
            {
                "connection_id": record.id,
                "kind": record.kind,
                "status_code": result.status_code,
                "latency_ms": result.latency_ms,
            },
        )
        session.commit()
        return ConnectionCheckResponse(
            connection=ConnectionResponse.model_validate(record), healthy=True
        )

    def delete_connection(self, session: Session, connection_id: str, *, actor: str) -> None:
        record = self._require_connection(session, connection_id)
        model_id = record.model_id
        details = {"connection_id": record.id, "kind": record.kind, "name": record.name}
        session.delete(record)
        self._audit(session, model_id, "model.connection_deleted", actor, details)
        session.commit()

    def get_model(self, session: Session, model_id: str) -> ModelResponse:
        return self._model_response(self._require_model(session, model_id))

    def update_model(
        self,
        session: Session,
        model_id: str,
        payload: ModelUpdate,
    ) -> ModelResponse:
        record = self._require_model(session, model_id)
        changes = payload.model_dump(exclude_unset=True, exclude={"actor"})
        if "name" in changes and changes["name"] != record.name:
            duplicate = session.scalar(
                select(MonitoredModel).where(
                    MonitoredModel.tenant_id == record.tenant_id,
                    MonitoredModel.name == changes["name"],
                    MonitoredModel.id != model_id,
                )
            )
            if duplicate:
                raise ResourceConflict(
                    f"A monitored model named '{changes['name']}' already exists."
                )

        previous = {name: getattr(record, name) for name in changes}
        for name, value in changes.items():
            setattr(record, name, value)
        session.flush()
        self._audit(
            session,
            record.id,
            "model.updated",
            payload.actor,
            {"before": previous, "after": changes},
        )
        session.commit()
        return self._model_response(record)

    def update_model_lifecycle(
        self,
        session: Session,
        model_id: str,
        payload: ModelLifecycleUpdate,
    ) -> ModelResponse:
        record = self._require_model(session, model_id)
        requested = ModelStatus(payload.status)
        current = ModelStatus(record.status)
        if current is ModelStatus.RETIRED and requested is not ModelStatus.RETIRED:
            raise InvalidTransition("A retired model cannot be reactivated.")
        if current is requested:
            return self._model_response(record)

        record.status = requested
        self._audit(
            session,
            record.id,
            "model.lifecycle_changed",
            payload.actor,
            {"from": current.value, "to": requested.value},
        )
        session.commit()
        return self._model_response(record)

    def create_model_version(
        self,
        session: Session,
        model_id: str,
        payload: ModelVersionCreate,
        *,
        actor: str,
    ) -> ModelVersionResponse:
        model = self._require_model(session, model_id)
        if ModelStatus(model.status) is ModelStatus.RETIRED:
            raise InvalidTransition("Cannot add a version to a retired model.")
        version = self._create_model_version(session, model, payload)
        self._audit(
            session,
            model.id,
            "model.version_created",
            actor,
            {
                "version_id": version.id,
                "label": version.label,
                "fingerprint": version.fingerprint,
            },
        )
        session.commit()
        return ModelVersionResponse.model_validate(version)

    def list_model_versions(
        self,
        session: Session,
        model_id: str,
    ) -> list[ModelVersionResponse]:
        self._require_model(session, model_id)
        records = session.scalars(
            select(ModelVersion)
            .where(ModelVersion.model_id == model_id)
            .order_by(ModelVersion.created_at.desc())
        ).all()
        return [ModelVersionResponse.model_validate(record) for record in records]

    def activate_model_version(
        self,
        session: Session,
        model_id: str,
        version_id: str,
        *,
        actor: str,
    ) -> ModelVersionResponse:
        model = self._require_model(session, model_id)
        if ModelStatus(model.status) is ModelStatus.RETIRED:
            raise InvalidTransition("Cannot activate a version of a retired model.")
        target = session.scalar(
            select(ModelVersion).where(
                ModelVersion.id == version_id,
                ModelVersion.model_id == model_id,
            )
        )
        if target is None:
            raise ResourceNotFound("Model version not found.")
        if target.active_to is None:
            return ModelVersionResponse.model_validate(target)

        now = datetime.now(UTC)
        active_versions = session.scalars(
            select(ModelVersion).where(
                ModelVersion.model_id == model_id,
                ModelVersion.active_to.is_(None),
            )
        ).all()
        for version in active_versions:
            version.active_to = now
        target.active_from = now
        target.active_to = None
        self._audit(
            session,
            model.id,
            "model.version_activated",
            actor,
            {"version_id": target.id, "fingerprint": target.fingerprint},
        )
        session.commit()
        return ModelVersionResponse.model_validate(target)

    def registration_status(
        self,
        session: Session,
        model_id: str,
    ) -> RegistrationStatusResponse:
        model = self._require_model(session, model_id)
        active_version = self._active_model_version(session, model_id)
        latest_snapshot = session.scalar(
            select(HealthSnapshot)
            .where(HealthSnapshot.model_id == model_id)
            .order_by(HealthSnapshot.observed_at.desc())
            .limit(1)
        )
        connections = session.scalars(
            select(ModelConnection).where(ModelConnection.model_id == model_id)
        ).all()
        connection_kinds = sorted({connection.kind for connection in connections})
        connected_connections = sum(
            connection.status == "connected" for connection in connections
        )
        active = ModelStatus(model.status) is ModelStatus.ACTIVE
        checks = [
            RegistrationCheck(
                code="identity_registered",
                passed=True,
                detail="The monitored model has a persistent DriftZero ID.",
            ),
            RegistrationCheck(
                code="lifecycle_active",
                passed=active,
                detail=f"Model lifecycle state is '{ModelStatus(model.status).value}'.",
            ),
            RegistrationCheck(
                code="provider_configured",
                passed=bool(model.provider.strip()),
                detail=f"Telemetry is attributed to provider '{model.provider}'.",
            ),
            RegistrationCheck(
                code="active_version_fingerprinted",
                passed=active_version is not None,
                detail=(
                    "Controlled model inputs have a reproducible fingerprint."
                    if active_version
                    else "Register a model version before sending production telemetry."
                ),
            ),
            RegistrationCheck(
                code="telemetry_received",
                passed=latest_snapshot is not None,
                detail=(
                    "At least one health snapshot has been stored."
                    if latest_snapshot
                    else "Registration is ready, but no telemetry has arrived yet."
                ),
            ),
            RegistrationCheck(
                code="connection_configured",
                passed=bool(connections),
                detail=(
                    f"{len(connections)} source connection(s) registered."
                    if connections
                    else "Add GitHub, telemetry, website, or API evidence sources."
                ),
            ),
        ]
        ready = active and active_version is not None and bool(model.provider.strip())
        if not active:
            monitoring_state = "paused"
        elif latest_snapshot is None:
            monitoring_state = "awaiting_telemetry"
        else:
            monitoring_state = "receiving_telemetry"
        return RegistrationStatusResponse(
            model_id=model.id,
            ready_for_telemetry=ready,
            monitoring_state=monitoring_state,
            active_version_id=active_version.id if active_version else None,
            connection_kinds=connection_kinds,
            connected_connections=connected_connections,
            checks=checks,
        )

    def record_telemetry(
        self,
        session: Session,
        model_id: str,
        payload: TelemetryCreate,
        *,
        ingestion_key: str | None = None,
    ) -> HealthSnapshotResponse:
        self._require_model(session, model_id)
        observed_at = payload.observed_at
        if observed_at.tzinfo is None:
            observed_at = observed_at.replace(tzinfo=UTC)
        if (
            payload.source is SignalSource.OBSERVED
            and observed_at
            > datetime.now(UTC)
            + timedelta(seconds=self.settings.telemetry_max_future_skew_seconds)
        ):
            raise TelemetryIngestionError(
                "Telemetry observed_at is too far in the future. Check the producer clock."
            )
        telemetry_connections = session.scalars(
            select(ModelConnection).where(
                ModelConnection.model_id == model_id,
                ModelConnection.kind == "telemetry",
                ModelConnection.status != "paused",
            )
        ).all()
        if not telemetry_connections and self.settings.environment.lower() in {
            "production",
            "prod",
        }:
            raise AuthorizationDenied(
                "Configure a telemetry connection before ingesting production telemetry."
            )
        if telemetry_connections:
            supplied_hash = hashlib.sha256((ingestion_key or "").encode()).hexdigest()
            if not any(
                connection.ingest_key_hash
                and secrets.compare_digest(connection.ingest_key_hash, supplied_hash)
                for connection in telemetry_connections
            ):
                raise AuthorizationDenied("A valid telemetry ingestion key is required.")
        if payload.event_id:
            existing = session.scalar(
                select(HealthSnapshot).where(
                    HealthSnapshot.model_id == model_id,
                    HealthSnapshot.event_id == payload.event_id,
                )
            )
            if existing is not None:
                return self._snapshot_response(existing)
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

    def record_shopassist_telemetry(
        self,
        session: Session,
        payload: ShopAssistTelemetryCreate,
    ) -> HealthSnapshotResponse:
        """Resolve ShopAssist server-side and accept one evidence-qualified window."""

        model = session.scalar(
            select(MonitoredModel).where(
                MonitoredModel.tenant_id == self._tenant_id(session),
                MonitoredModel.name == "ShopAssist",
            )
        )
        if model is None:
            raise ResourceNotFound(
                "ShopAssist is not initialized. Run POST /api/v1/demo/reset first."
            )
        if payload.sample_size < self.settings.minimum_sample_size:
            raise TelemetryIngestionError(
                "ShopAssist telemetry window requires at least "
                f"{self.settings.minimum_sample_size} samples; received {payload.sample_size}."
            )
        return self.record_telemetry(session, model.id, payload)

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
        model = self._require_model(session, model_id)
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
        evidence = list(result.evidence)
        if model.name == "ShopAssist" and result.probable_cause == "knowledge_freshness_failure":
            evidence.append(
                EvidenceItem(
                    reason_code="RETIRED_RETURN_POLICY_RETRIEVED",
                    metric="groundedness",
                    summary=(
                        "ShopAssist traces cite the retired 14-day returns policy while the "
                        "current approved policy allows returns within 30 days."
                    ),
                    baseline_value=baseline.groundedness,
                    current_value=latest.groundedness,
                    change=round(latest.groundedness - baseline.groundedness, 1),
                    supports_diagnosis=True,
                )
            )
        incident = self._open_incident(session, model_id)
        diagnosis = Diagnosis(
            model_id=model_id,
            snapshot_id=latest.id,
            incident_id=incident.id if incident else None,
            probable_cause=result.probable_cause,
            confidence=result.confidence,
            status=DiagnosisStatus.OPEN.value,
            evidence=[item.model_dump(mode="json") for item in evidence],
        )
        session.add(diagnosis)
        session.flush()
        self._record_evidence(session, diagnosis, latest, evidence)
        self._advance_incident(session, incident, IncidentState.DIAGNOSING)

        playbook = build_playbook(result.probable_cause)
        plan = RecoveryPlan(
            model_id=model_id,
            diagnosis_id=diagnosis.id,
            incident_id=diagnosis.incident_id,
            state=RecoveryState.RECOMMENDED.value,
            risk=playbook.risk.value,
            approval_level=playbook.risk.value,
            requires_approval=True,
            policy_version=self.recovery_policy.version,
            actions=[action.model_dump(mode="json") for action in playbook.actions],
            simulation=self.recovery_adapter.simulation,
        )
        session.add(plan)
        session.flush()
        for action in playbook.actions:
            session.add(
                RecoveryActionRecord(
                    plan_id=plan.id,
                    order=action.order,
                    code=action.code,
                    title=action.title,
                    description=action.description,
                    risk=action.risk.value,
                    reversible=action.reversible,
                    adapter=type(self.recovery_adapter).__name__,
                    is_simulated=self.recovery_adapter.simulation,
                )
            )
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

    def get_recovery(self, session: Session, plan_id: str) -> RecoveryPlanResponse:
        return self._recovery_response(self._require_plan(session, plan_id))

    def get_recovery_command(
        self, session: Session, command_id: str
    ) -> RecoveryCommandResponse:
        command = session.get(RecoveryCommand, command_id)
        if command is None:
            raise ResourceNotFound("Recovery command not found.")
        return RecoveryCommandResponse.model_validate(command)

    def recovery_commands(
        self, session: Session, plan_id: str
    ) -> list[RecoveryCommandResponse]:
        self._require_plan(session, plan_id)
        records = session.scalars(
            select(RecoveryCommand)
            .where(RecoveryCommand.plan_id == plan_id)
            .order_by(RecoveryCommand.requested_at)
        ).all()
        return [RecoveryCommandResponse.model_validate(record) for record in records]

    def enqueue_recovery(
        self,
        session: Session,
        plan_id: str,
        payload: RecoveryExecuteRequest,
    ) -> RecoveryCommandResponse:
        plan = self._require_plan(session, plan_id, for_update=True)
        self._check_plan_version(plan, payload)
        self._authorize_recovery(plan, payload)

        existing = session.scalar(
            select(RecoveryCommand).where(
                RecoveryCommand.idempotency_key == payload.idempotency_key
            )
        )
        if existing is not None:
            if existing.plan_id != plan.id or existing.command_type != RecoveryCommandType.EXECUTE:
                raise ResourceConflict("Idempotency key belongs to a different command.")
            return RecoveryCommandResponse.model_validate(existing)

        if plan.state != RecoveryState.APPROVED.value:
            raise InvalidTransition("Recovery must be approved before it can be queued.")
        active = session.scalar(
            select(RecoveryCommand.id).where(
                RecoveryCommand.plan_id == plan.id,
                RecoveryCommand.state.in_(
                    [RecoveryCommandState.PENDING.value, RecoveryCommandState.RUNNING.value]
                ),
            )
        )
        if active is not None:
            raise ResourceConflict("A recovery command is already active for this plan.")

        self._validate_blast_radius(session, plan, payload.max_traffic_pct)
        now = datetime.now(UTC)
        command = RecoveryCommand(
            plan_id=plan.id,
            command_type=RecoveryCommandType.EXECUTE.value,
            state=RecoveryCommandState.PENDING.value,
            idempotency_key=payload.idempotency_key,
            actor=payload.actor,
            actor_role=payload.role.value,
            reason=payload.reason,
            max_traffic_pct=payload.max_traffic_pct,
            max_attempts=self.settings.recovery_command_max_attempts,
            requested_at=now,
            available_at=now,
        )
        session.add(command)
        plan.state = RecoveryState.QUEUED.value
        plan.idempotency_key = payload.idempotency_key
        plan.version += 1
        session.flush()
        self._audit(
            session,
            plan.model_id,
            "recovery.queued",
            payload.actor,
            {"plan_id": plan.id, "command_id": command.id},
        )
        session.commit()
        return RecoveryCommandResponse.model_validate(command)

    def enqueue_verification(
        self,
        session: Session,
        plan_id: str,
        payload: RecoveryVerifyRequest,
    ) -> RecoveryCommandResponse:
        plan = self._require_plan(session, plan_id, for_update=True)
        self._authorize_recovery(plan, payload)
        if plan.state != RecoveryState.VERIFYING.value:
            raise InvalidTransition("Recovery must be awaiting verification.")
        snapshot = session.get(HealthSnapshot, payload.snapshot_id)
        if snapshot is None or snapshot.model_id != plan.model_id:
            raise ResourceNotFound("Verification snapshot not found for this model.")
        existing = session.scalar(
            select(RecoveryCommand).where(
                RecoveryCommand.idempotency_key == payload.idempotency_key
            )
        )
        if existing is not None:
            if existing.plan_id != plan.id or existing.command_type != RecoveryCommandType.VERIFY:
                raise ResourceConflict("Idempotency key belongs to a different command.")
            return RecoveryCommandResponse.model_validate(existing)

        command = self._new_verification_command(
            plan,
            snapshot,
            actor=payload.actor,
            role=payload.role,
            idempotency_key=payload.idempotency_key,
            reason=payload.reason,
        )
        session.add(command)
        session.flush()
        self._audit(
            session,
            plan.model_id,
            "recovery.verification_queued",
            payload.actor,
            {"plan_id": plan.id, "command_id": command.id, "snapshot_id": snapshot.id},
        )
        session.commit()
        return RecoveryCommandResponse.model_validate(command)

    def enqueue_rollback(
        self,
        session: Session,
        plan_id: str,
        payload: RecoveryRollbackRequest,
    ) -> RecoveryCommandResponse:
        plan = self._require_plan(session, plan_id, for_update=True)
        self._check_plan_version(plan, payload)
        self._authorize_recovery(plan, payload)
        if plan.state not in {RecoveryState.RECOVERED.value, RecoveryState.FAILED.value}:
            raise InvalidTransition(f"Cannot roll back a plan in '{plan.state}' state.")
        existing = session.scalar(
            select(RecoveryCommand).where(
                RecoveryCommand.idempotency_key == payload.idempotency_key
            )
        )
        if existing is not None:
            if existing.plan_id != plan.id or existing.command_type != RecoveryCommandType.ROLLBACK:
                raise ResourceConflict("Idempotency key belongs to a different command.")
            return RecoveryCommandResponse.model_validate(existing)
        active = session.scalar(
            select(RecoveryCommand.id).where(
                RecoveryCommand.plan_id == plan.id,
                RecoveryCommand.state.in_(
                    [RecoveryCommandState.PENDING.value, RecoveryCommandState.RUNNING.value]
                ),
            )
        )
        if active is not None:
            raise ResourceConflict("A recovery command is already active for this plan.")

        now = datetime.now(UTC)
        command = RecoveryCommand(
            plan_id=plan.id,
            command_type=RecoveryCommandType.ROLLBACK.value,
            state=RecoveryCommandState.PENDING.value,
            idempotency_key=payload.idempotency_key,
            actor=payload.actor,
            actor_role=payload.role.value,
            reason=payload.reason,
            max_traffic_pct=100.0,
            max_attempts=self.settings.recovery_command_max_attempts,
            requested_at=now,
            available_at=now,
        )
        session.add(command)
        session.flush()
        self._audit(
            session,
            plan.model_id,
            "recovery.rollback_queued",
            payload.actor,
            {"plan_id": plan.id, "command_id": command.id},
        )
        session.commit()
        return RecoveryCommandResponse.model_validate(command)

    def recovery_executions(
        self, session: Session, plan_id: str
    ) -> list[RecoveryExecutionResponse]:
        plan = self._require_plan(session, plan_id)
        return [
            RecoveryExecutionResponse.model_validate(execution)
            for action in plan.action_items
            for execution in sorted(action.executions, key=lambda item: item.attempt)
        ]

    def recovery_verification(
        self, session: Session, plan_id: str
    ) -> VerificationRunResponse:
        plan = self._require_plan(session, plan_id)
        verification = max(
            plan.verification_runs, key=lambda run: run.started_at, default=None
        )
        if verification is None:
            raise ResourceNotFound("No verification run exists for this recovery plan.")
        return VerificationRunResponse.model_validate(verification)

    def approve_recovery(
        self,
        session: Session,
        plan_id: str,
        payload: ActorRequest,
    ) -> RecoveryPlanResponse:
        plan = self._require_plan(session, plan_id, for_update=True)
        self._check_plan_version(plan, payload)
        self._authorize_recovery(plan, payload)
        if plan.state in {RecoveryState.APPROVED.value, RecoveryState.RECOVERED.value}:
            return self._recovery_response(plan)
        if plan.state != RecoveryState.RECOMMENDED.value:
            raise InvalidTransition(f"Cannot approve a plan in '{plan.state}' state.")

        plan.state = RecoveryState.APPROVED.value
        plan.approved_at = datetime.now(UTC)
        plan.approved_by = payload.actor
        plan.approved_role = payload.role.value
        plan.approval_reason = payload.reason
        plan.version += 1
        self._advance_incident(
            session, self._open_incident(session, plan.model_id), IncidentState.MITIGATING
        )
        self._audit(
            session,
            plan.model_id,
            "recovery.approved",
            payload.actor,
            {"plan_id": plan.id, "risk": plan.risk, "simulation": plan.simulation},
        )
        session.commit()
        return self._recovery_response(plan)

    def reject_recovery(
        self,
        session: Session,
        plan_id: str,
        payload: ActorRequest,
    ) -> RecoveryPlanResponse:
        plan = self._require_plan(session, plan_id, for_update=True)
        self._check_plan_version(plan, payload)
        self._authorize_recovery(plan, payload)
        if plan.state == RecoveryState.REJECTED.value:
            return self._recovery_response(plan)
        if plan.state != RecoveryState.RECOMMENDED.value:
            raise InvalidTransition(f"Cannot reject a plan in '{plan.state}' state.")

        plan.state = RecoveryState.REJECTED.value
        plan.rejected_at = datetime.now(UTC)
        plan.rejected_by = payload.actor
        plan.rejected_reason = payload.reason
        plan.version += 1
        self._audit(
            session,
            plan.model_id,
            "recovery.rejected",
            payload.actor,
            {"plan_id": plan.id, "reason": payload.reason},
        )
        session.commit()
        return self._recovery_response(plan)

    def cancel_recovery(
        self,
        session: Session,
        plan_id: str,
        payload: ActorRequest,
    ) -> RecoveryPlanResponse:
        plan = self._require_plan(session, plan_id, for_update=True)
        self._check_plan_version(plan, payload)
        self._authorize_recovery(plan, payload)
        if plan.state == RecoveryState.CANCELED.value:
            return self._recovery_response(plan)
        cancelable = {
            RecoveryState.RECOMMENDED.value,
            RecoveryState.APPROVED.value,
            RecoveryState.QUEUED.value,
        }
        if plan.state not in cancelable:
            raise InvalidTransition(f"Cannot cancel a plan in '{plan.state}' state.")

        plan.state = RecoveryState.CANCELED.value
        plan.failure_reason = payload.reason or "Canceled by operator."
        plan.version += 1
        for command in plan.commands:
            if RecoveryCommandState(command.state) is RecoveryCommandState.PENDING:
                command.state = RecoveryCommandState.CANCELED.value
                command.completed_at = datetime.now(UTC)
        self._audit(
            session,
            plan.model_id,
            "recovery.canceled",
            payload.actor,
            {"plan_id": plan.id, "reason": plan.failure_reason},
        )
        session.commit()
        return self._recovery_response(plan)

    def execute_recovery(
        self,
        session: Session,
        plan_id: str,
        payload: ActorRequest,
    ) -> RecoveryPlanResponse:
        plan = self._require_plan(session, plan_id, for_update=True)
        self._check_plan_version(plan, payload)
        self._authorize_recovery(plan, payload)
        idempotency_key = getattr(payload, "idempotency_key", None)
        if plan.idempotency_key is not None:
            if idempotency_key != plan.idempotency_key:
                raise ResourceConflict("Recovery already has a different idempotency key.")
            if plan.state not in {
                RecoveryState.APPROVED.value,
                RecoveryState.QUEUED.value,
                RecoveryState.EXECUTING.value,
            }:
                return self._recovery_response(plan)
        if plan.state == RecoveryState.RECOVERED.value:
            return self._recovery_response(plan)
        if plan.state not in {
            RecoveryState.APPROVED.value,
            RecoveryState.QUEUED.value,
            RecoveryState.EXECUTING.value,
        }:
            raise InvalidTransition("Recovery must be approved before execution.")

        max_traffic_pct = getattr(payload, "max_traffic_pct", 100.0)
        self._validate_blast_radius(session, plan, max_traffic_pct)

        resuming = plan.state == RecoveryState.EXECUTING.value
        plan.state = RecoveryState.EXECUTING.value
        plan.idempotency_key = idempotency_key
        if not resuming:
            plan.executed_at = datetime.now(UTC)
            plan.version += 1
        incident = self._open_incident(session, plan.model_id)
        self._advance_incident(session, incident, IncidentState.VERIFYING)
        if not resuming:
            self._audit(
                session,
                plan.model_id,
                "recovery.execution_started",
                payload.actor,
                {"plan_id": plan.id, "simulation": plan.simulation},
            )
        session.flush()

        baseline_snapshot = latest_snapshot(session, plan.model_id)
        try:
            executions = self._apply_actions(session, plan, payload.actor)
            failed_execution = next(
                (
                    execution
                    for execution in executions
                    if ExecutionState(execution.state) is ExecutionState.FAILED
                ),
                None,
            )
            if failed_execution is not None:
                self._rollback_actions(session, plan, executions, payload.actor)
                plan.state = RecoveryState.FAILED.value
                plan.version += 1
                plan.failure_reason = (
                    failed_execution.error
                    or f"Recovery action {failed_execution.action_id} failed."
                )
                plan.rolled_back_at = datetime.now(UTC)
                if incident is not None and baseline_snapshot is not None:
                    self._close_incident(
                        session,
                        incident,
                        baseline_snapshot,
                        resolved=False,
                    )
                self._audit(
                    session,
                    plan.model_id,
                    "recovery.failed",
                    payload.actor,
                    {
                        "plan_id": plan.id,
                        "failed_execution_id": failed_execution.id,
                        "reason": plan.failure_reason,
                    },
                )
                session.commit()
                return self._recovery_response(plan)

            plan.state = RecoveryState.VERIFYING.value
            plan.version += 1
            result = self.recovery_adapter.execute(model_id=plan.model_id, plan_id=plan.id)
            if result is None:
                self._audit(
                    session,
                    plan.model_id,
                    "recovery.verification_pending",
                    "recovery-worker",
                    {
                        "plan_id": plan.id,
                        "required_requests": self.settings.recovery_verification_requests,
                        "required_coverage": self.settings.recovery_verification_coverage,
                    },
                )
                session.commit()
                return self._recovery_response(plan)
            snapshot = self._record_telemetry(
                session,
                plan.model_id,
                TelemetryCreate(
                    observed_at=datetime.now(UTC) + timedelta(seconds=1),
                    dimensions=result.dimensions,
                    sample_size=result.evaluated_requests,
                    coverage=result.coverage,
                    source=SignalSource.SIMULATED,
                ),
                allow_verifying_resolution=False,
            )
            verification = self._verify(
                session,
                plan,
                incident,
                baseline_snapshot,
                snapshot,
                evaluated_requests=result.evaluated_requests,
            )
            recovered = bool(verification.passed)
            plan.state = (
                RecoveryState.RECOVERED.value if recovered else RecoveryState.FAILED.value
            )
            plan.version += 1
            plan.verified_at = datetime.now(UTC)
            if not recovered:
                # Leave the system no worse than we found it: undo what can be
                # undone, and record what could not.
                self._rollback_actions(session, plan, executions, payload.actor)
                plan.rolled_back_at = datetime.now(UTC)
            if recovered:
                if incident is not None:
                    self._close_incident(session, incident, snapshot, resolved=True)
                diagnosis = session.get(Diagnosis, plan.diagnosis_id)
                if diagnosis:
                    diagnosis.status = DiagnosisStatus.RESOLVED.value
            elif incident is not None:
                self._close_incident(session, incident, snapshot, resolved=False)
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
                    "verification_run_id": verification.id,
                    "threshold": verification.threshold,
                    "no_regression_checks": verification.no_regression_checks,
                },
            )
            session.commit()
        except Exception:
            session.rollback()
            failed_plan = self._require_plan(session, plan_id, for_update=True)
            failed_plan.state = RecoveryState.QUEUED.value
            failed_plan.failure_reason = "Recovery execution was interrupted and will be retried."
            failed_plan.version += 1
            self._audit(
                session,
                failed_plan.model_id,
                "recovery.execution_interrupted",
                "recovery-worker",
                {"plan_id": failed_plan.id},
            )
            session.commit()
            raise

        return self._recovery_response(plan)

    def _validate_blast_radius(
        self, session: Session, plan: RecoveryPlan, max_traffic_pct: float
    ) -> None:
        for record in self._plan_actions(session, plan.id):
            action = RecoveryAction(
                order=record.order,
                code=record.code,
                title=record.title,
                description=record.description,
                risk=RiskLevel(record.risk),
                reversible=record.reversible,
            )
            estimator = getattr(self.recovery_adapter, "estimate_traffic_pct", None)
            estimated_traffic_pct = estimator(action=action) if estimator else 100.0
            if estimated_traffic_pct > max_traffic_pct:
                raise InvalidTransition(
                    f"Action '{record.code}' would affect {estimated_traffic_pct}% of traffic; "
                    f"request permits at most {max_traffic_pct}%."
                )

    def rollback_recovery(
        self,
        session: Session,
        plan_id: str,
        payload: ActorRequest,
    ) -> RecoveryPlanResponse:
        plan = self._require_plan(session, plan_id, for_update=True)
        self._check_plan_version(plan, payload)
        self._authorize_recovery(plan, payload)
        if plan.state == RecoveryState.ROLLED_BACK.value:
            return self._recovery_response(plan)
        if plan.state not in {RecoveryState.RECOVERED.value, RecoveryState.FAILED.value}:
            raise InvalidTransition(f"Cannot roll back a plan in '{plan.state}' state.")

        executions = [
            execution
            for action in plan.action_items
            for execution in action.executions
        ]
        if not any(
            ExecutionState(execution.state) is ExecutionState.SUCCEEDED
            for execution in executions
        ):
            raise InvalidTransition("No applied recovery actions are available to roll back.")

        self._rollback_actions(session, plan, executions, payload.actor)
        plan.state = RecoveryState.ROLLED_BACK.value
        plan.rolled_back_at = datetime.now(UTC)
        plan.version += 1
        session.commit()
        return self._recovery_response(plan)

    def verify_recovery(
        self,
        session: Session,
        plan_id: str,
        snapshot_id: str,
    ) -> RecoveryPlanResponse:
        plan = self._require_plan(session, plan_id, for_update=True)
        if plan.state in {RecoveryState.RECOVERED.value, RecoveryState.FAILED.value}:
            return self._recovery_response(plan)
        if plan.state != RecoveryState.VERIFYING.value:
            raise InvalidTransition("Recovery is not awaiting verification.")
        snapshot = session.get(HealthSnapshot, snapshot_id)
        if snapshot is None or snapshot.model_id != plan.model_id:
            raise ResourceNotFound("Verification snapshot not found for this model.")
        if plan.executed_at is not None and snapshot.observed_at <= plan.executed_at:
            raise InvalidTransition("Verification requires telemetry observed after execution.")

        baseline = session.scalar(
            select(HealthSnapshot)
            .where(
                HealthSnapshot.model_id == plan.model_id,
                HealthSnapshot.observed_at < (plan.executed_at or snapshot.observed_at),
            )
            .order_by(HealthSnapshot.observed_at.desc())
            .limit(1)
        )
        incident = session.get(Incident, plan.incident_id) if plan.incident_id else None
        verification = self._verify(
            session,
            plan,
            incident,
            baseline,
            snapshot,
            evaluated_requests=snapshot.sample_size,
        )
        recovered = bool(verification.passed)
        plan.state = (
            RecoveryState.RECOVERED.value if recovered else RecoveryState.FAILED.value
        )
        plan.verified_at = datetime.now(UTC)
        plan.version += 1
        if recovered:
            if incident is not None:
                self._close_incident(session, incident, snapshot, resolved=True)
            diagnosis = session.get(Diagnosis, plan.diagnosis_id)
            if diagnosis:
                diagnosis.status = DiagnosisStatus.RESOLVED.value
        else:
            executions = [
                execution
                for action in plan.action_items
                for execution in action.executions
            ]
            self._rollback_actions(session, plan, executions, "verification-engine")
            plan.rolled_back_at = datetime.now(UTC)
            if incident is not None:
                self._close_incident(session, incident, snapshot, resolved=False)
        self._audit(
            session,
            plan.model_id,
            "recovery.verified",
            "verification-engine",
            {
                "plan_id": plan.id,
                "snapshot_id": snapshot.id,
                "verification_run_id": verification.id,
                "outcome": plan.state,
            },
        )
        session.commit()
        return self._recovery_response(plan)

    def fail_recovery_after_retries(
        self,
        session: Session,
        plan_id: str,
        reason: str,
    ) -> RecoveryPlanResponse:
        """Terminally fail a command after its durable retry budget is exhausted."""

        plan = self._require_plan(session, plan_id, for_update=True)
        if plan.state in {
            RecoveryState.RECOVERED.value,
            RecoveryState.FAILED.value,
            RecoveryState.ROLLED_BACK.value,
        }:
            return self._recovery_response(plan)
        executions = [
            execution
            for action in plan.action_items
            for execution in action.executions
        ]
        self._rollback_actions(session, plan, executions, "recovery-worker")
        uncertain = [
            execution.id
            for execution in executions
            if ExecutionState(execution.state) is ExecutionState.RUNNING
        ]
        if uncertain:
            self._queue_for_review(
                session,
                plan.model_id,
                reason="Recovery action outcome is uncertain after worker failure.",
                incident_id=plan.incident_id,
            )
        plan.state = RecoveryState.FAILED.value
        plan.failure_reason = reason
        plan.rolled_back_at = datetime.now(UTC)
        plan.version += 1
        incident = session.get(Incident, plan.incident_id) if plan.incident_id else None
        snapshot = latest_snapshot(session, plan.model_id)
        if incident is not None and snapshot is not None:
            self._close_incident(session, incident, snapshot, resolved=False)
        self._audit(
            session,
            plan.model_id,
            "recovery.retry_exhausted",
            "recovery-worker",
            {"plan_id": plan.id, "reason": reason, "uncertain_execution_ids": uncertain},
        )
        session.commit()
        return self._recovery_response(plan)

    def _new_verification_command(
        self,
        plan: RecoveryPlan,
        snapshot: HealthSnapshot,
        *,
        actor: str,
        role: ActorRole,
        idempotency_key: str,
        reason: str | None = None,
    ) -> RecoveryCommand:
        now = datetime.now(UTC)
        return RecoveryCommand(
            plan_id=plan.id,
            command_type=RecoveryCommandType.VERIFY.value,
            state=RecoveryCommandState.PENDING.value,
            idempotency_key=idempotency_key,
            actor=actor,
            actor_role=role.value,
            reason=reason,
            max_traffic_pct=0.0,
            max_attempts=self.settings.recovery_command_max_attempts,
            requested_at=now,
            available_at=now,
            snapshot_id=snapshot.id,
        )

    def _authorize_recovery(self, plan: RecoveryPlan, payload: ActorRequest) -> None:
        decision = self.recovery_policy.authorize(
            risk=RiskLevel(plan.risk),
            role=payload.role,
        )
        if not decision.allowed:
            raise AuthorizationDenied(decision.reason)

    @staticmethod
    def _check_plan_version(plan: RecoveryPlan, payload: ActorRequest) -> None:
        expected = getattr(payload, "expected_version", None)
        if expected is not None and expected != plan.version:
            raise ResourceConflict(
                f"Recovery plan version changed: expected {expected}, current {plan.version}."
            )

    def _plan_actions(self, session: Session, plan_id: str) -> list[RecoveryActionRecord]:
        return list(
            session.scalars(
                select(RecoveryActionRecord)
                .where(RecoveryActionRecord.plan_id == plan_id)
                .order_by(RecoveryActionRecord.order)
            ).all()
        )

    def _apply_actions(
        self,
        session: Session,
        plan: RecoveryPlan,
        actor: str,
    ) -> list[RecoveryExecution]:
        """Apply each action in order, recording one execution row per attempt.

        A step that fails does not abort the rest: the remaining actions are
        recorded as skipped rather than silently omitted, so the record shows
        exactly how far the playbook got.
        """

        executions: list[RecoveryExecution] = []
        aborted = False

        for record in self._plan_actions(session, plan.id):
            execution = max(record.executions, key=lambda item: item.attempt, default=None)
            if execution is not None:
                existing_state = ExecutionState(execution.state)
                if existing_state is ExecutionState.SUCCEEDED:
                    executions.append(execution)
                    continue
                if existing_state in {
                    ExecutionState.FAILED,
                    ExecutionState.SKIPPED,
                    ExecutionState.ROLLED_BACK,
                }:
                    executions.append(execution)
                    aborted = True
                    continue
            else:
                execution = RecoveryExecution(
                    action_id=record.id,
                    plan_id=plan.id,
                    actor=actor,
                    actor_type=ActorType.HUMAN.value,
                    reason=f"Executing playbook step {record.order}: {record.code}",
                    state=(
                        ExecutionState.SKIPPED.value
                        if aborted
                        else ExecutionState.RUNNING.value
                    ),
                    timeout_seconds=max(
                        1, ceil(self.settings.recovery_control_timeout_seconds)
                    ),
                )
                session.add(execution)

            if aborted:
                session.flush()
                executions.append(execution)
                continue

            execution.started_at = execution.started_at or datetime.now(UTC)
            session.flush()
            # Persist intent before crossing the privileged adapter boundary.
            # A crashed worker therefore leaves a reclaimable RUNNING record
            # with a stable idempotency key instead of losing what it attempted.
            session.commit()
            action = RecoveryAction(
                order=record.order,
                code=record.code,
                title=record.title,
                description=record.description,
                risk=RiskLevel(record.risk),
                reversible=record.reversible,
            )
            outcome = self._invoke_adapter_action(
                "execute_action",
                model_id=plan.model_id,
                plan_id=plan.id,
                action=action,
                execution_id=execution.id,
            )
            execution.finished_at = datetime.now(UTC)
            execution.affected_traffic_pct = outcome.affected_traffic_pct
            execution.result = dict(outcome.detail)
            execution.error = outcome.error
            execution.external_operation_id = outcome.external_operation_id
            execution.config_before = dict(outcome.config_before)
            execution.config_after = dict(outcome.config_after)
            execution.configuration_verified_at = (
                datetime.now(UTC) if outcome.configuration_verified else None
            )
            execution.state = (
                ExecutionState.SUCCEEDED.value if outcome.succeeded else ExecutionState.FAILED.value
            )
            aborted = not outcome.succeeded
            session.flush()
            session.commit()

            if outcome.succeeded and record.code in self._REVIEW_ROUTING_ACTIONS:
                # The playbook said to involve a human; that only means something
                # if the work actually lands in front of one.
                self._queue_for_review(
                    session,
                    plan.model_id,
                    reason=record.title,
                    incident_id=plan.incident_id,
                )

            if outcome.succeeded and record.code in self._CORPUS_REFRESH_ACTIONS:
                # Likewise: an action that reports it refreshed the corpus has
                # to leave the corpus refreshed, or the recovery is asserting a
                # fix that anyone inspecting the source can see did not happen.
                self._refresh_knowledge_sources(session, plan.model_id)

            executions.append(execution)

        return executions

    # Playbook steps whose entire purpose is to put a human in the loop.
    _REVIEW_ROUTING_ACTIONS = frozenset({"queue_human_review", "route_human_review"})

    # Playbook steps that re-index the retrieval corpus.
    _CORPUS_REFRESH_ACTIONS = frozenset({"refresh_retrieval_index"})

    def _rollback_actions(
        self,
        session: Session,
        plan: RecoveryPlan,
        executions: list[RecoveryExecution],
        actor: str,
    ) -> None:
        """Undo applied actions in reverse order, recording what could not be."""

        for execution in reversed(executions):
            if ExecutionState(execution.state) is not ExecutionState.SUCCEEDED:
                continue
            record = session.get(RecoveryActionRecord, execution.action_id)
            if record is None:
                continue
            action = RecoveryAction(
                order=record.order,
                code=record.code,
                title=record.title,
                description=record.description,
                risk=RiskLevel(record.risk),
                reversible=record.reversible,
            )
            outcome = self._invoke_adapter_action(
                "rollback_action",
                model_id=plan.model_id,
                plan_id=plan.id,
                action=action,
                execution_id=execution.id,
            )
            execution.rollback_result = dict(outcome.detail)
            if outcome.succeeded:
                execution.state = ExecutionState.ROLLED_BACK.value
                execution.rolled_back_at = datetime.now(UTC)
            else:
                # An irreversible action stays applied; saying otherwise would
                # misrepresent the state of the deployment.
                execution.rollback_result = {
                    **dict(outcome.detail),
                    "error": outcome.error,
                }
            session.flush()
            session.commit()
        self._audit(
            session,
            plan.model_id,
            "recovery.rolled_back",
            actor,
            {
                "plan_id": plan.id,
                "rolled_back": sum(
                    1
                    for execution in executions
                    if ExecutionState(execution.state) is ExecutionState.ROLLED_BACK
                ),
            },
        )

    def _invoke_adapter_action(
        self,
        method_name: str,
        *,
        model_id: str,
        plan_id: str,
        action: RecoveryAction,
        execution_id: str,
    ) -> Any:
        """Call v2 adapters while preserving compatibility with v1 integrations."""

        method = getattr(self.recovery_adapter, method_name)
        kwargs: dict[str, object] = {
            "model_id": model_id,
            "plan_id": plan_id,
            "action": action,
        }
        if "execution_id" in signature(method).parameters:
            kwargs["execution_id"] = execution_id
        return method(**kwargs)

    # Dimensions that must not get worse for a recovery to count, and how much
    # slack to allow before calling a movement a regression.
    _NO_REGRESSION_METRICS = ("quality", "safety", "latency", "reliability", "cost")
    _REGRESSION_TOLERANCE = {
        "quality": 2.0,
        "safety": 2.0,
        "latency": 2.0,
        "reliability": 2.0,
        # Cost is naturally noisier across a mitigation window; a ten-point
        # normalized movement is the materiality boundary for recovery-v2.
        "cost": 10.0,
    }

    def _verify(
        self,
        session: Session,
        plan: RecoveryPlan,
        incident: Incident | None,
        baseline: HealthSnapshot | None,
        snapshot: HealthSnapshot,
        *,
        evaluated_requests: int,
    ) -> VerificationRun:
        """Record what recovery was judged against, alongside the verdict.

        Success is not the score alone: it must clear the threshold *and* not
        have traded one failure for another. Safety, latency and reliability are
        checked against the pre-execution snapshot, and each check is stored so
        the judgement can be inspected rather than trusted.
        """

        threshold = HEALTH_THRESHOLDS["healthy"]
        required_requests = self.settings.recovery_verification_requests
        required_coverage = self.settings.recovery_verification_coverage
        checks: list[dict[str, Any]] = []
        for metric in self._NO_REGRESSION_METRICS:
            before = getattr(baseline, metric, None) if baseline else None
            after = getattr(snapshot, metric, None)
            passed = (
                before is None
                or after is None
                or after >= before - self._REGRESSION_TOLERANCE[metric]
            )
            checks.append(
                {
                    "metric": metric,
                    "baseline": before,
                    "current": after,
                    "passed": passed,
                }
            )

        cleared = snapshot.score is not None and snapshot.score >= threshold
        enough_requests = evaluated_requests >= required_requests
        enough_coverage = snapshot.coverage >= required_coverage
        passed = (
            cleared
            and enough_requests
            and enough_coverage
            and all(check["passed"] for check in checks)
        )

        run = VerificationRun(
            plan_id=plan.id,
            incident_id=incident.id if incident else None,
            snapshot_id=snapshot.id,
            required_requests=required_requests,
            observed_requests=evaluated_requests,
            required_coverage=required_coverage,
            observed_coverage=snapshot.coverage,
            threshold=threshold,
            baseline_score=(
                incident.baseline_score if incident else (baseline.score if baseline else None)
            ),
            post_score=snapshot.score,
            passed=passed,
            no_regression_checks=checks,
            window_start=snapshot.window_start,
            window_end=snapshot.window_end,
            finished_at=datetime.now(UTC),
        )
        session.add(run)
        session.flush()
        return run

    # ---------------------------------------------------------------- #
    # Human review and evaluator feedback
    # ---------------------------------------------------------------- #

    def _queue_for_review(
        self,
        session: Session,
        model_id: str,
        *,
        reason: str,
        incident_id: str | None = None,
        trace_id: str | None = None,
    ) -> ReviewQueueItem:
        item = ReviewQueueItem(
            model_id=model_id,
            incident_id=incident_id,
            trace_id=trace_id,
            reason=reason,
        )
        session.add(item)
        session.flush()
        self._audit(
            session,
            model_id,
            "review.queued",
            "review-router",
            {"item_id": item.id, "reason": reason},
        )
        return item

    def list_review_queue(
        self,
        session: Session,
        model_id: str,
        *,
        state: ReviewState | None = None,
        limit: int = 50,
    ) -> list[ReviewQueueItemResponse]:
        self._require_model(session, model_id)
        statement = select(ReviewQueueItem).where(ReviewQueueItem.model_id == model_id)
        if state is not None:
            statement = statement.where(ReviewQueueItem.state == state.value)
        records = session.scalars(
            statement.order_by(ReviewQueueItem.created_at.desc()).limit(limit)
        ).all()
        return [ReviewQueueItemResponse.model_validate(record) for record in records]

    def decide_review_item(
        self,
        session: Session,
        item_id: str,
        payload: ReviewDecisionRequest,
    ) -> ReviewQueueItemResponse:
        """Record a human decision on a queued item.

        Only a terminal decision is stamped with a decider: moving an item to
        ``in_review`` is claiming it, not deciding it.
        """

        item = session.get(ReviewQueueItem, item_id)
        if item is None:
            raise ResourceNotFound("Review item not found.")
        if ReviewState(item.state) in {ReviewState.APPROVED, ReviewState.REJECTED}:
            raise InvalidTransition("This review item has already been decided.")

        item.state = payload.state.value
        item.notes = payload.notes
        if payload.state is ReviewState.IN_REVIEW:
            item.assigned_to = payload.actor
        else:
            item.decided_by = payload.actor
            item.decided_at = datetime.now(UTC)

        self._audit(
            session,
            item.model_id,
            "review.decided",
            payload.actor,
            {"item_id": item.id, "state": item.state},
        )
        session.commit()
        return ReviewQueueItemResponse.model_validate(item)

    def record_feedback(
        self,
        session: Session,
        payload: EvaluationFeedbackCreate,
    ) -> EvaluationFeedbackResponse:
        """Record a human verdict on an automated judgement.

        Evaluator output is fallible, so disagreement is captured as data rather
        than argued with. The target is validated so feedback cannot accumulate
        against something that does not exist.
        """

        target_model = {
            "diagnosis": Diagnosis,
            "stability_test": StabilityTest,
            "health_snapshot": HealthSnapshot,
        }[payload.target_type.value]
        if session.get(target_model, payload.target_id) is None:
            raise ResourceNotFound(f"No {payload.target_type.value} with that id.")

        record = EvaluationFeedback(
            target_type=payload.target_type.value,
            target_id=payload.target_id,
            actor=payload.actor,
            verdict=payload.verdict.value,
            note=payload.note,
        )
        session.add(record)
        session.flush()
        session.commit()
        return EvaluationFeedbackResponse.model_validate(record)

    def list_feedback(
        self,
        session: Session,
        target_type: str,
        target_id: str,
    ) -> list[EvaluationFeedbackResponse]:
        records = session.scalars(
            select(EvaluationFeedback)
            .where(
                EvaluationFeedback.target_type == target_type,
                EvaluationFeedback.target_id == target_id,
            )
            .order_by(EvaluationFeedback.created_at.desc())
        ).all()
        return [EvaluationFeedbackResponse.model_validate(record) for record in records]

    # ---------------------------------------------------------------- #
    # Alerting
    # ---------------------------------------------------------------- #

    def create_alert_rule(
        self,
        session: Session,
        model_id: str,
        payload: AlertRuleCreate,
    ) -> AlertRuleResponse:
        model = self._require_model(session, model_id)
        existing = session.scalar(
            select(AlertRule).where(AlertRule.model_id == model_id, AlertRule.name == payload.name)
        )
        if existing is not None:
            raise ResourceConflict(f"An alert rule named '{payload.name}' already exists.")

        rule = AlertRule(
            model_id=model_id,
            **payload.model_dump(exclude={"actor"}, mode="json"),
        )
        session.add(rule)
        session.flush()
        self._audit(
            session,
            model_id,
            "alert_rule.created",
            payload.actor,
            {
                "rule_id": rule.id,
                "rule_type": rule.rule_type,
                "metric": rule.metric,
                "severity": rule.severity,
            },
        )
        if rule.is_enabled:
            result = self.alert_evaluator.evaluate(
                session,
                model,
                snapshot=latest_snapshot(session, model_id),
                incident=self._open_incident(session, model_id),
                evaluated_at=datetime.now(UTC),
            )
            self._audit_alert_transitions(session, result)
        session.commit()
        return AlertRuleResponse.model_validate(rule)

    def get_alert_rule(self, session: Session, rule_id: str) -> AlertRuleResponse:
        return AlertRuleResponse.model_validate(self._require_alert_rule(session, rule_id))

    def list_alert_rules(self, session: Session, model_id: str) -> list[AlertRuleResponse]:
        self._require_model(session, model_id)
        records = session.scalars(
            select(AlertRule).where(AlertRule.model_id == model_id).order_by(AlertRule.name)
        ).all()
        return [AlertRuleResponse.model_validate(record) for record in records]

    def update_alert_rule(
        self,
        session: Session,
        rule_id: str,
        payload: AlertRuleUpdate,
    ) -> AlertRuleResponse:
        rule = self._require_alert_rule(session, rule_id)
        changes = payload.model_dump(exclude_unset=True, exclude={"actor"}, mode="json")
        if "name" in changes and changes["name"] != rule.name:
            duplicate = session.scalar(
                select(AlertRule).where(
                    AlertRule.model_id == rule.model_id,
                    AlertRule.name == changes["name"],
                    AlertRule.id != rule.id,
                )
            )
            if duplicate is not None:
                raise ResourceConflict(f"An alert rule named '{changes['name']}' already exists.")

        current = {field: getattr(rule, field) for field in AlertRuleDefinition.model_fields}
        validated = AlertRuleDefinition.model_validate({**current, **changes})
        normalized = validated.model_dump(mode="json")
        previous = {field: current[field] for field in changes}
        for field, value in normalized.items():
            setattr(rule, field, value)

        evaluated_at = datetime.now(UTC)
        result = AlertEvaluation(
            evaluated_at=evaluated_at,
            evaluated_rules=0,
            fired=[],
            resolved=[],
        )
        if not rule.is_enabled:
            resolved = self.alert_evaluator.resolve_rule_alerts(
                session,
                rule.id,
                evaluated_at=evaluated_at,
                reason="rule_disabled",
            )
            result = AlertEvaluation(
                evaluated_at=evaluated_at,
                evaluated_rules=0,
                fired=[],
                resolved=resolved,
            )
        else:
            result = self.alert_evaluator.evaluate(
                session,
                self._require_model(session, rule.model_id),
                snapshot=latest_snapshot(session, rule.model_id),
                incident=self._open_incident(session, rule.model_id),
                evaluated_at=evaluated_at,
            )
        self._audit_alert_transitions(session, result)
        session.flush()
        self._audit(
            session,
            rule.model_id,
            "alert_rule.updated",
            payload.actor,
            {
                "rule_id": rule.id,
                "before": previous,
                "after": {field: normalized[field] for field in changes},
                "fired_alert_ids": [alert.id for alert in result.fired],
                "resolved_alert_ids": [alert.id for alert in result.resolved],
            },
        )
        session.commit()
        return AlertRuleResponse.model_validate(rule)

    def delete_alert_rule(
        self,
        session: Session,
        rule_id: str,
        payload: ActorRequest,
    ) -> None:
        rule = self._require_alert_rule(session, rule_id)
        evaluated_at = datetime.now(UTC)
        resolved = self.alert_evaluator.resolve_rule_alerts(
            session,
            rule.id,
            evaluated_at=evaluated_at,
            reason="rule_deleted",
        )
        self._audit_alert_transitions(
            session,
            AlertEvaluation(
                evaluated_at=evaluated_at,
                evaluated_rules=0,
                fired=[],
                resolved=resolved,
            ),
        )
        self._audit(
            session,
            rule.model_id,
            "alert_rule.deleted",
            payload.actor,
            {
                "rule_id": rule.id,
                "name": rule.name,
                "resolved_alert_ids": [alert.id for alert in resolved],
            },
        )
        session.delete(rule)
        session.commit()

    def list_alerts(
        self,
        session: Session,
        model_id: str,
        *,
        state: AlertState | None = None,
        limit: int = 50,
    ) -> list[AlertResponse]:
        self._require_model(session, model_id)
        statement = select(Alert).where(Alert.model_id == model_id)
        if state is not None:
            statement = statement.where(Alert.state == state.value)
        records = session.scalars(statement.order_by(Alert.fired_at.desc()).limit(limit)).all()
        return [AlertResponse.model_validate(record) for record in records]

    def alert_feed(
        self,
        session: Session,
        *,
        state: AlertState | None = None,
        limit: int = 100,
    ) -> AlertFeedResponse:
        tenant_id = self._tenant_id(session)
        base = (
            select(Alert)
            .join(MonitoredModel, MonitoredModel.id == Alert.model_id)
            .where(MonitoredModel.tenant_id == tenant_id)
        )
        if state is not None:
            base = base.where(Alert.state == state.value)
        records = list(session.scalars(base.order_by(Alert.fired_at.desc()).limit(limit)).all())
        count_base = (
            select(func.count())
            .select_from(Alert)
            .join(MonitoredModel, MonitoredModel.id == Alert.model_id)
            .where(MonitoredModel.tenant_id == tenant_id)
        )
        if state is not None:
            count_base = count_base.where(Alert.state == state.value)
        total = int(session.scalar(count_base) or 0)
        raw_counts = dict(
            session.execute(
                select(Alert.state, func.count())
                .join(MonitoredModel, MonitoredModel.id == Alert.model_id)
                .where(MonitoredModel.tenant_id == tenant_id)
                .group_by(Alert.state)
            ).all()
        )
        counts = {AlertState(state): count for state, count in raw_counts.items()}
        return AlertFeedResponse(
            items=[AlertResponse.model_validate(record) for record in records],
            total=total,
            firing=int(counts.get(AlertState.FIRING, 0)),
            acknowledged=int(counts.get(AlertState.ACKNOWLEDGED, 0)),
        )

    def get_alert(self, session: Session, alert_id: str) -> AlertResponse:
        return AlertResponse.model_validate(self._require_alert(session, alert_id))

    def acknowledge_alert(
        self, session: Session, alert_id: str, payload: ActorRequest
    ) -> AlertResponse:
        alert = self._require_alert(session, alert_id)
        if AlertState(alert.state) is AlertState.RESOLVED:
            raise InvalidTransition("A resolved alert cannot be acknowledged.")
        if AlertState(alert.state) is AlertState.FIRING:
            alert.state = AlertState.ACKNOWLEDGED.value
            alert.acknowledged_at = datetime.now(UTC)
            alert.acknowledged_by = payload.actor
            self._audit(
                session,
                alert.model_id,
                "alert.acknowledged",
                payload.actor,
                {"alert_id": alert.id},
            )
            session.commit()
        return AlertResponse.model_validate(alert)

    def resolve_alert(
        self,
        session: Session,
        alert_id: str,
        payload: AlertResolveRequest,
    ) -> AlertResponse:
        alert = self._require_alert(session, alert_id)
        if AlertState(alert.state) is not AlertState.RESOLVED:
            alert.state = AlertState.RESOLVED.value
            alert.resolved_at = datetime.now(UTC)
            alert.resolution_reason = payload.reason
            self._audit(
                session,
                alert.model_id,
                "alert.resolved",
                payload.actor,
                {
                    "alert_id": alert.id,
                    "rule_id": alert.rule_id,
                    "summary": payload.reason,
                },
            )
            session.commit()
        return AlertResponse.model_validate(alert)

    def evaluate_alerts(
        self,
        session: Session,
        model_id: str,
        payload: AlertEvaluationRequest,
    ) -> AlertEvaluationResponse:
        model = self._require_model(session, model_id)
        snapshot = latest_snapshot(session, model_id)
        result = self.alert_evaluator.evaluate(
            session,
            model,
            snapshot=snapshot,
            incident=self._open_incident(session, model_id),
            evaluated_at=payload.evaluated_at,
        )
        self._audit_alert_transitions(session, result, actor=payload.actor)
        session.commit()
        return self._alert_evaluation_response(model_id, result)

    def _evaluate_alert_rules(
        self,
        session: Session,
        snapshot: HealthSnapshot,
        incident: Incident | None,
    ) -> AlertEvaluation:
        model = self._require_model(session, snapshot.model_id)
        result = self.alert_evaluator.evaluate(
            session,
            model,
            snapshot=snapshot,
            incident=incident,
            evaluated_at=snapshot.observed_at,
        )
        self._audit_alert_transitions(session, result)
        return result

    def _audit_alert_transitions(
        self,
        session: Session,
        result: AlertEvaluation,
        *,
        actor: str = "alerting-engine",
    ) -> None:
        for alert in result.fired:
            self._audit(
                session,
                alert.model_id,
                "alert.fired",
                actor,
                {
                    "alert_id": alert.id,
                    "rule_id": alert.rule_id,
                    "incident_id": alert.incident_id,
                    "value": alert.observed_value,
                    "severity": alert.severity,
                },
            )
        for alert in result.resolved:
            self._audit(
                session,
                alert.model_id,
                "alert.resolved",
                actor,
                {
                    "alert_id": alert.id,
                    "rule_id": alert.rule_id,
                    "value": alert.observed_value,
                    "summary": alert.resolution_reason,
                },
            )

    @staticmethod
    def _alert_evaluation_response(
        model_id: str,
        result: AlertEvaluation,
    ) -> AlertEvaluationResponse:
        return AlertEvaluationResponse(
            model_id=model_id,
            evaluated_at=result.evaluated_at,
            evaluated_rules=result.evaluated_rules,
            fired=[AlertResponse.model_validate(alert) for alert in result.fired],
            resolved=[AlertResponse.model_validate(alert) for alert in result.resolved],
        )

    # ---------------------------------------------------------------- #
    # Model versions and the signature stability evaluations
    # ---------------------------------------------------------------- #

    def _ensure_evaluator_version(
        self, session: Session, kind: EvaluatorKind
    ) -> EvaluatorVersion:
        """Pin the evaluator that produced a judgement, so it can be replayed."""

        record = session.scalar(
            select(EvaluatorVersion).where(
                EvaluatorVersion.name == self.evaluator.name,
                EvaluatorVersion.version == self.evaluator.version,
                EvaluatorVersion.kind == kind.value,
            )
        )
        if record is None:
            record = EvaluatorVersion(
                name=self.evaluator.name,
                version=self.evaluator.version,
                kind=kind.value,
                provider=self.evaluator.provider,
                config={"simulation": self.evaluator.simulation},
            )
            session.add(record)
            session.flush()
        return record

    # Agreement thresholds for a stability verdict. Published rather than
    # buried so a "critical" reading can be argued with.
    _STABLE_AT = 90.0
    _DRIFTING_AT = 70.0

    @classmethod
    def _verdict(cls, score: float | None) -> StabilityVerdict:
        if score is None:
            return StabilityVerdict.INCONCLUSIVE
        if score >= cls._STABLE_AT:
            return StabilityVerdict.STABLE
        if score >= cls._DRIFTING_AT:
            return StabilityVerdict.DRIFTING
        return StabilityVerdict.CRITICAL

    def run_semantic_stability(
        self,
        session: Session,
        model_id: str,
        payload: StabilityRunRequest,
    ) -> StabilityTestResponse:
        """Ask the same question several ways and see whether the facts agree.

        Agreement is judged on extracted claims rather than wording, so a
        differently phrased answer asserting the same deadline counts as stable.
        The first variant is the baseline the others are compared against.
        """

        self._require_model(session, model_id)
        version = self._active_model_version(session, model_id)
        evaluator = self._ensure_evaluator_version(session, EvaluatorKind.SEMANTIC_STABILITY)
        corpus_version = version.corpus_version if version else None

        test = StabilityTest(
            model_id=model_id,
            model_version_id=version.id if version else None,
            evaluator_version_id=evaluator.id,
            kind=StabilityKind.SEMANTIC.value,
            question_redacted=redact(payload.question) or "",
            question_hash=content_hash(payload.question) or "",
            run_at=datetime.now(UTC),
        )
        session.add(test)
        session.flush()

        prompts = self.evaluator.paraphrase(payload.question, payload.variants)
        answers = [
            self.evaluator.answer(
                question=payload.question, corpus_version=corpus_version, variant_index=index
            )
            for index in range(len(prompts))
        ]
        self._store_variants(session, test, prompts, answers)

        baseline_claims = answers[0].claims if answers else {}
        agreements = self._compare_claims(session, test, answers, baseline_claims)
        score = round(100.0 * sum(agreements) / len(agreements), 1) if agreements else None

        test.stability_score = score
        test.evaluator_confidence = 0.8 if len(answers) >= 3 else 0.5
        test.verdict = self._verdict(score).value
        session.flush()
        self._audit(
            session,
            model_id,
            "stability.semantic_evaluated",
            "evaluation-engine",
            {"test_id": test.id, "score": score, "verdict": test.verdict},
        )
        session.commit()
        return self._stability_response(test)

    def run_temporal_stability(
        self,
        session: Session,
        model_id: str,
        payload: StabilityRunRequest,
    ) -> StabilityTestResponse:
        """Re-ask a controlled question and compare it with the previous run.

        A changed answer only means drift when the inputs held constant. If the
        fingerprint moved, the difference is attributed to the changed input and
        the verdict is inconclusive -- reporting it as drift would be exactly
        the mistake the product is meant to avoid.
        """

        self._require_model(session, model_id)
        version = self._active_model_version(session, model_id)
        evaluator = self._ensure_evaluator_version(session, EvaluatorKind.TEMPORAL_STABILITY)
        question_hash = content_hash(payload.question) or ""

        previous = session.scalar(
            select(StabilityTest)
            .where(
                StabilityTest.model_id == model_id,
                StabilityTest.kind == StabilityKind.TEMPORAL.value,
                StabilityTest.question_hash == question_hash,
            )
            .order_by(StabilityTest.run_at.desc())
            .limit(1)
        )
        baseline_version = (
            session.get(ModelVersion, previous.model_version_id)
            if previous and previous.model_version_id
            else None
        )

        test = StabilityTest(
            model_id=model_id,
            model_version_id=version.id if version else None,
            baseline_version_id=baseline_version.id if baseline_version else None,
            evaluator_version_id=evaluator.id,
            kind=StabilityKind.TEMPORAL.value,
            question_redacted=redact(payload.question) or "",
            question_hash=question_hash,
            run_at=datetime.now(UTC),
        )
        session.add(test)
        session.flush()

        answer = self.evaluator.answer(
            question=payload.question,
            corpus_version=version.corpus_version if version else None,
        )
        self._store_variants(session, test, [payload.question], [answer])

        if previous is None:
            test.verdict = StabilityVerdict.INCONCLUSIVE.value
            test.evaluator_confidence = 0.3
            note = "no_baseline"
        elif baseline_version is not None and version is not None and not version.comparable_with(
            baseline_version
        ):
            # Attribute the change rather than calling it drift.
            test.inputs_changed = True
            test.changed_inputs = baseline_version.differences(version)
            test.verdict = StabilityVerdict.INCONCLUSIVE.value
            test.evaluator_confidence = 0.9
            note = "inputs_changed"
        else:
            baseline_claims = {
                claim.claim_key: claim.value_text or ""
                for claim in session.scalars(
                    select(StabilityClaim).where(StabilityClaim.test_id == previous.id)
                ).all()
            }
            agreements = self._compare_claims(session, test, [answer], baseline_claims)
            score = round(100.0 * sum(agreements) / len(agreements), 1) if agreements else None
            test.stability_score = score
            test.verdict = self._verdict(score).value
            test.evaluator_confidence = 0.75
            note = "compared"

        session.flush()
        self._audit(
            session,
            model_id,
            "stability.temporal_evaluated",
            "evaluation-engine",
            {
                "test_id": test.id,
                "verdict": test.verdict,
                "inputs_changed": test.inputs_changed,
                "note": note,
            },
        )
        session.commit()
        return self._stability_response(test)

    @staticmethod
    def _store_variants(
        session: Session,
        test: StabilityTest,
        prompts: list[str],
        answers: list[object],
    ) -> None:
        for index, (prompt, answer) in enumerate(zip(prompts, answers, strict=False)):
            session.add(
                StabilityVariant(
                    test_id=test.id,
                    variant_index=index,
                    prompt_redacted=redact(prompt) or "",
                    answer_redacted=redact(answer.text),
                    is_baseline=index == 0,
                )
            )
        session.flush()

    def _compare_claims(
        self,
        session: Session,
        test: StabilityTest,
        answers: list[object],
        baseline_claims: dict[str, str],
    ) -> list[bool]:
        """Persist each asserted fact and whether it matched the baseline."""

        variants = {
            variant.variant_index: variant
            for variant in session.scalars(
                select(StabilityVariant).where(StabilityVariant.test_id == test.id)
            ).all()
        }
        agreements: list[bool] = []

        for index, answer in enumerate(answers):
            variant = variants.get(index)
            if variant is None:
                continue
            for key, value in answer.claims.items():
                expected = baseline_claims.get(key)
                agrees = expected is None or expected == value
                if index > 0 or not baseline_claims:
                    agreements.append(agrees)
                session.add(
                    StabilityClaim(
                        test_id=test.id,
                        variant_id=variant.id,
                        claim_key=key,
                        claim_text_redacted=redact(answer.text) or "",
                        value_text=value,
                        agrees_with_baseline=agrees,
                        disagreement_note=(
                            None if agrees else f"baseline said {expected!r}, this said {value!r}"
                        ),
                    )
                )
        session.flush()
        return agreements

    def list_stability_tests(
        self,
        session: Session,
        model_id: str,
        *,
        kind: StabilityKind | None = None,
        limit: int = 20,
    ) -> list[StabilityTestResponse]:
        self._require_model(session, model_id)
        statement = select(StabilityTest).where(StabilityTest.model_id == model_id)
        if kind is not None:
            statement = statement.where(StabilityTest.kind == kind.value)
        records = session.scalars(
            statement.order_by(StabilityTest.run_at.desc()).limit(limit)
        ).all()
        return [self._stability_response(record) for record in records]

    @staticmethod
    def _stability_response(record: StabilityTest) -> StabilityTestResponse:
        return StabilityTestResponse.model_validate(record)

    def audit_events(self, session: Session, model_id: str) -> list[AuditEventResponse]:
        self._require_model(session, model_id)
        records = session.scalars(
            select(AuditEvent)
            .where(AuditEvent.model_id == model_id)
            .order_by(AuditEvent.created_at)
        ).all()
        return [self._audit_response(record) for record in records]

    def reset_demo(self, session: Session) -> DemoResetResponse:
        if self.settings.environment.strip().lower() in {"production", "prod"}:
            raise AuthorizationDenied("Demo reset is disabled in production environments.")

        existing_ids = list(
            session.scalars(
                select(MonitoredModel.id).where(
                    MonitoredModel.name.in_(["CampusGPT", "ShopAssist"])
                )
            ).all()
        )
        if existing_ids:
            session.execute(delete(MonitoredModel).where(MonitoredModel.id.in_(existing_ids)))
            session.commit()

        model = MonitoredModel(
            name="ShopAssist",
            provider="demo-adapter",
            environment="simulation",
            description=(
                "Retail support assistant answering returns and refund policy questions."
            ),
        )
        session.add(model)
        session.flush()
        now = datetime.now(UTC)
        self._create_model_version(
            session,
            model,
            ModelVersionCreate(
                label="shopassist-demo-v1",
                model_identifier="shopassist-retail-assistant",
                prompt_version="returns-support-v3",
                configuration={"temperature": 0.2, "citation_required": False},
                tools=["catalog-search", "returns-policy-retriever"],
                corpus_version="returns-policy-2026-06-01",
                evaluation_policy_version="shopassist-returns-v1",
                actor="demo-seeder",
            ),
        )
        retired_document = self._seed_knowledge_corpus(session, model.id, now)
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
        for index, (observed_at, dimensions) in enumerate(demo_points):
            self._record_telemetry(
                session,
                model.id,
                TelemetryCreate(
                    observed_at=observed_at,
                    dimensions=dimensions,
                    sample_size=100,
                    coverage=0.95,
                    source=SignalSource.SIMULATED,
                    traces=self._demo_traces(
                        observed_at, index, retired_document.external_ref
                    ),
                ),
            )
        self._audit(
            session,
            model.id,
            "demo.reset",
            "demo-seeder",
            {
                "scenario": "shopassist_return_policy_freshness_failure",
                "snapshots": len(demo_points),
                "retired_policy": retired_document.external_ref,
                "minimum_sample_size": self.settings.minimum_sample_size,
            },
        )
        session.commit()

        diagnosis = self.diagnose_latest(session, model.id)
        incident = self._open_incident(session, model.id)
        return DemoResetResponse(
            model=self._model_response(model),
            health=self.health_timeline(session, model.id),
            diagnosis=diagnosis,
            recovery=self.latest_recovery(session, model.id),
            incident=IncidentResponse.model_validate(incident) if incident else None,
        )

    def purge_expired_traces(self, session: Session, model_id: str) -> int:
        """Delete traces past the model's retention window.

        Retention was configurable but never applied: every model carried a
        `retention_days` nothing honoured, on the table that grows fastest and
        holds redacted user traffic.

        Deleting user data is audited. A purge that removes nothing writes no
        event, so the trail records deletions rather than the fact that a worker
        ran.
        """

        model = self._require_model(session, model_id)
        removed = purge_expired_traces(session, model)
        if removed:
            self._audit(
                session,
                model_id,
                "retention.purged",
                "retention-worker",
                {"removed_traces": removed, "retention_days": model.retention_days},
            )
        session.commit()
        return removed

    def _refresh_knowledge_sources(self, session: Session, model_id: str) -> int:
        """Re-index a model's retrieval sources, and record the input change.

        The failure being repaired is that the superseding document was never
        indexed, so the retriever kept returning the older one. Stamping
        ``indexed_at`` on the newest document is therefore the actual fix; the
        source's status and version follow from it.

        ``is_stale`` on the superseded document is deliberately left alone. That
        document really was superseded -- a historical fact about it, not a
        symptom to be cleared.

        Returns the number of sources refreshed.
        """

        sources = session.scalars(
            select(KnowledgeSource).where(KnowledgeSource.model_id == model_id)
        ).all()
        if not sources:
            return 0

        now = datetime.now(UTC)
        refreshed = 0
        for source in sources:
            newest = session.scalar(
                select(KnowledgeDocument)
                .where(
                    KnowledgeDocument.source_id == source.id,
                    KnowledgeDocument.is_stale.is_(False),
                )
                .order_by(KnowledgeDocument.published_at.desc())
                .limit(1)
            )
            previous_version = source.corpus_version
            if newest is not None:
                newest.indexed_at = now
                source.corpus_version = self._corpus_version_for(newest, previous_version)
                source.status = KnowledgeStatus.FRESH.value
                version_id = self._register_corpus_version(
                    session, model_id, source.corpus_version
                )
            else:
                # A source containing only superseded policy must not be made
                # healthy by a refresh. Remove it from serving instead.
                source.status = KnowledgeStatus.DISABLED.value
                version_id = None
            source.last_refreshed_at = now
            refreshed += 1

            self._audit(
                session,
                model_id,
                "knowledge.refreshed",
                "recovery-adapter",
                {
                    "source_id": source.id,
                    "previous_corpus_version": previous_version,
                    "corpus_version": source.corpus_version,
                    "indexed_document_id": newest.id if newest else None,
                    "model_version_id": version_id,
                },
            )

        session.flush()
        return refreshed

    @staticmethod
    def _corpus_version_for(document: KnowledgeDocument, fallback: str) -> str:
        """Derive the corpus version now being served from the indexed document."""

        if document.published_at is not None:
            return document.published_at.date().isoformat()
        return fallback

    def _register_corpus_version(
        self,
        session: Session,
        model_id: str,
        corpus_version: str,
    ) -> str | None:
        """Record that a controlled input moved when the corpus was re-indexed.

        Without this the active version keeps advertising the old corpus, and a
        later temporal comparison would believe the inputs held constant while
        the retrieval corpus underneath it had changed -- reporting model drift
        for a change the system itself made. Registering the new version is what
        lets that comparison correctly report an attributed input change.

        Returns the new version id, or None when the model has no active version
        to derive one from.
        """

        active = self._active_model_version(session, model_id)
        if active is None or active.corpus_version == corpus_version:
            return None

        payload = ModelVersionCreate(
            label=f"{active.label}+corpus-{corpus_version}",
            model_identifier=active.model_identifier,
            prompt_version=active.prompt_version,
            corpus_version=corpus_version,
            evaluation_policy_version=active.evaluation_policy_version,
            actor="recovery-adapter",
        )
        model = session.get(MonitoredModel, model_id)
        version = self._create_model_version(session, model, payload)
        return version.id

    def _seed_knowledge_corpus(
        self,
        session: Session,
        model_id: str,
        now: datetime,
    ) -> KnowledgeDocument:
        """Seed the current and retired policy sources behind ShopAssist's failure.

        A new returns policy was published, but the retriever kept serving the
        retired one. Modelling both documents and the link between them is
        what turns "the retriever served stale documents" into something a user
        can verify rather than a claim they have to accept.

        Returns the stale document, which the seeded traces cite.
        """

        current_source = KnowledgeSource(
            model_id=model_id,
            name="ShopAssist Returns Policy — Current",
            kind="corpus",
            corpus_version="returns-policy-2026-09-01",
            status=KnowledgeStatus.FRESH,
            document_count=1,
            last_refreshed_at=None,
        )
        retired_source = KnowledgeSource(
            model_id=model_id,
            name="ShopAssist Returns Policy — Retired",
            kind="corpus",
            corpus_version="returns-policy-2026-06-01",
            status=KnowledgeStatus.STALE,
            document_count=1,
            last_refreshed_at=now - timedelta(days=45),
        )
        session.add_all([current_source, retired_source])
        session.flush()

        current = KnowledgeDocument(
            source_id=current_source.id,
            external_ref="policy/returns-2026-09-current",
            title="ShopAssist Returns Policy (current: 30-day window)",
            content_hash=content_hash("returns accepted within 30 days of delivery") or "",
            published_at=datetime(2026, 9, 1, tzinfo=UTC),
            indexed_at=None,
            is_stale=False,
        )
        session.add(current)
        session.flush()

        stale = KnowledgeDocument(
            source_id=retired_source.id,
            external_ref="policy/returns-2026-06-retired",
            title="ShopAssist Returns Policy (retired: 14-day window)",
            content_hash=content_hash("returns accepted within 14 days of delivery") or "",
            published_at=datetime(2026, 6, 1, tzinfo=UTC),
            indexed_at=now - timedelta(days=45),
            is_stale=True,
            superseded_by_id=current.id,
        )
        session.add(stale)
        session.flush()
        return stale

    @staticmethod
    def _demo_traces(observed_at: datetime, step: int, stale_ref: str) -> list[TraceCreate]:
        """Build the requests underlying one demo window.

        Deterministic by construction -- no random source -- because the README
        requires the scenario to behave identically every time it is presented.
        Groundedness falls and unsupported claims rise with each step, so the
        traces tell the same story the aggregate scores do.
        """

        groundedness = (92.0, 81.0, 55.0, 30.0)[step]
        quality = (90.0, 87.0, 74.0, 61.0)[step]
        # By the final window most answers assert a deadline nothing supports.
        unsupported = (0, 1, 2, 3)[step]

        questions = (
            "How long do I have to return an item?",
            "Can I return this order after 14 days?",
            "What is the current returns window?",
            "Was the returns policy extended? Reply to me at shopper@example.com",
        )

        traces: list[TraceCreate] = []
        for offset, question in enumerate(questions):
            cites_stale = step >= 1
            traces.append(
                TraceCreate(
                    occurred_at=observed_at - timedelta(seconds=90 - offset * 20),
                    request_id=f"shopassist-{step}-{offset}",
                    question=question,
                    answer=(
                        "Items may be returned within 14 days from delivery."
                        if cites_stale
                        else "Items may be returned within 30 days from delivery."
                    ),
                    provider="demo-adapter",
                    latency_ms=310 + offset * 5 + step * 12,
                    input_tokens=48 + offset,
                    output_tokens=64 + offset,
                    cost_usd=0.0009,
                    retrieved_document_ids=[stale_ref] if cites_stale else [],
                    citation_count=0 if step == 3 else 1,
                    unsupported_claim_count=unsupported,
                    groundedness_score=max(0.0, groundedness - offset * 1.5),
                    quality_score=max(0.0, quality - offset * 1.0),
                    is_simulated=True,
                )
            )
        return traces

    # A degradation is one story: the snapshot that opened it, the diagnosis
    # that explained it, the recovery that addressed it, and the verification
    # that closed it. The incident is what holds those together.
    _OPEN_STATES = frozenset(
        {
            IncidentState.OPEN,
            IncidentState.DIAGNOSING,
            IncidentState.MITIGATING,
            IncidentState.VERIFYING,
        }
    )
    _SEVERITY_BY_HEALTH = {
        HealthState.WARNING: Severity.MEDIUM,
        HealthState.CRITICAL: Severity.HIGH,
    }

    @classmethod
    def _open_incident(cls, session: Session, model_id: str) -> Incident | None:
        """Return the model's unresolved incident, if it has one."""

        return session.scalar(
            select(Incident)
            .where(
                Incident.model_id == model_id,
                Incident.state.in_([state.value for state in cls._OPEN_STATES]),
            )
            .order_by(Incident.opened_at.desc())
            .limit(1)
        )

    def _sync_incident(
        self,
        session: Session,
        model_id: str,
        snapshot: HealthSnapshot,
        *,
        allow_verifying_resolution: bool = False,
    ) -> Incident | None:
        """Open, deepen or resolve the incident this snapshot implies.

        A degrading snapshot opens an incident if none is already running, and
        otherwise deepens the existing one -- severity only escalates, and the
        trough records the worst the model actually got, not merely the latest
        reading. A healthy snapshot closes an incident that was being verified;
        one that is merely open is left alone, since a single good window is not
        yet a recovery.
        """

        state = HealthState(snapshot.state)
        incident = self._open_incident(session, model_id)

        if state in self._SEVERITY_BY_HEALTH:
            severity = self._SEVERITY_BY_HEALTH[state]
            if incident is None:
                incident = Incident(
                    model_id=model_id,
                    title=f"Health degraded to {state.value}",
                    state=IncidentState.OPEN.value,
                    severity=severity.value,
                    opened_at=snapshot.observed_at,
                    opening_snapshot_id=snapshot.id,
                    baseline_score=self._last_healthy_score(session, model_id, snapshot),
                    trough_score=snapshot.score,
                )
                session.add(incident)
                session.flush()
                self._audit(
                    session,
                    model_id,
                    "incident.opened",
                    "pulse-engine",
                    {
                        "incident_id": incident.id,
                        "severity": incident.severity,
                        "score": snapshot.score,
                    },
                )
                return incident

            if Severity(incident.severity) is Severity.MEDIUM and severity is Severity.HIGH:
                incident.severity = severity.value
            if snapshot.score is not None and (
                incident.trough_score is None or snapshot.score < incident.trough_score
            ):
                incident.trough_score = snapshot.score
            session.flush()
            return incident

        if (
            allow_verifying_resolution
            and incident is not None
            and IncidentState(incident.state) is IncidentState.VERIFYING
        ):
            self._close_incident(session, incident, snapshot, resolved=True)
        return incident

    @staticmethod
    def _last_healthy_score(
        session: Session,
        model_id: str,
        before: HealthSnapshot,
    ) -> float | None:
        """The score this model was holding before it started to fall."""

        return session.scalar(
            select(HealthSnapshot.score)
            .where(
                HealthSnapshot.model_id == model_id,
                HealthSnapshot.observed_at < before.observed_at,
                HealthSnapshot.score.is_not(None),
                HealthSnapshot.state == HealthState.HEALTHY.value,
            )
            .order_by(HealthSnapshot.observed_at.desc())
            .limit(1)
        )

    def _advance_incident(
        self,
        session: Session,
        incident: Incident | None,
        state: IncidentState,
    ) -> None:
        """Move an incident forward, never backwards, and never once closed."""

        if incident is None or IncidentState(incident.state) not in self._OPEN_STATES:
            return
        incident.state = state.value
        session.flush()

    def _close_incident(
        self,
        session: Session,
        incident: Incident,
        snapshot: HealthSnapshot,
        *,
        resolved: bool,
    ) -> None:
        incident.state = (IncidentState.RESOLVED if resolved else IncidentState.FAILED).value
        incident.closed_at = datetime.now(UTC)
        incident.closing_snapshot_id = snapshot.id
        incident.summary = (
            f"Recovered to {snapshot.score} from a trough of {incident.trough_score}."
            if resolved
            else f"Recovery did not restore health; last score {snapshot.score}."
        )
        session.flush()
        self._audit(
            session,
            incident.model_id,
            "incident.resolved" if resolved else "incident.failed",
            "verification-engine",
            {
                "incident_id": incident.id,
                "score": snapshot.score,
                "trough_score": incident.trough_score,
            },
        )

    def list_incidents(
        self,
        session: Session,
        model_id: str,
        *,
        limit: int = 20,
    ) -> list[IncidentResponse]:
        """Recent incidents for a model, most recently opened first."""

        self._require_model(session, model_id)
        records = session.scalars(
            select(Incident)
            .where(Incident.model_id == model_id)
            .order_by(Incident.opened_at.desc())
            .limit(limit)
        ).all()
        return [IncidentResponse.model_validate(record) for record in records]

    def get_incident(self, session: Session, incident_id: str) -> IncidentResponse:
        record = session.get(Incident, incident_id)
        if record is None:
            raise ResourceNotFound("Incident not found.")
        return IncidentResponse.model_validate(record)

    def _record_evidence(
        self,
        session: Session,
        diagnosis: Diagnosis,
        snapshot: HealthSnapshot,
        items: list[EvidenceItem],
    ) -> None:
        """Store each observation as a row, linked to the requests behind it.

        The JSON column on the diagnosis stays populated for existing readers,
        but these rows are canonical: they are queryable and they carry the
        drill-down to individual traces. Contradicting evidence is stored the
        same way as supporting evidence, because it is meant to be shown rather
        than filtered out.
        """

        for item in items:
            evidence = DiagnosisEvidence(
                diagnosis_id=diagnosis.id,
                reason_code=item.reason_code,
                metric=item.metric,
                summary=item.summary,
                baseline_value=item.baseline_value,
                current_value=item.current_value,
                change=item.change,
                supports_diagnosis=item.supports_diagnosis,
            )
            evidence.traces = traces_for_metric(
                session,
                snapshot.model_id,
                metric=item.metric,
                start=snapshot.window_start,
                end=snapshot.window_end,
            )
            session.add(evidence)
        session.flush()

    def _record_telemetry(
        self,
        session: Session,
        model_id: str,
        payload: TelemetryCreate,
        *,
        allow_verifying_resolution: bool = False,
    ) -> HealthSnapshot:
        traces = self._record_traces(session, model_id, payload.traces)
        window_start, window_end = self._evaluation_window(payload, traces)
        dimensions = self._infer_missing_dimensions(
            session, model_id, payload.dimensions, traces, window_start, window_end
        )
        score = calculate_health(
            dimensions,
            sample_size=payload.sample_size,
            coverage=payload.coverage,
            minimum_sample_size=self.settings.minimum_sample_size,
            minimum_coverage=self.settings.minimum_coverage,
        )
        policy = ensure_health_policy(
            session,
            version=score.policy_version,
            weights=DIMENSION_WEIGHTS,
            thresholds=HEALTH_THRESHOLDS,
            minimum_sample_size=self.settings.minimum_sample_size,
            minimum_coverage=self.settings.minimum_coverage,
        )

        record = HealthSnapshot(
            model_id=model_id,
            event_id=payload.event_id,
            schema_version=payload.schema_version,
            observed_at=payload.observed_at,
            window_start=window_start,
            window_end=window_end,
            **dimensions.model_dump(),
            score=score.score,
            state=score.state.value,
            confidence=score.confidence,
            sample_size=payload.sample_size,
            trace_count=len(traces),
            coverage=payload.coverage,
            policy_version=score.policy_version,
            policy_id=policy.id,
            source=payload.source.value,
            missing_dimensions=score.missing_dimensions,
        )
        session.add(record)
        session.flush()
        self._settle_forecasts(session, record)
        self._store_forecast(session, record)
        incident = self._sync_incident(
            session,
            model_id,
            record,
            allow_verifying_resolution=allow_verifying_resolution,
        )
        self._evaluate_alert_rules(session, record, incident)
        self._queue_recovery_verification(session, record)
        return record

    def _infer_missing_dimensions(
        self,
        session: Session,
        model_id: str,
        dimensions: DimensionScores,
        traces: list[Trace],
        window_start: datetime,
        window_end: datetime,
    ) -> DimensionScores:
        """Fill groundedness and drift from trace evidence when not supplied.

        A caller that already scored these dimensions upstream is trusted as
        -is; this only covers the gap for traces that ship raw counts (citation
        counts, retrieved document ids) and expect DriftZero to turn them into
        a dimension score, rather than treating a missing field as healthy.
        """

        updates: dict[str, float] = {}

        if dimensions.groundedness is None:
            inferred_groundedness = score_groundedness(traces)
            if inferred_groundedness is not None:
                updates["groundedness"] = inferred_groundedness

        if dimensions.drift is None:
            baseline = baseline_traces_before(
                session,
                model_id,
                before=window_start,
                span=window_end - window_start,
            )
            inferred_drift = score_drift(traces, baseline)
            if inferred_drift is not None:
                updates["drift"] = inferred_drift

        if not updates:
            return dimensions
        return dimensions.model_copy(update=updates)

    def _queue_recovery_verification(
        self,
        session: Session,
        snapshot: HealthSnapshot,
    ) -> None:
        """Queue real post-action evidence once its sample gates are satisfied."""

        if SignalSource(snapshot.source) is SignalSource.SIMULATED:
            return
        if (
            snapshot.sample_size < self.settings.recovery_verification_requests
            or snapshot.coverage < self.settings.recovery_verification_coverage
        ):
            return
        plan = session.scalar(
            select(RecoveryPlan)
            .where(
                RecoveryPlan.model_id == snapshot.model_id,
                RecoveryPlan.state == RecoveryState.VERIFYING.value,
            )
            .order_by(RecoveryPlan.executed_at.desc())
            .limit(1)
        )
        if plan is None or (plan.executed_at and snapshot.observed_at <= plan.executed_at):
            return
        idempotency_key = f"verify:{plan.id}:{snapshot.id}"
        existing = session.scalar(
            select(RecoveryCommand.id).where(
                RecoveryCommand.idempotency_key == idempotency_key
            )
        )
        if existing is not None:
            return
        command = self._new_verification_command(
            plan,
            snapshot,
            actor="verification-engine",
            role=ActorRole.SERVICE,
            idempotency_key=idempotency_key,
            reason="Post-recovery telemetry met verification evidence gates.",
        )
        session.add(command)
        session.flush()
        self._audit(
            session,
            plan.model_id,
            "recovery.verification_queued",
            "verification-engine",
            {"plan_id": plan.id, "command_id": command.id, "snapshot_id": snapshot.id},
        )

    def _store_forecast(
        self,
        session: Session,
        snapshot: HealthSnapshot,
    ) -> HealthForecastRecord | None:
        """Persist the trajectory predicted from this snapshot.

        Written when the snapshot is recorded rather than when a timeline is
        read, so a prediction is a fact about a moment rather than a side effect
        of someone opening a page.
        """

        horizon = self.settings.forecast_horizon_minutes
        forecast = forecast_health(
            snapshot_timeline(session, snapshot.model_id),
            horizon_minutes=horizon,
        )
        if forecast is None:
            return None

        record = HealthForecastRecord(
            model_id=snapshot.model_id,
            snapshot_id=snapshot.id,
            horizon_minutes=forecast.horizon_minutes,
            predicted_score=forecast.predicted_score,
            lower_bound=forecast.lower_bound,
            upper_bound=forecast.upper_bound,
            change_per_hour=forecast.change_per_hour,
            direction=forecast.direction,
            method=forecast.method,
            target_at=snapshot.observed_at + timedelta(minutes=horizon),
        )
        session.add(record)
        session.flush()
        return record

    @staticmethod
    def _settle_forecasts(session: Session, snapshot: HealthSnapshot) -> None:
        """Record what actually happened for predictions whose horizon has passed.

        Only scored snapshots can settle a forecast: an insufficient-data window
        is not evidence that a prediction was wrong.
        """

        if snapshot.score is None:
            return
        pending = session.scalars(
            select(HealthForecastRecord).where(
                HealthForecastRecord.model_id == snapshot.model_id,
                HealthForecastRecord.actual_score.is_(None),
                HealthForecastRecord.target_at.is_not(None),
                HealthForecastRecord.target_at <= snapshot.observed_at,
            )
        ).all()
        for record in pending:
            record.actual_score = snapshot.score
        if pending:
            session.flush()

    def list_forecasts(
        self,
        session: Session,
        model_id: str,
        *,
        limit: int = 50,
    ) -> list[HealthForecastRecordResponse]:
        """Stored predictions for a model, most recent first."""

        self._require_model(session, model_id)
        records = session.scalars(
            select(HealthForecastRecord)
            .where(HealthForecastRecord.model_id == model_id)
            .order_by(HealthForecastRecord.created_at.desc())
            .limit(limit)
        ).all()
        return [HealthForecastRecordResponse.model_validate(record) for record in records]

    def _record_traces(
        self,
        session: Session,
        model_id: str,
        payloads: list[TraceCreate],
    ) -> list[Trace]:
        """Persist request-level traces, redacting text on the way in.

        Only the redacted rendering is stored; the hash is taken over the
        original so repeated questions stay correlatable without retaining what
        was asked.
        """

        traces: list[Trace] = []
        for item in payloads:
            trace = Trace(
                model_id=model_id,
                tenant_id=self._tenant_id(session),
                occurred_at=item.occurred_at,
                request_id=item.request_id,
                question_redacted=redact(item.question),
                answer_redacted=redact(item.answer),
                prompt_hash=content_hash(item.question),
                answer_hash=content_hash(item.answer),
                redaction_policy_version=REDACTION_POLICY_VERSION,
                provider=item.provider,
                status=item.status.value,
                error_code=item.error_code,
                latency_ms=item.latency_ms,
                input_tokens=item.input_tokens,
                output_tokens=item.output_tokens,
                cost_usd=item.cost_usd,
                retrieved_document_ids=list(item.retrieved_document_ids),
                citation_count=item.citation_count,
                unsupported_claim_count=item.unsupported_claim_count,
                groundedness_score=item.groundedness_score,
                quality_score=item.quality_score,
                safety_flags=list(item.safety_flags),
                is_simulated=item.is_simulated,
            )
            session.add(trace)
            traces.append(trace)

        if traces:
            session.flush()
        return traces

    def _evaluation_window(
        self,
        payload: TelemetryCreate,
        traces: list[Trace],
    ) -> tuple[datetime, datetime]:
        """Return the period a score covers.

        Every score has to state its window. When traces are supplied the window
        is exactly the traffic they span; otherwise it falls back to the
        configured horizon ending at the observation, so the window is never
        left unstated.
        """

        if traces:
            times = [trace.occurred_at for trace in traces]
            return min(times), max(times)

        horizon = timedelta(minutes=self.settings.forecast_horizon_minutes)
        return payload.observed_at - horizon, payload.observed_at

    def _create_model_version(
        self,
        session: Session,
        model: MonitoredModel,
        payload: ModelVersionCreate,
    ) -> ModelVersion:
        config_hash = self._canonical_hash(payload.configuration)
        tool_set_hash = self._canonical_hash(sorted(set(payload.tools)))
        fingerprint = self._canonical_hash(
            {
                "model_identifier": payload.model_identifier,
                "prompt_version": payload.prompt_version,
                "config_hash": config_hash,
                "tool_set_hash": tool_set_hash,
                "corpus_version": payload.corpus_version,
                "evaluation_policy_version": payload.evaluation_policy_version,
            }
        )
        duplicate = session.scalar(
            select(ModelVersion).where(
                ModelVersion.model_id == model.id,
                ModelVersion.fingerprint == fingerprint,
            )
        )
        if duplicate:
            raise ResourceConflict(
                "This exact model, prompt, tool, corpus, and evaluation configuration "
                "is already registered."
            )

        now = datetime.now(UTC)
        active_versions = session.scalars(
            select(ModelVersion).where(
                ModelVersion.model_id == model.id,
                ModelVersion.active_to.is_(None),
            )
        ).all()
        for version in active_versions:
            version.active_to = now

        version = ModelVersion(
            model_id=model.id,
            label=payload.label,
            model_identifier=payload.model_identifier,
            prompt_version=payload.prompt_version,
            config_hash=config_hash,
            tool_set_hash=tool_set_hash,
            corpus_version=payload.corpus_version,
            evaluation_policy_version=payload.evaluation_policy_version,
            fingerprint=fingerprint,
            active_from=now,
        )
        session.add(version)
        session.flush()
        return version

    @staticmethod
    def _active_model_version(session: Session, model_id: str) -> ModelVersion | None:
        return session.scalar(
            select(ModelVersion)
            .where(
                ModelVersion.model_id == model_id,
                ModelVersion.active_to.is_(None),
            )
            .order_by(ModelVersion.active_from.desc())
            .limit(1)
        )

    @staticmethod
    def _canonical_hash(value: object) -> str:
        serialized = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    @staticmethod
    def _require_model(session: Session, model_id: str) -> MonitoredModel:
        record = session.scalar(
            select(MonitoredModel).where(
                MonitoredModel.id == model_id,
                MonitoredModel.tenant_id == DriftZeroService._tenant_id(session),
            )
        )
        if not record:
            raise ResourceNotFound("Monitored model not found.")
        return record

    @staticmethod
    def _require_connection(session: Session, connection_id: str) -> ModelConnection:
        record = session.scalar(
            select(ModelConnection).where(
                ModelConnection.id == connection_id,
                ModelConnection.tenant_id == DriftZeroService._tenant_id(session),
            )
        )
        if record is None:
            raise ResourceNotFound("Model connection not found.")
        return record

    @staticmethod
    def _tenant_id(session: Session) -> str:
        return str(session.info.get("tenant_id", DEFAULT_TENANT_ID))

    @staticmethod
    def _require_alert_rule(session: Session, rule_id: str) -> AlertRule:
        record = session.scalar(
            select(AlertRule)
            .join(MonitoredModel, MonitoredModel.id == AlertRule.model_id)
            .where(
                AlertRule.id == rule_id,
                MonitoredModel.tenant_id == DriftZeroService._tenant_id(session),
            )
        )
        if record is None:
            raise ResourceNotFound("Alert rule not found.")
        return record

    @staticmethod
    def _require_alert(session: Session, alert_id: str) -> Alert:
        record = session.scalar(
            select(Alert)
            .join(MonitoredModel, MonitoredModel.id == Alert.model_id)
            .where(
                Alert.id == alert_id,
                MonitoredModel.tenant_id == DriftZeroService._tenant_id(session),
            )
        )
        if record is None:
            raise ResourceNotFound("Alert not found.")
        return record

    @staticmethod
    def _require_plan(
        session: Session,
        plan_id: str,
        *,
        for_update: bool = False,
    ) -> RecoveryPlan:
        statement = (
            select(RecoveryPlan)
            .join(MonitoredModel, MonitoredModel.id == RecoveryPlan.model_id)
            .where(
                RecoveryPlan.id == plan_id,
                MonitoredModel.tenant_id == DriftZeroService._tenant_id(session),
            )
        )
        if for_update:
            statement = statement.with_for_update()
        record = session.scalar(statement)
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
        entity_type, entity_id = DriftZeroService._audit_entity(
            model_id,
            event_type,
            details,
        )
        session.add(
            AuditEvent(
                model_id=model_id,
                tenant_id=DriftZeroService._tenant_id(session),
                event_type=event_type,
                actor=actor,
                actor_type=DriftZeroService._actor_type(actor),
                entity_type=entity_type,
                entity_id=entity_id,
                reason=str(details["summary"]) if details.get("summary") else None,
                request_id=get_request_id(),
                details=details,
            )
        )

    @staticmethod
    def _actor_type(actor: str) -> ActorType:
        normalized = actor.strip().lower()
        system_actors = {
            "demo-seeder",
            "diagnosis-engine",
            "ingestion",
            "pulse-engine",
            "recovery-adapter",
            "system",
            "verification-engine",
        }
        if normalized in system_actors or normalized.endswith("-engine"):
            return ActorType.SYSTEM
        if normalized.endswith("-bot") or normalized.startswith("agent:"):
            return ActorType.AGENT
        return ActorType.HUMAN

    @staticmethod
    def _audit_entity(
        model_id: str,
        event_type: str,
        details: dict[str, object],
    ) -> tuple[str, str]:
        prefix = event_type.partition(".")[0]
        entity_type = {
            "alert": "alert",
            "alert_rule": "alert_rule",
            "demo": "model",
            "diagnosis": "diagnosis",
            "incident": "incident",
            "model": "model",
            "recovery": "recovery_plan",
            "telemetry": "health_snapshot",
        }.get(prefix, "model")
        if prefix == "model" and details.get("version_id"):
            entity_type = "model_version"
        id_keys = {
            "alert": ("alert_id",),
            "alert_rule": ("rule_id",),
            "diagnosis": ("diagnosis_id",),
            "incident": ("incident_id",),
            "model": ("version_id",),
            "recovery": ("plan_id",),
            "telemetry": ("snapshot_id",),
        }.get(prefix, ())
        entity_id = next(
            (str(details[key]) for key in id_keys if details.get(key)),
            model_id,
        )
        return entity_type, entity_id

    @staticmethod
    def _model_response(record: MonitoredModel) -> ModelResponse:
        return ModelResponse.model_validate(record)

    @classmethod
    def _snapshot_response(cls, record: HealthSnapshot) -> HealthSnapshotResponse:
        return HealthSnapshotResponse(
            id=record.id,
            model_id=record.model_id,
            event_id=record.event_id,
            schema_version=record.schema_version,
            observed_at=record.observed_at,
            window_start=record.window_start,
            window_end=record.window_end,
            trace_count=record.trace_count,
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
            incident_id=record.incident_id,
            probable_cause=record.probable_cause,
            confidence=record.confidence,
            status=DiagnosisStatus(record.status),
            evidence=DriftZeroService._evidence_items(record),
            created_at=record.created_at,
        )

    @staticmethod
    def _evidence_items(record: Diagnosis) -> list[EvidenceItem]:
        """Prefer stored evidence rows, which carry the trace drill-down.

        Falls back to the JSON column so diagnoses written before evidence rows
        existed still render.
        """

        if record.evidence_items:
            return [
                EvidenceItem(
                    reason_code=item.reason_code,
                    metric=item.metric,
                    summary=item.summary,
                    baseline_value=item.baseline_value,
                    current_value=item.current_value,
                    change=item.change,
                    supports_diagnosis=item.supports_diagnosis,
                    trace_ids=[trace.id for trace in item.traces],
                )
                for item in record.evidence_items
            ]
        return [EvidenceItem.model_validate(item) for item in record.evidence]

    @staticmethod
    def _recovery_response(record: RecoveryPlan) -> RecoveryPlanResponse:
        # action_items is ordered by playbook step; sorting across actions by id
        # would scramble the sequence a reader needs to follow.
        executions = [
            execution
            for action in record.action_items
            for execution in sorted(action.executions, key=lambda item: item.attempt)
        ]
        verification = max(
            record.verification_runs, key=lambda run: run.started_at, default=None
        )
        return RecoveryPlanResponse(
            id=record.id,
            model_id=record.model_id,
            diagnosis_id=record.diagnosis_id,
            incident_id=record.incident_id,
            state=RecoveryState(record.state),
            risk=RiskLevel(record.risk),
            version=record.version,
            approval_level=RiskLevel(record.approval_level),
            requires_approval=record.requires_approval,
            policy_version=record.policy_version,
            actions=[RecoveryAction.model_validate(item) for item in record.actions],
            simulation=record.simulation,
            failure_reason=record.failure_reason,
            created_at=record.created_at,
            approved_at=record.approved_at,
            approved_by=record.approved_by,
            approved_role=ActorRole(record.approved_role) if record.approved_role else None,
            approval_reason=record.approval_reason,
            rejected_at=record.rejected_at,
            rejected_by=record.rejected_by,
            rejected_reason=record.rejected_reason,
            executed_at=record.executed_at,
            verified_at=record.verified_at,
            rolled_back_at=record.rolled_back_at,
            executions=[
                RecoveryExecutionResponse.model_validate(execution) for execution in executions
            ],
            verification=(
                VerificationRunResponse.model_validate(verification) if verification else None
            ),
        )

    @staticmethod
    def _audit_response(record: AuditEvent) -> AuditEventResponse:
        return AuditEventResponse(
            id=record.id,
            model_id=record.model_id,
            event_type=record.event_type,
            actor=record.actor,
            actor_type=record.actor_type.value,
            entity_type=record.entity_type,
            entity_id=record.entity_id,
            reason=record.reason,
            request_id=record.request_id,
            details=record.details,
            created_at=record.created_at,
        )
