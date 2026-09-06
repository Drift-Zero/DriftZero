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


class ActorRequest(BaseModel):
    actor: str = Field(min_length=1, max_length=120)


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
