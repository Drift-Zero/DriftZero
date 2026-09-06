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
    AlertState,
    DiagnosisStatus,
    EvaluatorKind,
    ExecutionState,
    FeedbackVerdict,
    HealthState,
    IncidentState,
    RecoveryState,
    ReviewState,
    RiskLevel,
    Severity,
    SignalSource,
    StabilityKind,
    StabilityVerdict,
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
