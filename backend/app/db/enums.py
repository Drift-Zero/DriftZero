"""Enumerations used by the persistence layer.

The five vocabularies that appear on the wire — health state, signal source,
diagnosis status, recovery state, risk level — are imported from
``app.schemas`` so the database and the API contract share one definition. The
rest are internal to persistence and defined here.
"""

from __future__ import annotations

from enum import StrEnum

from app.schemas import (
    DiagnosisStatus,
    HealthState,
    RecoveryState,
    RiskLevel,
    SignalSource,
)

__all__ = [
    "ActorType",
    "AlertState",
    "DiagnosisStatus",
    "EvaluatorKind",
    "ExecutionState",
    "FeedbackVerdict",
    "HealthState",
    "IncidentState",
    "KnowledgeStatus",
    "ModelStatus",
    "RecoveryState",
    "ReviewState",
    "RiskLevel",
    "Severity",
    "SignalSource",
    "StabilityKind",
    "StabilityVerdict",
    "TraceStatus",
]


class ModelStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    RETIRED = "retired"


class KnowledgeStatus(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    DISABLED = "disabled"


class TraceStatus(StrEnum):
    OK = "ok"
    ERROR = "error"
    TIMEOUT = "timeout"
    FILTERED = "filtered"


class Severity(StrEnum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class IncidentState(StrEnum):
    OPEN = "open"
    DIAGNOSING = "diagnosing"
    MITIGATING = "mitigating"
    VERIFYING = "verifying"
    RESOLVED = "resolved"
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


class EvaluatorKind(StrEnum):
    QUALITY = "quality"
    GROUNDEDNESS = "groundedness"
    SAFETY = "safety"
    SEMANTIC_STABILITY = "semantic_stability"
    TEMPORAL_STABILITY = "temporal_stability"


class StabilityKind(StrEnum):
    SEMANTIC = "semantic"
    TEMPORAL = "temporal"


class StabilityVerdict(StrEnum):
    STABLE = "stable"
    DRIFTING = "drifting"
    CRITICAL = "critical"
    INCONCLUSIVE = "inconclusive"


class ReviewState(StrEnum):
    PENDING = "pending"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    REJECTED = "rejected"


class AlertState(StrEnum):
    FIRING = "firing"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


class ActorType(StrEnum):
    HUMAN = "human"
    SYSTEM = "system"
    AGENT = "agent"


class FeedbackVerdict(StrEnum):
    AGREE = "agree"
    DISAGREE = "disagree"
    UNSURE = "unsure"
