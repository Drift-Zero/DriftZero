"""Application service coordinating scoring, diagnosis, recovery, and storage."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

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
    EvaluatorVersion,
    HealthForecastRecord,
    Incident,
    KnowledgeDocument,
    KnowledgeSource,
    KnowledgeStatus,
    ModelVersion,
    RecoveryActionRecord,
    RecoveryExecution,
    StabilityClaim,
    StabilityTest,
    StabilityVariant,
    Trace,
    VerificationRun,
    ensure_health_policy,
    latest_snapshot,
    snapshot_timeline,
    traces_for_metric,
)
from app.diagnosis import diagnose_change
from app.evaluation import EvaluatorAdapter, SimulatedEvaluator
from app.recovery import RecoveryAdapter, SimulatedRecoveryAdapter, build_playbook
from app.redaction import REDACTION_POLICY_VERSION, content_hash, redact
from app.schemas import (
    ActorRequest,
    ActorType,
    AuditEventResponse,
    DemoResetResponse,
    DiagnosisResponse,
    DiagnosisStatus,
    DimensionScores,
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
    ModelResponse,
    ModelVersionCreate,
    ModelVersionResponse,
    RecoveryAction,
    RecoveryExecutionResponse,
    RecoveryPlanResponse,
    RecoveryState,
    RiskLevel,
    Severity,
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


class DriftZeroService:
    def __init__(
        self,
        settings: Settings,
        recovery_adapter: RecoveryAdapter | None = None,
        evaluator: EvaluatorAdapter | None = None,
    ) -> None:
        self.settings = settings
        self.recovery_adapter = recovery_adapter or SimulatedRecoveryAdapter()
        self.evaluator = evaluator or SimulatedEvaluator()

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
        incident = self._open_incident(session, model_id)
        diagnosis = Diagnosis(
            model_id=model_id,
            snapshot_id=latest.id,
            incident_id=incident.id if incident else None,
            probable_cause=result.probable_cause,
            confidence=result.confidence,
            status=DiagnosisStatus.OPEN.value,
            evidence=[item.model_dump(mode="json") for item in result.evidence],
        )
        session.add(diagnosis)
        session.flush()
        self._record_evidence(session, diagnosis, latest, result.evidence)
        self._advance_incident(session, incident, IncidentState.DIAGNOSING)

        playbook = build_playbook(result.probable_cause)
        plan = RecoveryPlan(
            model_id=model_id,
            diagnosis_id=diagnosis.id,
            incident_id=diagnosis.incident_id,
            state=RecoveryState.RECOMMENDED.value,
            risk=playbook.risk.value,
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
        incident = self._open_incident(session, plan.model_id)
        self._advance_incident(session, incident, IncidentState.VERIFYING)
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
            plan.verified_at = datetime.now(UTC)
            if not recovered:
                # Leave the system no worse than we found it: undo what can be
                # undone, and record what could not.
                self._rollback_actions(session, plan, executions, payload.actor)
                plan.rolled_back_at = datetime.now(UTC)
            if recovered:
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
            execution = RecoveryExecution(
                action_id=record.id,
                plan_id=plan.id,
                actor=actor,
                actor_type=ActorType.HUMAN.value,
                reason=f"Executing playbook step {record.order}: {record.code}",
                state=ExecutionState.SKIPPED.value if aborted else ExecutionState.RUNNING.value,
            )
            session.add(execution)

            if aborted:
                session.flush()
                executions.append(execution)
                continue

            execution.started_at = datetime.now(UTC)
            action = RecoveryAction(
                order=record.order,
                code=record.code,
                title=record.title,
                description=record.description,
                risk=RiskLevel(record.risk),
                reversible=record.reversible,
            )
            outcome = self.recovery_adapter.execute_action(
                model_id=plan.model_id, plan_id=plan.id, action=action
            )
            execution.finished_at = datetime.now(UTC)
            execution.affected_traffic_pct = outcome.affected_traffic_pct
            execution.result = dict(outcome.detail)
            execution.error = outcome.error
            execution.state = (
                ExecutionState.SUCCEEDED.value if outcome.succeeded else ExecutionState.FAILED.value
            )
            aborted = not outcome.succeeded
            session.flush()
            executions.append(execution)

        return executions

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
            outcome = self.recovery_adapter.rollback_action(
                model_id=plan.model_id, plan_id=plan.id, action=action
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

    # Dimensions that must not get worse for a recovery to count, and how much
    # slack to allow before calling a movement a regression.
    _NO_REGRESSION_METRICS = ("safety", "latency", "reliability")
    _REGRESSION_TOLERANCE = 2.0

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
        checks: list[dict[str, Any]] = []
        for metric in self._NO_REGRESSION_METRICS:
            before = getattr(baseline, metric, None) if baseline else None
            after = getattr(snapshot, metric, None)
            passed = before is None or after is None or after >= before - self._REGRESSION_TOLERANCE
            checks.append(
                {
                    "metric": metric,
                    "baseline": before,
                    "current": after,
                    "passed": passed,
                }
            )

        cleared = snapshot.score is not None and snapshot.score >= threshold
        passed = cleared and all(check["passed"] for check in checks)

        run = VerificationRun(
            plan_id=plan.id,
            incident_id=incident.id if incident else None,
            snapshot_id=snapshot.id,
            required_requests=evaluated_requests,
            observed_requests=evaluated_requests,
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
    # Model versions and the signature stability evaluations
    # ---------------------------------------------------------------- #

    def register_model_version(
        self,
        session: Session,
        model_id: str,
        payload: ModelVersionCreate,
    ) -> ModelVersionResponse:
        """Record a new set of controlled inputs, retiring the previous one.

        Re-registering identical inputs returns the existing version rather than
        creating a duplicate, so a caller that re-declares its configuration on
        every boot does not fragment the comparison history.
        """

        self._require_model(session, model_id)
        fingerprint = ModelVersion.fingerprint_for(**payload.model_dump())

        existing = session.scalar(
            select(ModelVersion).where(
                ModelVersion.model_id == model_id,
                ModelVersion.fingerprint == fingerprint,
            )
        )
        if existing is not None:
            return ModelVersionResponse.model_validate(existing)

        now = datetime.now(UTC)
        current = self._active_model_version(session, model_id)
        if current is not None:
            current.active_to = now

        version = ModelVersion(
            model_id=model_id,
            fingerprint=fingerprint,
            active_from=now,
            **payload.model_dump(),
        )
        session.add(version)
        session.flush()
        self._audit(
            session,
            model_id,
            "model_version.registered",
            "system",
            {"version_id": version.id, "label": version.label, "fingerprint": fingerprint},
        )
        session.commit()
        return ModelVersionResponse.model_validate(version)

    def list_model_versions(
        self, session: Session, model_id: str
    ) -> list[ModelVersionResponse]:
        self._require_model(session, model_id)
        records = session.scalars(
            select(ModelVersion)
            .where(ModelVersion.model_id == model_id)
            .order_by(ModelVersion.active_from.desc())
        ).all()
        return [ModelVersionResponse.model_validate(record) for record in records]

    @staticmethod
    def _active_model_version(session: Session, model_id: str) -> ModelVersion | None:
        return session.scalar(
            select(ModelVersion)
            .where(ModelVersion.model_id == model_id, ModelVersion.active_to.is_(None))
            .order_by(ModelVersion.active_from.desc())
            .limit(1)
        )

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
        incident = self._open_incident(session, model.id)
        return DemoResetResponse(
            model=self._model_response(model),
            health=self.health_timeline(session, model.id),
            diagnosis=diagnosis,
            recovery=self.latest_recovery(session, model.id),
            incident=IncidentResponse.model_validate(incident) if incident else None,
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

        if incident is not None and IncidentState(incident.state) is IncidentState.VERIFYING:
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
        self._settle_forecasts(session, record)
        self._store_forecast(session, record)
        self._sync_incident(session, model_id, record)
        return record

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
            actions=[RecoveryAction.model_validate(item) for item in record.actions],
            simulation=record.simulation,
            created_at=record.created_at,
            approved_at=record.approved_at,
            approved_by=record.approved_by,
            executed_at=record.executed_at,
            verified_at=record.verified_at,
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
            details=record.details,
            created_at=record.created_at,
        )
