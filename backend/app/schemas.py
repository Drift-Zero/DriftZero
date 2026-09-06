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


class ModelCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    provider: str = Field(default="custom", min_length=1, max_length=80)
    environment: str = Field(default="production", min_length=1, max_length=40)


class ModelResponse(ModelCreate):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime


class TelemetryCreate(BaseModel):
    observed_at: datetime = Field(default_factory=utc_now)
    dimensions: DimensionScores
    sample_size: int = Field(ge=1)
    coverage: float = Field(ge=0, le=1)
    source: SignalSource = SignalSource.OBSERVED


class HealthSnapshotResponse(BaseModel):
    id: str
    model_id: str
    observed_at: datetime
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


class DiagnosisResponse(BaseModel):
    id: str
    model_id: str
    snapshot_id: str
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
