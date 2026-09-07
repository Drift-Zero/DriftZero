"""Validated API contracts shared by DriftZero services and routes."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

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


class VerificationSourceType(StrEnum):
    """How a trusted source was supplied by the application owner."""

    PDF = "pdf"
    JSON = "json"
    CSV = "csv"
    TEXT = "text"
    MARKDOWN = "markdown"
    WEBSITE = "website"
    DEMO = "demo"


class VerificationSourceStatus(StrEnum):
    """Approval lifecycle. Only ``APPROVED`` sources may verify a claim."""

    AWAITING_REVIEW = "awaiting_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    RETIRED = "retired"


class ClaimType(StrEnum):
    POLICY = "policy"
    PRICE = "price"
    INVENTORY = "inventory"
    SPECIFICATION = "specification"
    DATE = "date"
    IDENTITY = "identity"
    EVENT = "event"
    PREDICTION = "prediction"
    OTHER = "other"


class ClaimImportance(StrEnum):
    """Weighting for a claim's contribution to groundedness."""

    CENTRAL = "central"
    SUPPORTING = "supporting"
    MINOR = "minor"


class ClaimVerdictValue(StrEnum):
    """A claim's status against approved evidence.

    ``INSUFFICIENT_EVIDENCE`` is deliberately distinct from ``CONTRADICTED``:
    absent evidence is not a confirmed hallucination and must never be
    reported as one.
    """

    SUPPORTED = "supported"
    CONTRADICTED = "contradicted"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    NOT_VERIFIABLE = "not_verifiable"
    NOT_APPLICABLE = "not_applicable"


class EvaluationRunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class VerificationMethod(StrEnum):
    """Which mechanism produced a verdict, surfaced to the operator."""

    DETERMINISTIC = "deterministic"
    LLM_VERIFIER = "llm_verifier"
    NO_EVIDENCE = "no_evidence"


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


class ConnectionKind(StrEnum):
    """Ways a monitored AI system can be connected to DriftZero."""

    GITHUB = "github"
    TELEMETRY = "telemetry"
    API = "api"
    WEBSITE = "website"


class ConnectionStatus(StrEnum):
    CONFIGURED = "configured"
    CONNECTED = "connected"
    ERROR = "error"
    NEEDS_SETUP = "needs_setup"
    PAUSED = "paused"


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
    evaluation_policy_version: str = Field(default="health-v2", min_length=1, max_length=40)
    actor: str = Field(default="system", min_length=1, max_length=120)


class ModelCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    provider: str = Field(default="custom", min_length=1, max_length=80)
    environment: str = Field(default="production", min_length=1, max_length=40)
    description: str | None = Field(default=None, max_length=2000)
    retention_days: int = Field(default=30, ge=1, le=3650)
    initial_version: ModelVersionCreate | None = None
    actor: str = Field(default="system", min_length=1, max_length=120)


class ConnectionCreate(BaseModel):
    """A connection descriptor; credentials are encrypted and never returned."""

    kind: ConnectionKind
    name: str = Field(min_length=1, max_length=120)
    url: str | None = Field(default=None, max_length=2000)
    repository: str | None = Field(default=None, max_length=240)
    branch: str | None = Field(default=None, max_length=160)
    api_endpoint: str | None = Field(default=None, max_length=2000)
    auth_scheme: str | None = Field(default=None, max_length=40)
    api_key: SecretStr | None = None
    config: dict[str, object] = Field(default_factory=dict)
    actor: str = Field(default="system", min_length=1, max_length=120)

    @model_validator(mode="after")
    def validate_target(self) -> ConnectionCreate:
        if self.kind is ConnectionKind.GITHUB and not (self.repository or self.url):
            raise ValueError("GitHub connections require a repository or URL.")
        if self.kind is ConnectionKind.API and not self.api_endpoint:
            raise ValueError("API connections require api_endpoint.")
        if self.kind is ConnectionKind.WEBSITE and not self.url:
            raise ValueError("Website connections require url.")
        if self.kind is ConnectionKind.TELEMETRY and not self.url and not self.config:
            self.url = "/api/v1/models/{model_id}/telemetry"
        return self


class ConnectionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    model_id: str
    kind: ConnectionKind
    name: str
    url: str | None
    repository: str | None
    branch: str | None
    api_endpoint: str | None
    auth_scheme: str | None
    credential_configured: bool
    status: ConnectionStatus
    config: dict[str, object]
    discovered_metadata: dict[str, object]
    last_status_code: int | None
    last_latency_ms: int | None
    last_error: str | None
    last_checked_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ConnectionCreatedResponse(ConnectionResponse):
    """Creation response; a telemetry key appears exactly once."""

    ingestion_key: str | None = None


class ConnectionCheckResponse(BaseModel):
    connection: ConnectionResponse
    healthy: bool


class ConnectionUpdate(BaseModel):
    status: Literal["configured", "paused"] | None = None
    api_key: SecretStr | None = None
    config: dict[str, object] | None = None
    actor: str = Field(default="system", min_length=1, max_length=120)

    @model_validator(mode="after")
    def require_change(self) -> ConnectionUpdate:
        if not any(field in self.model_fields_set for field in ("status", "api_key", "config")):
            raise ValueError("At least one connection field must be supplied.")
        return self


EvidenceSourceState = Literal["awaiting_review", "approved", "rejected", "retired"]


class EvidenceImportRequest(BaseModel):
    """Base64 transport keeps file ingestion dependency-free at the HTTP boundary."""

    filename: str = Field(min_length=1, max_length=255)
    name: str | None = Field(default=None, min_length=1, max_length=160)
    media_type: str | None = Field(default=None, max_length=100)
    content_base64: str = Field(min_length=1)
    use_llm: bool = False
    actor: str = Field(default="system", min_length=1, max_length=120)


class EvidenceChunkResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    source_id: str
    ordinal: int
    text: str
    evidence_quote: str
    locator: dict[str, object]
    content_hash: str
    validation_status: Literal["deterministic", "exact_match"]
    created_at: datetime


class EvidenceSourceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    model_id: str
    name: str
    filename: str
    media_type: str
    content_hash: str
    corpus_version: str
    status: EvidenceSourceState
    extraction_method: str
    llm_provider: str | None
    llm_model: str | None
    chunk_count: int
    approved_by: str | None
    approved_at: datetime | None
    rejection_reason: str | None
    created_at: datetime
    updated_at: datetime
    chunks: list[EvidenceChunkResponse] = Field(default_factory=list)


class EvidenceReviewRequest(BaseModel):
    status: Literal["approved", "rejected", "retired"]
    actor: str = Field(min_length=1, max_length=120)
    reason: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def require_rejection_reason(self) -> EvidenceReviewRequest:
        if self.status == "rejected" and not (self.reason or "").strip():
            raise ValueError("Rejected evidence requires a reason.")
        return self


class EvidenceSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    limit: int = Field(default=5, ge=1, le=20)


class WebsiteRefreshRequest(BaseModel):
    actor: str = Field(default="website-operator", min_length=1, max_length=120)


class WebsiteRefreshResponse(BaseModel):
    connection_id: str
    status: Literal["updated", "unchanged"]
    source_id: str | None
    fetched_at: datetime
    content_hash: str
    fact_count: int
    message: str


class AutomatedEvaluationRequest(BaseModel):
    """Controls for a source-generated black-box model health check."""

    max_questions: int = Field(default=20, ge=1, le=50)
    variants_per_fact: int = Field(default=4, ge=2, le=5)
    latency_best_ms: int = Field(default=200, ge=0, le=300_000)
    latency_worst_ms: int = Field(default=2000, ge=1, le=300_000)
    actor: str = Field(default="system", min_length=1, max_length=120)

    @model_validator(mode="after")
    def validate_latency_range(self) -> AutomatedEvaluationRequest:
        if self.latency_worst_ms <= self.latency_best_ms:
            raise ValueError("latency_worst_ms must be greater than latency_best_ms")
        return self


class AutomatedEvaluationCaseResponse(BaseModel):
    question: str
    expected: str
    actual: str
    passed: bool
    failure_reason: str | None
    field: str
    source_id: str
    source_name: str
    locator: dict[str, object]
    latency_ms: int


class AutomatedEvaluationResponse(BaseModel):
    model_id: str
    connection: str
    generated_questions: int
    passed_questions: int
    failed_questions: int
    pass_rate: Score
    dimensions: DimensionScores
    health_score: Score | None
    health_state: HealthState
    confidence: float = Field(ge=0, le=1)
    message: str
    formula: str
    cases: list[AutomatedEvaluationCaseResponse]
    snapshot: HealthSnapshotResponse


class EvidenceSearchHit(BaseModel):
    chunk_id: str
    source_id: str
    source_name: str
    filename: str
    corpus_version: str
    text: str
    evidence_quote: str
    locator: dict[str, object]
    relevance: float = Field(ge=0, le=1)


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
    connection_kinds: list[ConnectionKind] = Field(default_factory=list)
    connected_connections: int = 0
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
    event_id: str | None = Field(
        default=None,
        min_length=8,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )
    schema_version: Literal["1.0"] = "1.0"
    observed_at: datetime = Field(default_factory=utc_now)
    dimensions: DimensionScores
    sample_size: int = Field(ge=1)
    coverage: float = Field(ge=0, le=1)
    source: SignalSource = SignalSource.OBSERVED
    traces: list[TraceCreate] = Field(default_factory=list)


class ShopAssistTelemetryCreate(TelemetryCreate):
    """A server-side ShopAssist telemetry window.

    The route resolves the demo model on the server, so clients never choose a
    model ID or write directly to storage. The service also enforces the demo's
    minimum evidence gate before accepting the window.
    """


class HealthSnapshotResponse(BaseModel):
    id: str
    model_id: str
    event_id: str | None = None
    schema_version: str = "1.0"
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


class GroqModelCatalogResponse(BaseModel):
    """Models visible to the server-owned Groq credential."""

    models: list[str]


class GroqModelImportRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    model_identifier: str = Field(min_length=1, max_length=160)
    environment: str = Field(default="development", min_length=1, max_length=40)
    description: str | None = Field(default=None, max_length=2000)
    prompt_version: str = Field(default="prompt-v1", min_length=1, max_length=80)
    actor: str = Field(default="system", min_length=1, max_length=120)


class GroqEvaluationProfileInput(BaseModel):
    """Declared evidence and limits used by deterministic calculations."""

    expected_terms: list[str] = Field(default_factory=list, max_length=100)
    trusted_facts: list[str] = Field(default_factory=list, max_length=100)
    forbidden_terms: list[str] = Field(default_factory=list, max_length=100)
    expected_json: bool = False
    feedback_score: float | None = Field(default=None, ge=0, le=100)
    latency_best_ms: int = Field(default=200, ge=0, le=300_000)
    latency_worst_ms: int = Field(default=2000, ge=1, le=300_000)
    cost_max_usd: float | None = Field(default=None, gt=0)
    input_cost_per_million: float = Field(default=0.0, ge=0)
    output_cost_per_million: float = Field(default=0.0, ge=0)

    @model_validator(mode="after")
    def validate_latency_range(self) -> GroqEvaluationProfileInput:
        if self.latency_worst_ms <= self.latency_best_ms:
            raise ValueError("latency_worst_ms must be greater than latency_best_ms")
        return self


class GroqEvaluationRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=32_000)
    repeat: int = Field(default=1, ge=1, le=20)
    temperature: float = Field(default=0.0, ge=0, le=2)
    profile: GroqEvaluationProfileInput = Field(default_factory=GroqEvaluationProfileInput)
    actor: str = Field(default="system", min_length=1, max_length=120)


class GroqCompletionResponse(BaseModel):
    text: str
    latency_ms: int
    input_tokens: int
    output_tokens: int


class GroqEvaluationResponse(BaseModel):
    model_id: str
    model_identifier: str
    responses: list[GroqCompletionResponse]
    dimensions: DimensionScores
    health_score: float | None
    confidence: float
    evidence: dict[str, object]
    formula: str
    snapshot: HealthSnapshotResponse


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
    timeout_seconds: int | None = None
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


class UserRegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: SecretStr = Field(min_length=12, max_length=128)
    display_name: str = Field(min_length=1, max_length=120)
    tenant_name: str = Field(min_length=1, max_length=120)


class UserLoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: SecretStr = Field(min_length=1, max_length=128)
    tenant_id: str | None = Field(default=None, min_length=36, max_length=36)


class AuthUserResponse(BaseModel):
    user_id: str
    email: str
    display_name: str
    tenant_id: str
    tenant_name: str
    role: ActorRole


class AuthSessionResponse(BaseModel):
    user: AuthUserResponse
    csrf_token: str
    expires_at: datetime


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


class RecoveryRollbackRequest(ActorRequest):
    idempotency_key: str = Field(min_length=8, max_length=120)
    expected_version: int | None = Field(default=None, ge=1)


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


class VerificationChunkResponse(BaseModel):
    """One retrievable passage, with the provenance an operator needs."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    text: str
    structured_facts: dict[str, object] = Field(default_factory=dict)
    sequence: int
    token_count: int


class CorpusVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    version: int
    content_hash: str
    effective_from: datetime | None = None
    imported_at: datetime
    approved_at: datetime | None = None
    approved_by: str | None = None
    retired_at: datetime | None = None
    source_metadata: dict[str, object] = Field(default_factory=dict)
    chunk_count: int = 0
    fact_count: int = 0


class VerificationSourceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    source_type: VerificationSourceType
    status: VerificationSourceStatus
    description: str | None = None
    original_filename: str | None = None
    source_url: str | None = None
    created_at: datetime
    created_by: str
    versions: list[CorpusVersionResponse] = Field(default_factory=list)


class VerificationSourceDecision(BaseModel):
    """Who is approving, rejecting or retiring, and why."""

    actor: str = Field(min_length=1, max_length=120)
    reason: str | None = Field(default=None, max_length=500)


class ClaimEvidenceResponse(BaseModel):
    chunk_id: str
    text: str
    score: float
    source_name: str
    version: int
    exact_fact_match: bool


class ClaimVerdictResponse(BaseModel):
    text: str
    claim_type: str
    importance: str
    verdict: ClaimVerdictValue
    method: VerificationMethod
    explanation: str
    evidence_chunk_id: str | None = None
    verifier_confidence: float | None = None
    evidence: list[ClaimEvidenceResponse] = Field(default_factory=list)


class GroundednessBreakdown(BaseModel):
    """Everything needed to re-derive the number, not just the number."""

    groundedness: float | None
    confirmed_hallucination_rate: float | None
    evidence_coverage: float | None
    supported_weight: int
    contradicted_weight: int
    insufficient_weight: int
    total_factual_weight: int
    central_contradiction: bool
    capped: bool
    formula: str
    verdict_counts: dict[str, int] = Field(default_factory=dict)


class QualityBreakdown(BaseModel):
    quality: float | None
    correctness: float | None
    correctness_confidence: str
    correctness_capped: bool
    components: dict[str, float | None] = Field(default_factory=dict)
    missing_components: list[str] = Field(default_factory=list)


class EvaluationRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    answer: str = Field(min_length=1, max_length=8000)
    trace_id: str | None = None


class EvaluationResponse(BaseModel):
    """A verification run and its complete reasoning chain."""

    id: str
    model_id: str
    status: EvaluationRunStatus
    evaluator_provider: str | None = None
    evaluator_model: str | None = None
    extractor_version: str
    verifier_version: str
    corpus_versions: list[str] = Field(default_factory=list)
    created_at: datetime
    completed_at: datetime | None = None
    error: str | None = None
    claims: list[ClaimVerdictResponse] = Field(default_factory=list)
    groundedness: GroundednessBreakdown | None = None
    quality: QualityBreakdown | None = None


class EvaluationSummaryResponse(BaseModel):
    """Window aggregate. Never a health score below the evidence gate."""

    model_id: str
    evaluated_interactions: int
    minimum_window: int
    meets_minimum: bool
    groundedness_mean: float | None = None
    groundedness_median: float | None = None
    groundedness_p10: float | None = None
    quality_mean: float | None = None
    quality_median: float | None = None
    quality_p10: float | None = None
    evidence_coverage_mean: float | None = None
    evaluator_error_rate: float = 0.0
    supported_claims: int = 0
    contradicted_claims: int = 0
    insufficient_claims: int = 0
    not_verifiable_claims: int = 0
