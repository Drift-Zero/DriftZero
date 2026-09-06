"""Application service coordinating scoring, diagnosis, recovery, and storage."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

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
from app.db import (
    DiagnosisEvidence,
    KnowledgeDocument,
    KnowledgeSource,
    KnowledgeStatus,
    Trace,
    ensure_health_policy,
    traces_for_metric,
)
from app.diagnosis import diagnose_change
from app.recovery import RecoveryAdapter, SimulatedRecoveryAdapter, build_playbook
from app.redaction import REDACTION_POLICY_VERSION, content_hash, redact
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
    TraceCreate,
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
        self._record_evidence(session, diagnosis, latest, result.evidence)

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
        plan.approved_at = datetime.now(UTC)
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
        plan.executed_at = datetime.now(UTC)
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
                    observed_at=datetime.now(UTC) + timedelta(seconds=1),
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
            plan.verified_at = datetime.now(UTC)
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
        now = datetime.now(UTC)
        stale_document = self._seed_knowledge_corpus(session, model.id, now)
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
                    traces=self._demo_traces(observed_at, index, stale_document.external_ref),
                ),
            )
        self._audit(
            session,
            model.id,
            "demo.reset",
            "demo-seeder",
            {
                "scenario": "knowledge_freshness_failure",
                "snapshots": len(demo_points),
                "stale_document": stale_document.external_ref,
            },
        )
        session.commit()

        diagnosis = self.diagnose_latest(session, model.id)
        return DemoResetResponse(
            model=self._model_response(model),
            health=self.health_timeline(session, model.id),
            diagnosis=diagnosis,
            recovery=self.latest_recovery(session, model.id),
        )

    def _seed_knowledge_corpus(
        self,
        session: Session,
        model_id: str,
        now: datetime,
    ) -> KnowledgeDocument:
        """Seed the corpus behind the CampusGPT failure.

        A new fee policy was published, but the retriever kept serving the
        superseded one. Modelling both documents and the link between them is
        what turns "the retriever served stale documents" into something a user
        can verify rather than a claim they have to accept.

        Returns the stale document, which the seeded traces cite.
        """

        source = KnowledgeSource(
            model_id=model_id,
            name="Examination Policy Corpus",
            kind="corpus",
            corpus_version="2026-01-14",
            status=KnowledgeStatus.STALE,
            document_count=2,
            last_refreshed_at=now - timedelta(days=21),
        )
        session.add(source)
        session.flush()

        current = KnowledgeDocument(
            source_id=source.id,
            external_ref="policy/exam-fee-2026-03",
            title="Examination Fee Policy (effective 2026-03-01)",
            content_hash=content_hash("exam fee deadline 2026-03-28") or "",
            published_at=now - timedelta(days=3),
            indexed_at=None,
            is_stale=False,
        )
        session.add(current)
        session.flush()

        stale = KnowledgeDocument(
            source_id=source.id,
            external_ref="policy/exam-fee-2025-11",
            title="Examination Fee Policy (superseded)",
            content_hash=content_hash("exam fee deadline 2026-02-14") or "",
            published_at=now - timedelta(days=120),
            indexed_at=now - timedelta(days=21),
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
            "When is the examination fee deadline this semester?",
            "Can I still pay the exam fee after the due date?",
            "What is the last date to pay examination fees?",
            "Has the exam fee deadline been extended? Reply to me at student@campus.edu",
        )

        traces: list[TraceCreate] = []
        for offset, question in enumerate(questions):
            cites_stale = step >= 1
            traces.append(
                TraceCreate(
                    occurred_at=observed_at - timedelta(seconds=90 - offset * 20),
                    request_id=f"campus-{step}-{offset}",
                    question=question,
                    answer=(
                        "The examination fee deadline is 14 February 2026."
                        if cites_stale
                        else "The examination fee deadline is 28 March 2026."
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
    ) -> HealthSnapshot:
        score = calculate_health(
            payload.dimensions,
            sample_size=payload.sample_size,
            coverage=payload.coverage,
            minimum_sample_size=self.settings.minimum_sample_size,
            minimum_coverage=self.settings.minimum_coverage,
        )
        traces = self._record_traces(session, model_id, payload.traces)
        window_start, window_end = self._evaluation_window(payload, traces)
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
            observed_at=payload.observed_at,
            window_start=window_start,
            window_end=window_end,
            **payload.dimensions.model_dump(),
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
        return record

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
