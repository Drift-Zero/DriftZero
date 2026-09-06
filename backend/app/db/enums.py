"""Enumerations used by the persistence layer.

The five vocabularies that appear on the wire — health state, signal source,
diagnosis status, recovery state, risk level — are imported from
``app.schemas`` so the database and the API contract share one definition. The
rest are internal to persistence and defined here.
"""

from __future__ import annotations

from enum import StrEnum

from app.schemas import (
    ActorType,
    DiagnosisStatus,
    ExecutionState,
    HealthState,
    IncidentState,
    RecoveryState,
    RiskLevel,
    Severity,
    SignalSource,
    TraceStatus,
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


class FeedbackVerdict(StrEnum):
    AGREE = "agree"
    DISAGREE = "disagree"
    UNSURE = "unsure"
