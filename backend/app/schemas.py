"""Validated API contracts shared by DriftZero services and routes."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

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
    EXECUTING = "executing"
    RECOVERED = "recovered"
    FAILED = "failed"


class ExecutionState(StrEnum):
    """Lifecycle of a single recovery action attempt."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    ROLLED_BACK = "rolled_back"
    SKIPPED = "skipped"


class ActorType(StrEnum):
    HUMAN = "human"
    SYSTEM = "system"
    AGENT = "agent"


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


class ModelCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    provider: str = Field(default="custom", min_length=1, max_length=80)
    environment: str = Field(default="production", min_length=1, max_length=40)


class ModelResponse(ModelCreate):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime


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


class ModelVersionCreate(BaseModel):
    """The controlled inputs whose stability makes a comparison valid."""

    label: str = Field(min_length=1, max_length=120)
    model_identifier: str = Field(min_length=1, max_length=160)
    prompt_version: str = Field(default="v1", max_length=80)
    config_hash: str = Field(default="", max_length=64)
    tool_set_hash: str = Field(default="", max_length=64)
    corpus_version: str | None = Field(default=None, max_length=80)
    evaluation_policy_version: str = Field(default="eval-v1", max_length=40)


class ModelVersionResponse(ModelVersionCreate):
    model_config = ConfigDict(from_attributes=True)

    id: str
    model_id: str
    fingerprint: str
    active_from: datetime
    active_to: datetime | None = None


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
    rolled_back_at: datetime | None = None


class VerificationRunResponse(BaseModel):
    """What "recovered" was judged against, recorded with the verdict."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    plan_id: str
    incident_id: str | None = None
    snapshot_id: str | None = None
    required_requests: int
    observed_requests: int
    threshold: float
    baseline_score: float | None = None
    post_score: float | None = None
    passed: bool | None = None
    no_regression_checks: list[dict[str, object]] = Field(default_factory=list)
    window_start: datetime | None = None
    window_end: datetime | None = None
    started_at: datetime
    finished_at: datetime | None = None


class RecoveryPlanResponse(BaseModel):
    id: str
    model_id: str
    diagnosis_id: str
    incident_id: str | None = None
    state: RecoveryState
    risk: RiskLevel
    actions: list[RecoveryAction]
    simulation: bool
    created_at: datetime
    approved_at: datetime | None = None
    approved_by: str | None = None
    executed_at: datetime | None = None
    verified_at: datetime | None = None
    executions: list[RecoveryExecutionResponse] = Field(default_factory=list)
    verification: VerificationRunResponse | None = None


class AlertRuleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    metric: str = Field(default="score", max_length=80)
    comparator: Comparator = Comparator.LT
    threshold: float
    window_minutes: int = Field(default=15, ge=1)
    cooldown_minutes: int = Field(default=30, ge=0)
    severity: Severity = Severity.MEDIUM
    channel: str = Field(default="in_app", max_length=40)
    is_enabled: bool = True


class AlertRuleResponse(AlertRuleCreate):
    model_config = ConfigDict(from_attributes=True)

    id: str
    model_id: str
    created_at: datetime


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
    fired_at: datetime
    acknowledged_at: datetime | None = None
    acknowledged_by: str | None = None
    resolved_at: datetime | None = None


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


class AuditEventResponse(BaseModel):
    id: str
    model_id: str
    event_type: str
    actor: str
    details: dict[str, object]
    created_at: datetime


class DemoResetResponse(BaseModel):
    model: ModelResponse
    health: HealthTimelineResponse
    diagnosis: DiagnosisResponse
    recovery: RecoveryPlanResponse
    incident: IncidentResponse | None = None
