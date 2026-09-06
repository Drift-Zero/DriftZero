"""Validated API contracts shared by DriftZero services and routes."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Score = Annotated[float, Field(ge=0, le=100)]


def utc_now() -> datetime:
    return datetime.now(UTC)


class HealthState(StrEnum):
    INSUFFICIENT_DATA = "insufficient_data"
    HEALTHY = "healthy"
    WARNING = "warning"
    CRITICAL = "critical"


class SignalSource(StrEnum):
    OBSERVED = "observed"
    INFERRED = "inferred"
    SIMULATED = "simulated"


class Severity(StrEnum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class IncidentState(StrEnum):
    """Lifecycle of a degradation, from detection through verified recovery."""

    OPEN = "open"
    DIAGNOSING = "diagnosing"
    MITIGATING = "mitigating"
    VERIFYING = "verifying"
    RESOLVED = "resolved"
    FAILED = "failed"


class ReviewState(StrEnum):
    PENDING = "pending"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    REJECTED = "rejected"


class FeedbackVerdict(StrEnum):
    AGREE = "agree"
    DISAGREE = "disagree"
    UNSURE = "unsure"


class FeedbackTarget(StrEnum):
    """What a human is passing judgement on."""

    DIAGNOSIS = "diagnosis"
    STABILITY_TEST = "stability_test"
    HEALTH_SNAPSHOT = "health_snapshot"


class AlertState(StrEnum):
    FIRING = "firing"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


class Comparator(StrEnum):
    """How a metric is compared against a rule's threshold."""

    LT = "lt"
    LTE = "lte"
    GT = "gt"
    GTE = "gte"


class AlertRuleType(StrEnum):
    """Supported alert evaluation strategies."""

    THRESHOLD = "threshold"
    TRANSITION = "transition"
    TRAJECTORY = "trajectory"
    COVERAGE = "coverage"
    EVALUATION_FRESHNESS = "evaluation_freshness"


class AlertMetric(StrEnum):
    SCORE = "score"
    QUALITY = "quality"
    GROUNDEDNESS = "groundedness"
    SEMANTIC_STABILITY = "semantic_stability"
    TEMPORAL_STABILITY = "temporal_stability"
    SAFETY = "safety"
    DRIFT = "drift"
    RELIABILITY = "reliability"
    LATENCY = "latency"
    COST = "cost"
    STATE = "state"
    COVERAGE = "coverage"
    FORECAST_SCORE = "forecast_score"
    FORECAST_CHANGE_PER_HOUR = "forecast_change_per_hour"
    EVALUATION_AGE_MINUTES = "evaluation_age_minutes"


class StabilityKind(StrEnum):
    SEMANTIC = "semantic"
    TEMPORAL = "temporal"


class StabilityVerdict(StrEnum):
    STABLE = "stable"
    DRIFTING = "drifting"
    CRITICAL = "critical"
    INCONCLUSIVE = "inconclusive"


class EvaluatorKind(StrEnum):
    QUALITY = "quality"
    GROUNDEDNESS = "groundedness"
    SAFETY = "safety"
    SEMANTIC_STABILITY = "semantic_stability"
    TEMPORAL_STABILITY = "temporal_stability"


class TraceStatus(StrEnum):
    OK = "ok"
    ERROR = "error"
    TIMEOUT = "timeout"
    FILTERED = "filtered"


class DiagnosisStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"


class RecoveryState(StrEnum):
    RECOMMENDED = "recommended"
    APPROVED = "approved"
    QUEUED = "queued"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    RECOVERED = "recovered"
    FAILED = "failed"
    REJECTED = "rejected"
    CANCELED = "canceled"
    ROLLED_BACK = "rolled_back"


class ExecutionState(StrEnum):
    """Lifecycle of a single recovery action attempt."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    ROLLED_BACK = "rolled_back"
    SKIPPED = "skipped"


class RecoveryCommandType(StrEnum):
    EXECUTE = "execute"
    ROLLBACK = "rollback"
    VERIFY = "verify"


class RecoveryCommandState(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"


class ActorType(StrEnum):
    HUMAN = "human"
    SYSTEM = "system"
    AGENT = "agent"


class ActorRole(StrEnum):
    """Recovery authorization role asserted by the authenticated API layer."""

    VIEWER = "viewer"
    OPERATOR = "operator"
    ADMIN = "admin"
    SERVICE = "service"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class DimensionScores(BaseModel):
    """Normalized component scores where 100 always means healthier."""

    quality: Score | None = None
    groundedness: Score | None = None
    semantic_stability: Score | None = None
    temporal_stability: Score | None = None
    safety: Score | None = None
    drift: Score | None = None
    reliability: Score | None = None
    latency: Score | None = None
    cost: Score | None = None


ModelLifecycleState = Literal["active", "paused", "retired"]


class ModelVersionCreate(BaseModel):
    """Controlled inputs that uniquely identify one deployed model version."""

    label: str = Field(min_length=1, max_length=120)
    model_identifier: str = Field(min_length=1, max_length=160)
    prompt_version: str = Field(min_length=1, max_length=80)
    configuration: dict[str, object] = Field(default_factory=dict)
    tools: list[str] = Field(default_factory=list, max_length=100)
    corpus_version: str | None = Field(default=None, max_length=80)
    evaluation_policy_version: str = Field(default="health-v1", min_length=1, max_length=40)
    actor: str = Field(default="system", min_length=1, max_length=120)


class ModelCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    provider: str = Field(default="custom", min_length=1, max_length=80)
    environment: str = Field(default="production", min_length=1, max_length=40)
    description: str | None = Field(default=None, max_length=2000)
    retention_days: int = Field(default=30, ge=1, le=3650)
    initial_version: ModelVersionCreate | None = None
    actor: str = Field(default="system", min_length=1, max_length=120)


class ModelResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    provider: str
    environment: str
    description: str | None
    status: ModelLifecycleState
    retention_days: int
    created_at: datetime
    updated_at: datetime


class ModelUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    provider: str | None = Field(default=None, min_length=1, max_length=80)
    environment: str | None = Field(default=None, min_length=1, max_length=40)
    description: str | None = Field(default=None, max_length=2000)
    retention_days: int | None = Field(default=None, ge=1, le=3650)
    actor: str = Field(min_length=1, max_length=120)

    @model_validator(mode="after")
    def require_change(self) -> ModelUpdate:
        fields = ("name", "provider", "environment", "description", "retention_days")
        if not any(field in self.model_fields_set for field in fields):
            raise ValueError("At least one model field must be supplied.")
        return self


class ModelLifecycleUpdate(BaseModel):
    status: ModelLifecycleState
    actor: str = Field(min_length=1, max_length=120)


class ModelVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    model_id: str
    label: str
    model_identifier: str
    prompt_version: str
    config_hash: str
    tool_set_hash: str
    corpus_version: str | None
    evaluation_policy_version: str
    fingerprint: str
    active_from: datetime
    active_to: datetime | None
    created_at: datetime


class RegistrationCheck(BaseModel):
    code: str
    passed: bool
    detail: str


class RegistrationStatusResponse(BaseModel):
    model_id: str
    ready_for_telemetry: bool
    monitoring_state: Literal["paused", "awaiting_telemetry", "receiving_telemetry"]
    active_version_id: str | None
    checks: list[RegistrationCheck]


class TraceCreate(BaseModel):
    """One observed request/response interaction.

    ``question`` and ``answer`` are redacted before storage and only the
    redacted rendering is persisted, alongside a hash of the original.
    """

    occurred_at: datetime = Field(default_factory=utc_now)
    request_id: str | None = Field(default=None, max_length=120)
    question: str | None = None
    answer: str | None = None
    provider: str | None = Field(default=None, max_length=80)
    status: TraceStatus = TraceStatus.OK
    error_code: str | None = Field(default=None, max_length=80)
    latency_ms: int | None = Field(default=None, ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    cost_usd: float | None = Field(default=None, ge=0)
    retrieved_document_ids: list[str] = Field(default_factory=list)
    citation_count: int = Field(default=0, ge=0)
    unsupported_claim_count: int = Field(default=0, ge=0)
    groundedness_score: Score | None = None
    quality_score: Score | None = None
    safety_flags: list[str] = Field(default_factory=list)
    is_simulated: bool = False


class TraceResponse(BaseModel):
    """A stored trace. Never carries raw prompt or response text."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    model_id: str
    occurred_at: datetime
    request_id: str | None = None
    question_redacted: str | None = None
    answer_redacted: str | None = None
    prompt_hash: str | None = None
    answer_hash: str | None = None
    redaction_policy_version: str
    provider: str | None = None
    status: TraceStatus
    latency_ms: int | None = None
    retrieved_document_ids: list[str] = Field(default_factory=list)
    citation_count: int = 0
    unsupported_claim_count: int = 0
    groundedness_score: float | None = None
    quality_score: float | None = None
    safety_flags: list[str] = Field(default_factory=list)
    is_simulated: bool = False


class StabilityClaimResponse(BaseModel):
    """A material fact asserted by one variant."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    variant_id: str
    claim_key: str
    claim_text_redacted: str
    value_text: str | None = None
    agrees_with_baseline: bool | None = None
    disagreement_note: str | None = None


class StabilityVariantResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    variant_index: int
    prompt_redacted: str
    answer_redacted: str | None = None
    is_baseline: bool
    trace_id: str | None = None
    captured_at: datetime


class StabilityTestResponse(BaseModel):
    """A stability evaluation, its variants, and the claims they disagreed on."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    model_id: str
    kind: StabilityKind
    question_redacted: str
    stability_score: float | None = None
    evaluator_confidence: float | None = None
    verdict: StabilityVerdict
    confidence_label: str = "estimated"
    inputs_changed: bool = False
    changed_inputs: dict[str, object] = Field(default_factory=dict)
    model_version_id: str | None = None
    baseline_version_id: str | None = None
    evaluator_version_id: str | None = None
    run_at: datetime
    variants: list[StabilityVariantResponse] = Field(default_factory=list)
    claims: list[StabilityClaimResponse] = Field(default_factory=list)


class StabilityRunRequest(BaseModel):
    question: str = Field(min_length=1)
    variants: int = Field(default=4, ge=2, le=5)


class TelemetryCreate(BaseModel):
    observed_at: datetime = Field(default_factory=utc_now)
    dimensions: DimensionScores
    sample_size: int = Field(ge=1)
    coverage: float = Field(ge=0, le=1)
    source: SignalSource = SignalSource.OBSERVED
    traces: list[TraceCreate] = Field(default_factory=list)


class HealthSnapshotResponse(BaseModel):
    id: str
    model_id: str
    observed_at: datetime
    window_start: datetime | None = None
    window_end: datetime | None = None
    trace_count: int = 0
    dimensions: DimensionScores
    score: float | None
    state: HealthState
    confidence: float = Field(ge=0, le=1)
    sample_size: int
    coverage: float
    policy_version: str
    source: SignalSource
    missing_dimensions: list[str] = Field(default_factory=list)


class HealthForecast(BaseModel):
    horizon_minutes: int
    predicted_score: float
    lower_bound: float
    upper_bound: float
    change_per_hour: float
    direction: str
    method: str = "recent_slope_v1"


class HealthForecastRecordResponse(BaseModel):
    """A stored prediction and, once the horizon elapses, what happened.

    Keeping both is what allows the early-warning claim to be checked rather
    than taken on trust.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    model_id: str
    snapshot_id: str
    horizon_minutes: int
    predicted_score: float
    lower_bound: float
    upper_bound: float
    change_per_hour: float
    direction: str
    method: str
    target_at: datetime | None = None
    actual_score: float | None = None
    created_at: datetime


class HealthTimelineResponse(BaseModel):
    model: ModelResponse
    snapshots: list[HealthSnapshotResponse]
    forecast: HealthForecast | None


class EvidenceItem(BaseModel):
    reason_code: str
    metric: str
    summary: str
    baseline_value: float | None = None
    current_value: float | None = None
    change: float | None = None
    supports_diagnosis: bool
    trace_ids: list[str] = Field(default_factory=list)


class IncidentResponse(BaseModel):
    """A period of degradation and everything attached to it."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    model_id: str
    title: str
    state: IncidentState
    severity: Severity
    opened_at: datetime
    closed_at: datetime | None = None
    opening_snapshot_id: str | None = None
    closing_snapshot_id: str | None = None
    baseline_score: float | None = None
    trough_score: float | None = None
    summary: str | None = None


class DiagnosisResponse(BaseModel):
    id: str
    model_id: str
    snapshot_id: str
    incident_id: str | None = None
    probable_cause: str
    confidence: float = Field(ge=0, le=1)
    confidence_label: str = "estimated"
    status: DiagnosisStatus
    evidence: list[EvidenceItem]
    created_at: datetime


class RecoveryAction(BaseModel):
    order: int = Field(ge=1)
    code: str
    title: str
    description: str
    risk: RiskLevel
    reversible: bool


class RecoveryExecutionResponse(BaseModel):
    """One attempt at one action, including its blast radius and rollback."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    action_id: str
    plan_id: str
    state: ExecutionState
    attempt: int
    actor: str
    actor_type: ActorType
    reason: str | None = None
    affected_traffic_pct: float | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    result: dict[str, object] = Field(default_factory=dict)
    error: str | None = None
    external_operation_id: str | None = None
    configuration_verified_at: datetime | None = None
    config_before: dict[str, object] = Field(default_factory=dict)
    config_after: dict[str, object] = Field(default_factory=dict)
    rolled_back_at: datetime | None = None
    rollback_result: dict[str, object] = Field(default_factory=dict)


class VerificationRunResponse(BaseModel):
    """What "recovered" was judged against, recorded with the verdict."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    plan_id: str
    incident_id: str | None = None
    snapshot_id: str | None = None
    required_requests: int
    observed_requests: int
    required_coverage: float
    observed_coverage: float
    threshold: float
    baseline_score: float | None = None
    post_score: float | None = None
    passed: bool | None = None
    no_regression_checks: list[dict[str, object]] = Field(default_factory=list)
    window_start: datetime | None = None
    window_end: datetime | None = None
    started_at: datetime
    finished_at: datetime | None = None


class RecoveryCommandResponse(BaseModel):
    """A durable request for a worker to execute a recovery transition."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    plan_id: str
    command_type: RecoveryCommandType
    state: RecoveryCommandState
    idempotency_key: str
    actor: str
    actor_role: ActorRole
    reason: str | None = None
    max_traffic_pct: float
    attempt: int
    max_attempts: int
    requested_at: datetime
    available_at: datetime
    claimed_at: datetime | None = None
    lease_expires_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None
    snapshot_id: str | None = None


class RecoveryPlanResponse(BaseModel):
    id: str
    model_id: str
    diagnosis_id: str
    incident_id: str | None = None
    state: RecoveryState
    risk: RiskLevel
    version: int
    approval_level: RiskLevel
    requires_approval: bool
    policy_version: str
    actions: list[RecoveryAction]
    simulation: bool
    failure_reason: str | None = None
    created_at: datetime
    approved_at: datetime | None = None
    approved_by: str | None = None
    approved_role: ActorRole | None = None
    approval_reason: str | None = None
    rejected_at: datetime | None = None
    rejected_by: str | None = None
    rejected_reason: str | None = None
    executed_at: datetime | None = None
    verified_at: datetime | None = None
    rolled_back_at: datetime | None = None
    executions: list[RecoveryExecutionResponse] = Field(default_factory=list)
    verification: VerificationRunResponse | None = None


class AlertRuleDefinition(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    rule_type: AlertRuleType = AlertRuleType.THRESHOLD
    metric: AlertMetric = AlertMetric.SCORE
    comparator: Comparator | None = Comparator.LT
    threshold: float | None = None
    target_state: HealthState | None = None
    window_minutes: int = Field(default=15, ge=1, le=10_080)
    cooldown_minutes: int = Field(default=30, ge=0, le=10_080)
    minimum_consecutive_windows: int = Field(default=1, ge=1, le=100)
    severity: Severity = Severity.MEDIUM
    channel: Literal["in_app"] = "in_app"
    is_enabled: bool = True

    @model_validator(mode="after")
    def validate_strategy(self) -> AlertRuleDefinition:
        dimension_metrics = {
            AlertMetric.SCORE,
            AlertMetric.QUALITY,
            AlertMetric.GROUNDEDNESS,
            AlertMetric.SEMANTIC_STABILITY,
            AlertMetric.TEMPORAL_STABILITY,
            AlertMetric.SAFETY,
            AlertMetric.DRIFT,
            AlertMetric.RELIABILITY,
            AlertMetric.LATENCY,
            AlertMetric.COST,
        }
        expected_metrics = {
            AlertRuleType.THRESHOLD: dimension_metrics,
            AlertRuleType.TRANSITION: {AlertMetric.STATE},
            AlertRuleType.TRAJECTORY: {
                AlertMetric.FORECAST_SCORE,
                AlertMetric.FORECAST_CHANGE_PER_HOUR,
            },
            AlertRuleType.COVERAGE: {AlertMetric.COVERAGE},
            AlertRuleType.EVALUATION_FRESHNESS: {AlertMetric.EVALUATION_AGE_MINUTES},
        }
        if self.metric not in expected_metrics[self.rule_type]:
            allowed = ", ".join(sorted(item.value for item in expected_metrics[self.rule_type]))
            raise ValueError(f"{self.rule_type.value} rules require one of: {allowed}.")

        if self.rule_type is AlertRuleType.TRANSITION:
            if self.target_state is None:
                raise ValueError("Transition rules require target_state.")
            if self.target_state is HealthState.INSUFFICIENT_DATA:
                raise ValueError("Use a coverage rule instead of alerting on insufficient_data.")
            if self.threshold is not None or self.comparator is not None:
                raise ValueError("Transition rules do not accept comparator or threshold.")
        else:
            if self.threshold is None or self.comparator is None:
                raise ValueError(f"{self.rule_type.value} rules require comparator and threshold.")
            if self.target_state is not None:
                raise ValueError("target_state is only valid for transition rules.")

        if (
            self.metric in dimension_metrics | {AlertMetric.FORECAST_SCORE}
            and self.threshold is not None
            and not 0 <= self.threshold <= 100
        ):
            raise ValueError(f"{self.metric.value} thresholds must be between 0 and 100.")
        if (
            self.metric is AlertMetric.COVERAGE
            and self.threshold is not None
            and not 0 <= self.threshold <= 1
        ):
            raise ValueError("Coverage thresholds must be between 0 and 1.")
        if (
            self.metric is AlertMetric.EVALUATION_AGE_MINUTES
            and self.threshold is not None
            and self.threshold < 0
        ):
            raise ValueError("Evaluation freshness thresholds cannot be negative.")
        return self


class AlertRuleCreate(AlertRuleDefinition):
    actor: str = Field(default="system", min_length=1, max_length=120, exclude=True)


class AlertRuleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    rule_type: AlertRuleType | None = None
    metric: AlertMetric | None = None
    comparator: Comparator | None = None
    threshold: float | None = None
    target_state: HealthState | None = None
    window_minutes: int | None = Field(default=None, ge=1, le=10_080)
    cooldown_minutes: int | None = Field(default=None, ge=0, le=10_080)
    minimum_consecutive_windows: int | None = Field(default=None, ge=1, le=100)
    severity: Severity | None = None
    channel: Literal["in_app"] | None = None
    is_enabled: bool | None = None
    actor: str = Field(min_length=1, max_length=120)

    @model_validator(mode="after")
    def require_change(self) -> AlertRuleUpdate:
        if self.model_fields_set == {"actor"}:
            raise ValueError("At least one alert rule field must be supplied.")
        return self


class AlertRuleResponse(AlertRuleDefinition):
    model_config = ConfigDict(from_attributes=True)

    id: str
    model_id: str
    created_at: datetime
    updated_at: datetime


class AlertResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    model_id: str
    rule_id: str | None = None
    snapshot_id: str | None = None
    incident_id: str | None = None
    state: AlertState
    severity: Severity
    message: str
    observed_value: float | None = None
    details: dict[str, object] = Field(default_factory=dict)
    fired_at: datetime
    acknowledged_at: datetime | None = None
    acknowledged_by: str | None = None
    resolved_at: datetime | None = None
    resolution_reason: str | None = None
    notified_at: datetime | None = None


class AlertResolveRequest(BaseModel):
    actor: str = Field(min_length=1, max_length=120)
    reason: str = Field(min_length=1, max_length=1000)


class AlertEvaluationRequest(BaseModel):
    actor: str = Field(default="alerting-engine", min_length=1, max_length=120)
    evaluated_at: datetime = Field(default_factory=utc_now)


class AlertEvaluationResponse(BaseModel):
    model_id: str
    evaluated_at: datetime
    evaluated_rules: int
    fired: list[AlertResponse] = Field(default_factory=list)
    resolved: list[AlertResponse] = Field(default_factory=list)


class AlertFeedResponse(BaseModel):
    items: list[AlertResponse]
    total: int
    firing: int
    acknowledged: int


class ReviewQueueItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    model_id: str
    trace_id: str | None = None
    incident_id: str | None = None
    reason: str
    state: ReviewState
    assigned_to: str | None = None
    decided_by: str | None = None
    decided_at: datetime | None = None
    notes: str | None = None
    created_at: datetime


class ReviewDecisionRequest(BaseModel):
    actor: str = Field(min_length=1, max_length=120)
    state: ReviewState
    notes: str | None = None


class EvaluationFeedbackCreate(BaseModel):
    target_type: FeedbackTarget
    target_id: str = Field(min_length=1, max_length=36)
    actor: str = Field(min_length=1, max_length=120)
    verdict: FeedbackVerdict
    note: str | None = None


class EvaluationFeedbackResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    target_type: str
    target_id: str
    actor: str
    verdict: FeedbackVerdict
    note: str | None = None
    created_at: datetime


class ActorRequest(BaseModel):
    actor: str = Field(min_length=1, max_length=120)
    role: ActorRole = ActorRole.OPERATOR
    reason: str | None = Field(default=None, max_length=500)


class RecoveryDecisionRequest(ActorRequest):
    expected_version: int | None = Field(default=None, ge=1)


class RecoveryExecuteRequest(ActorRequest):
    idempotency_key: str = Field(min_length=8, max_length=120)
    expected_version: int | None = Field(default=None, ge=1)
    max_traffic_pct: float = Field(default=100.0, ge=0, le=100)


class RecoveryVerifyRequest(ActorRequest):
    snapshot_id: str = Field(min_length=1, max_length=36)
    idempotency_key: str = Field(min_length=8, max_length=120)


class AuditEventResponse(BaseModel):
    id: str
    model_id: str | None
    event_type: str
    actor: str
    actor_type: Literal["human", "system", "agent"]
    entity_type: str | None = None
    entity_id: str | None = None
    reason: str | None = None
    request_id: str | None = None
    details: dict[str, object]
    created_at: datetime


class DemoResetResponse(BaseModel):
    model: ModelResponse
    health: HealthTimelineResponse
    diagnosis: DiagnosisResponse
    recovery: RecoveryPlanResponse
    incident: IncidentResponse | None = None
