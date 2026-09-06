"""The DriftZero relational model.

Organised by product layer: fleet identity, the knowledge corpus, Pulse
(telemetry and health), Diagnose (incidents and evidence), Recover (plans,
executions and verification), the signature evaluations, and governance.

Two rules hold throughout:

* No raw prompt or response text is stored. Traces and stability tests keep a
  redacted rendering plus a content hash, tagged with the redaction policy that
  produced it.
* Every number a user sees can be traced back to the window, sample size,
  policy version and individual requests that produced it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import (
    Base,
    IdMixin,
    TenantMixin,
    enum_column,
    utc_now,
)
from app.db.enums import (
    ActorType,
    AlertState,
    DiagnosisStatus,
    EvaluatorKind,
    ExecutionState,
    FeedbackVerdict,
    HealthState,
    IncidentState,
    KnowledgeStatus,
    ModelStatus,
    RecoveryState,
    ReviewState,
    RiskLevel,
    Severity,
    SignalSource,
    StabilityKind,
    StabilityVerdict,
    TraceStatus,
)

# Enum column types. Each needs a distinct name per table so the CHECK
# constraints generated from the naming convention stay unique.
HEALTH_STATE = enum_column(HealthState, "health_state")
SIGNAL_SOURCE = enum_column(SignalSource, "signal_source")
DIAGNOSIS_STATUS = enum_column(DiagnosisStatus, "diagnosis_status")
RECOVERY_STATE = enum_column(RecoveryState, "recovery_state")
RISK_LEVEL = enum_column(RiskLevel, "risk_level")
APPROVAL_LEVEL = enum_column(RiskLevel, "approval_level")
MODEL_STATUS = enum_column(ModelStatus, "model_status")
KNOWLEDGE_STATUS = enum_column(KnowledgeStatus, "knowledge_status")
TRACE_STATUS = enum_column(TraceStatus, "trace_status")
SEVERITY = enum_column(Severity, "severity")
INCIDENT_STATE = enum_column(IncidentState, "incident_state")
EXECUTION_STATE = enum_column(ExecutionState, "execution_state")
EVALUATOR_KIND = enum_column(EvaluatorKind, "evaluator_kind")
STABILITY_KIND = enum_column(StabilityKind, "stability_kind")
STABILITY_VERDICT = enum_column(StabilityVerdict, "stability_verdict")
REVIEW_STATE = enum_column(ReviewState, "review_state")
ALERT_STATE = enum_column(AlertState, "alert_state")
ACTOR_TYPE = enum_column(ActorType, "actor_type")
FEEDBACK_VERDICT = enum_column(FeedbackVerdict, "feedback_verdict")

_MODEL_FK = "monitored_models.id"


# --------------------------------------------------------------------------- #
# Fleet and identity
# --------------------------------------------------------------------------- #


class Tenant(IdMixin, Base):
    """Owner of a fleet.

    Single-tenant deployments carry exactly one row. Every tenant-scoped table
    already references it, so becoming multi-tenant is a data change rather than
    a migration.
    """

    __tablename__ = "tenants"

    slug: Mapped[str] = mapped_column(sa.String(80), unique=True)
    name: Mapped[str] = mapped_column(sa.String(120))
    created_at: Mapped[datetime] = mapped_column(default=utc_now)

    models: Mapped[list[MonitoredModel]] = relationship(
        back_populates="tenant", cascade="all, delete-orphan", passive_deletes=True
    )


class MonitoredModel(IdMixin, TenantMixin, Base):
    """An AI system under observation."""

    __tablename__ = "monitored_models"
    __table_args__ = (
        sa.UniqueConstraint("tenant_id", "name", name="tenant_name"),
        sa.CheckConstraint("retention_days > 0", name="retention_positive"),
    )

    name: Mapped[str] = mapped_column(sa.String(120), index=True)
    provider: Mapped[str] = mapped_column(sa.String(80), default="custom")
    environment: Mapped[str] = mapped_column(sa.String(40), default="production")
    description: Mapped[str | None] = mapped_column(sa.Text())
    status: Mapped[ModelStatus] = mapped_column(MODEL_STATUS, default=ModelStatus.ACTIVE)
    retention_days: Mapped[int] = mapped_column(default=30)
    created_at: Mapped[datetime] = mapped_column(default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(default=utc_now, onupdate=utc_now)

    tenant: Mapped[Tenant] = relationship(back_populates="models")
    versions: Mapped[list[ModelVersion]] = relationship(
        back_populates="model", cascade="all, delete-orphan", passive_deletes=True
    )
    knowledge_sources: Mapped[list[KnowledgeSource]] = relationship(
        back_populates="model", cascade="all, delete-orphan", passive_deletes=True
    )
    traces: Mapped[list[Trace]] = relationship(
        back_populates="model", cascade="all, delete-orphan", passive_deletes=True
    )
    snapshots: Mapped[list[HealthSnapshot]] = relationship(
        back_populates="model", cascade="all, delete-orphan", passive_deletes=True
    )
    incidents: Mapped[list[Incident]] = relationship(
        back_populates="model", cascade="all, delete-orphan", passive_deletes=True
    )


class ModelVersion(IdMixin, Base):
    """A frozen description of everything that can change a model's answers.

    The Temporal Stability Test is only meaningful when the model, prompt,
    configuration, tools, retrieval corpus and evaluation policy are unchanged
    between runs. ``fingerprint`` is the hash of exactly those inputs, so a
    changed answer can be attributed to a changed input instead of being
    reported as unexplained drift.
    """

    __tablename__ = "model_versions"
    __table_args__ = (
        sa.UniqueConstraint("model_id", "fingerprint", name="model_fingerprint"),
    )

    model_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey(_MODEL_FK, ondelete="CASCADE"), index=True
    )
    label: Mapped[str] = mapped_column(sa.String(120))
    model_identifier: Mapped[str] = mapped_column(sa.String(160))
    prompt_version: Mapped[str] = mapped_column(sa.String(80))
    config_hash: Mapped[str] = mapped_column(sa.String(64))
    tool_set_hash: Mapped[str] = mapped_column(sa.String(64))
    corpus_version: Mapped[str | None] = mapped_column(sa.String(80))
    evaluation_policy_version: Mapped[str] = mapped_column(sa.String(40))
    fingerprint: Mapped[str] = mapped_column(sa.String(64), index=True)
    active_from: Mapped[datetime] = mapped_column(default=utc_now)
    active_to: Mapped[datetime | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(default=utc_now)

    model: Mapped[MonitoredModel] = relationship(back_populates="versions")

    def comparable_with(self, other: ModelVersion) -> bool:
        """Whether two runs may be compared without attributing input changes."""

        return self.fingerprint == other.fingerprint

    def differences(self, other: ModelVersion) -> dict[str, list[str]]:
        """Report which controlled inputs changed between two versions."""

        fields = (
            "model_identifier",
            "prompt_version",
            "config_hash",
            "tool_set_hash",
            "corpus_version",
            "evaluation_policy_version",
        )
        return {
            field: [getattr(self, field), getattr(other, field)]
            for field in fields
            if getattr(self, field) != getattr(other, field)
        }


# --------------------------------------------------------------------------- #
# Knowledge and retrieval
# --------------------------------------------------------------------------- #


class KnowledgeSource(IdMixin, Base):
    """A retrieval corpus or index backing a model's answers."""

    __tablename__ = "knowledge_sources"

    model_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey(_MODEL_FK, ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(sa.String(120))
    kind: Mapped[str] = mapped_column(sa.String(40), default="corpus")
    corpus_version: Mapped[str] = mapped_column(sa.String(80))
    status: Mapped[KnowledgeStatus] = mapped_column(
        KNOWLEDGE_STATUS, default=KnowledgeStatus.FRESH
    )
    document_count: Mapped[int] = mapped_column(default=0)
    last_refreshed_at: Mapped[datetime | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(default=utc_now, onupdate=utc_now)

    model: Mapped[MonitoredModel] = relationship(back_populates="knowledge_sources")
    documents: Mapped[list[KnowledgeDocument]] = relationship(
        back_populates="source", cascade="all, delete-orphan", passive_deletes=True
    )


class KnowledgeDocument(IdMixin, Base):
    """A single retrievable document.

    ``superseded_by_id`` is what turns "the retriever served stale documents"
    from an assertion into evidence: the superseding document exists, is newer,
    and was not the one returned.
    """

    __tablename__ = "knowledge_documents"
    __table_args__ = (
        sa.UniqueConstraint("source_id", "external_ref", name="source_external_ref"),
    )

    source_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("knowledge_sources.id", ondelete="CASCADE"), index=True
    )
    external_ref: Mapped[str] = mapped_column(sa.String(200))
    title: Mapped[str] = mapped_column(sa.String(300))
    content_hash: Mapped[str] = mapped_column(sa.String(64))
    published_at: Mapped[datetime | None] = mapped_column()
    indexed_at: Mapped[datetime | None] = mapped_column()
    is_stale: Mapped[bool] = mapped_column(default=False)
    superseded_by_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("knowledge_documents.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(default=utc_now)

    source: Mapped[KnowledgeSource] = relationship(back_populates="documents")
    superseded_by: Mapped[KnowledgeDocument | None] = relationship(
        remote_side="KnowledgeDocument.id"
    )


# --------------------------------------------------------------------------- #
# Pulse: telemetry and health
# --------------------------------------------------------------------------- #


class Trace(IdMixin, TenantMixin, Base):
    """One observed request/response interaction.

    This is the drill-down target for every claim the product makes. Prompt and
    response text is stored redacted, alongside a hash of the original so
    duplicate or replayed content can still be identified.
    """

    __tablename__ = "traces"
    __table_args__ = (
        sa.Index("ix_traces_model_occurred", "model_id", "occurred_at"),
        sa.CheckConstraint("latency_ms IS NULL OR latency_ms >= 0", name="latency_non_negative"),
    )

    model_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey(_MODEL_FK, ondelete="CASCADE"), index=True
    )
    model_version_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("model_versions.id", ondelete="SET NULL"), index=True
    )
    occurred_at: Mapped[datetime] = mapped_column(index=True)
    request_id: Mapped[str | None] = mapped_column(sa.String(120), index=True)

    question_redacted: Mapped[str | None] = mapped_column(sa.Text())
    answer_redacted: Mapped[str | None] = mapped_column(sa.Text())
    prompt_hash: Mapped[str | None] = mapped_column(sa.String(64), index=True)
    answer_hash: Mapped[str | None] = mapped_column(sa.String(64))
    redaction_policy_version: Mapped[str] = mapped_column(sa.String(40), default="redact-v1")

    provider: Mapped[str | None] = mapped_column(sa.String(80))
    status: Mapped[TraceStatus] = mapped_column(TRACE_STATUS, default=TraceStatus.OK)
    error_code: Mapped[str | None] = mapped_column(sa.String(80))
    latency_ms: Mapped[int | None] = mapped_column()
    input_tokens: Mapped[int | None] = mapped_column()
    output_tokens: Mapped[int | None] = mapped_column()
    cost_usd: Mapped[float | None] = mapped_column()

    retrieved_document_ids: Mapped[list[str]] = mapped_column(default=list)
    citation_count: Mapped[int] = mapped_column(default=0)
    unsupported_claim_count: Mapped[int] = mapped_column(default=0)
    groundedness_score: Mapped[float | None] = mapped_column()
    quality_score: Mapped[float | None] = mapped_column()
    safety_flags: Mapped[list[str]] = mapped_column(default=list)

    is_simulated: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(default=utc_now)

    model: Mapped[MonitoredModel] = relationship(back_populates="traces")


class HealthPolicy(IdMixin, Base):
    """A versioned scoring policy.

    The weights and thresholds `app.scoring` applies are published here so the
    interface can show which policy produced a score, what it weighted, and what
    evidence it required. Without this, a score is a number with no definition.
    """

    __tablename__ = "health_policies"

    version: Mapped[str] = mapped_column(sa.String(40), unique=True)
    description: Mapped[str | None] = mapped_column(sa.Text())
    weights: Mapped[dict[str, Any]] = mapped_column(default=dict)
    thresholds: Mapped[dict[str, Any]] = mapped_column(default=dict)
    minimum_sample_size: Mapped[int] = mapped_column(default=20)
    minimum_coverage: Mapped[float] = mapped_column(default=0.30)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(default=utc_now)

    snapshots: Mapped[list[HealthSnapshot]] = relationship(back_populates="policy")


class HealthSnapshot(IdMixin, Base):
    """A health score computed over one evaluation window.

    Component dimensions are stored alongside the score so a number can always
    be decomposed, and ``window_start``/``window_end``, ``sample_size``,
    ``coverage`` and ``policy_version`` record the evidence it rests on.
    """

    __tablename__ = "health_snapshots"
    __table_args__ = (
        sa.Index("ix_health_snapshots_model_observed", "model_id", "observed_at"),
        sa.CheckConstraint("score IS NULL OR (score >= 0 AND score <= 100)", name="score_range"),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        sa.CheckConstraint("coverage >= 0 AND coverage <= 1", name="coverage_range"),
        sa.CheckConstraint("sample_size >= 0", name="sample_size_non_negative"),
    )

    model_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey(_MODEL_FK, ondelete="CASCADE"), index=True
    )
    observed_at: Mapped[datetime] = mapped_column(index=True)
    window_start: Mapped[datetime | None] = mapped_column()
    window_end: Mapped[datetime | None] = mapped_column()

    quality: Mapped[float | None] = mapped_column()
    groundedness: Mapped[float | None] = mapped_column()
    semantic_stability: Mapped[float | None] = mapped_column()
    temporal_stability: Mapped[float | None] = mapped_column()
    safety: Mapped[float | None] = mapped_column()
    drift: Mapped[float | None] = mapped_column()
    reliability: Mapped[float | None] = mapped_column()
    latency: Mapped[float | None] = mapped_column()
    cost: Mapped[float | None] = mapped_column()

    score: Mapped[float | None] = mapped_column()
    state: Mapped[HealthState] = mapped_column(HEALTH_STATE)
    confidence: Mapped[float] = mapped_column()
    sample_size: Mapped[int] = mapped_column()
    trace_count: Mapped[int] = mapped_column(default=0)
    coverage: Mapped[float] = mapped_column()
    policy_version: Mapped[str] = mapped_column(sa.String(40))
    policy_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("health_policies.id", ondelete="SET NULL")
    )
    source: Mapped[SignalSource] = mapped_column(SIGNAL_SOURCE)
    missing_dimensions: Mapped[list[str]] = mapped_column(default=list)
    created_at: Mapped[datetime] = mapped_column(default=utc_now)

    model: Mapped[MonitoredModel] = relationship(back_populates="snapshots")
    policy: Mapped[HealthPolicy | None] = relationship(back_populates="snapshots")
    forecasts: Mapped[list[HealthForecastRecord]] = relationship(
        back_populates="snapshot", cascade="all, delete-orphan", passive_deletes=True
    )


class HealthForecastRecord(IdMixin, Base):
    """A stored trajectory prediction and, later, what actually happened.

    Persisting forecasts is what allows the early-warning claim to be checked:
    ``actual_score`` is backfilled once the horizon elapses, so predictions can
    be scored for calibration instead of disappearing after they are rendered.
    """

    __tablename__ = "health_forecasts"
    __table_args__ = (
        sa.CheckConstraint(
            "predicted_score >= 0 AND predicted_score <= 100", name="predicted_range"
        ),
        sa.CheckConstraint("lower_bound <= upper_bound", name="bounds_ordered"),
    )

    model_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey(_MODEL_FK, ondelete="CASCADE"), index=True
    )
    snapshot_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("health_snapshots.id", ondelete="CASCADE"), index=True
    )
    horizon_minutes: Mapped[int] = mapped_column()
    predicted_score: Mapped[float] = mapped_column()
    lower_bound: Mapped[float] = mapped_column()
    upper_bound: Mapped[float] = mapped_column()
    change_per_hour: Mapped[float] = mapped_column()
    direction: Mapped[str] = mapped_column(sa.String(20))
    method: Mapped[str] = mapped_column(sa.String(40), default="recent_slope_v1")
    target_at: Mapped[datetime | None] = mapped_column()
    actual_score: Mapped[float | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(default=utc_now)

    snapshot: Mapped[HealthSnapshot] = relationship(back_populates="forecasts")


# --------------------------------------------------------------------------- #
# Diagnose: incidents and evidence
# --------------------------------------------------------------------------- #


class Incident(IdMixin, Base):
    """A period of degradation, from first detection to verified recovery.

    Diagnoses, recovery plans and verification runs all hang off an incident, so
    the fleet view can show recent incidents and a single incident can be told
    as one story.
    """

    __tablename__ = "incidents"
    __table_args__ = (sa.Index("ix_incidents_model_opened", "model_id", "opened_at"),)

    model_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey(_MODEL_FK, ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(sa.String(200))
    state: Mapped[IncidentState] = mapped_column(INCIDENT_STATE, default=IncidentState.OPEN)
    severity: Mapped[Severity] = mapped_column(SEVERITY, default=Severity.MEDIUM)
    opened_at: Mapped[datetime] = mapped_column(default=utc_now, index=True)
    closed_at: Mapped[datetime | None] = mapped_column()
    opening_snapshot_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("health_snapshots.id", ondelete="SET NULL")
    )
    closing_snapshot_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("health_snapshots.id", ondelete="SET NULL")
    )
    baseline_score: Mapped[float | None] = mapped_column()
    trough_score: Mapped[float | None] = mapped_column()
    summary: Mapped[str | None] = mapped_column(sa.Text())
    created_at: Mapped[datetime] = mapped_column(default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(default=utc_now, onupdate=utc_now)

    model: Mapped[MonitoredModel] = relationship(back_populates="incidents")
    diagnoses: Mapped[list[Diagnosis]] = relationship(
        back_populates="incident", cascade="all, delete-orphan", passive_deletes=True
    )
    recovery_plans: Mapped[list[RecoveryPlan]] = relationship(
        back_populates="incident", cascade="all, delete-orphan", passive_deletes=True
    )


class Diagnosis(IdMixin, Base):
    """One candidate root cause, ranked among alternatives.

    ``confidence`` is an estimate and is labelled as one; ``rank`` orders the
    candidates for a single incident. The ``evidence`` JSON column is retained
    for compatibility, but :class:`DiagnosisEvidence` rows are canonical because
    they can be queried and linked to traces.
    """

    __tablename__ = "diagnoses"
    __table_args__ = (
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        sa.CheckConstraint("rank >= 1", name="rank_positive"),
    )

    model_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey(_MODEL_FK, ondelete="CASCADE"), index=True
    )
    snapshot_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("health_snapshots.id", ondelete="CASCADE"), index=True
    )
    incident_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("incidents.id", ondelete="CASCADE"), index=True
    )
    evaluator_version_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("evaluator_versions.id", ondelete="SET NULL")
    )
    probable_cause: Mapped[str] = mapped_column(sa.String(120))
    taxonomy_code: Mapped[str] = mapped_column(sa.String(60), default="unknown", index=True)
    rank: Mapped[int] = mapped_column(default=1)
    confidence: Mapped[float] = mapped_column()
    confidence_label: Mapped[str] = mapped_column(sa.String(20), default="estimated")
    status: Mapped[DiagnosisStatus] = mapped_column(
        DIAGNOSIS_STATUS, default=DiagnosisStatus.OPEN
    )
    window_start: Mapped[datetime | None] = mapped_column()
    window_end: Mapped[datetime | None] = mapped_column()
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(default=list)
    created_at: Mapped[datetime] = mapped_column(default=utc_now)

    incident: Mapped[Incident | None] = relationship(back_populates="diagnoses")
    evidence_items: Mapped[list[DiagnosisEvidence]] = relationship(
        back_populates="diagnosis",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="DiagnosisEvidence.created_at",
    )
    recovery_plans: Mapped[list[RecoveryPlan]] = relationship(
        back_populates="diagnosis", cascade="all, delete-orphan", passive_deletes=True
    )


evidence_traces = sa.Table(
    "evidence_traces",
    Base.metadata,
    sa.Column(
        "evidence_id",
        sa.String(36),
        sa.ForeignKey("diagnosis_evidence.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    sa.Column(
        "trace_id",
        sa.String(36),
        sa.ForeignKey("traces.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    comment="Links a piece of evidence to the requests that demonstrate it.",
)


class DiagnosisEvidence(IdMixin, Base):
    """A single observation for or against a diagnosis.

    ``supports_diagnosis`` is deliberately not implied: contradicting evidence is
    stored and displayed alongside supporting evidence, and ``traces`` is the
    path from the claim down to the individual requests behind it.
    """

    __tablename__ = "diagnosis_evidence"

    diagnosis_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("diagnoses.id", ondelete="CASCADE"), index=True
    )
    reason_code: Mapped[str] = mapped_column(sa.String(60), index=True)
    metric: Mapped[str] = mapped_column(sa.String(80))
    summary: Mapped[str] = mapped_column(sa.Text())
    baseline_value: Mapped[float | None] = mapped_column()
    current_value: Mapped[float | None] = mapped_column()
    change: Mapped[float | None] = mapped_column()
    supports_diagnosis: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(default=utc_now)

    diagnosis: Mapped[Diagnosis] = relationship(back_populates="evidence_items")
    # The link table records which requests demonstrate this evidence, not a
    # ranking, so read them back in a stable chronological order rather than
    # whatever order the join happens to produce.
    traces: Mapped[list[Trace]] = relationship(
        secondary=evidence_traces, order_by="Trace.occurred_at"
    )


# --------------------------------------------------------------------------- #
# Recover: plans, execution and verification
# --------------------------------------------------------------------------- #


class RecoveryPlan(IdMixin, Base):
    """A recommended set of actions, and the approval state around them.

    Recommendation, approval, execution, verification and rollback are kept
    separate on purpose. This row covers recommendation and approval; execution
    lives on :class:`RecoveryExecution` and verification on
    :class:`VerificationRun`.
    """

    __tablename__ = "recovery_plans"
    __table_args__ = (
        sa.UniqueConstraint("idempotency_key", name="idempotency_key"),
    )

    model_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey(_MODEL_FK, ondelete="CASCADE"), index=True
    )
    diagnosis_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("diagnoses.id", ondelete="CASCADE"), index=True
    )
    incident_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("incidents.id", ondelete="CASCADE"), index=True
    )
    state: Mapped[RecoveryState] = mapped_column(
        RECOVERY_STATE, default=RecoveryState.RECOMMENDED, index=True
    )
    risk: Mapped[RiskLevel] = mapped_column(RISK_LEVEL)
    approval_level: Mapped[RiskLevel] = mapped_column(APPROVAL_LEVEL, default=RiskLevel.HIGH)
    requires_approval: Mapped[bool] = mapped_column(default=True)
    policy_version: Mapped[str] = mapped_column(sa.String(40), default="recovery-v1")
    idempotency_key: Mapped[str | None] = mapped_column(sa.String(120))
    actions: Mapped[list[dict[str, Any]]] = mapped_column(default=list)
    simulation: Mapped[bool] = mapped_column(default=True)
    failure_reason: Mapped[str | None] = mapped_column(sa.Text())

    created_at: Mapped[datetime] = mapped_column(default=utc_now)
    approved_at: Mapped[datetime | None] = mapped_column()
    approved_by: Mapped[str | None] = mapped_column(sa.String(120))
    rejected_at: Mapped[datetime | None] = mapped_column()
    rejected_by: Mapped[str | None] = mapped_column(sa.String(120))
    executed_at: Mapped[datetime | None] = mapped_column()
    verified_at: Mapped[datetime | None] = mapped_column()
    rolled_back_at: Mapped[datetime | None] = mapped_column()

    incident: Mapped[Incident | None] = relationship(back_populates="recovery_plans")
    diagnosis: Mapped[Diagnosis] = relationship(back_populates="recovery_plans")
    action_items: Mapped[list[RecoveryActionRecord]] = relationship(
        back_populates="plan",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="RecoveryActionRecord.order",
    )
    verification_runs: Mapped[list[VerificationRun]] = relationship(
        back_populates="plan", cascade="all, delete-orphan", passive_deletes=True
    )


class RecoveryActionRecord(IdMixin, Base):
    """One step of a playbook, bound to a provider-neutral adapter."""

    __tablename__ = "recovery_actions"
    __table_args__ = (
        sa.UniqueConstraint("plan_id", "order", name="plan_order"),
        sa.CheckConstraint('"order" >= 1', name="order_positive"),
    )

    plan_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("recovery_plans.id", ondelete="CASCADE"), index=True
    )
    order: Mapped[int] = mapped_column()
    code: Mapped[str] = mapped_column(sa.String(80), index=True)
    title: Mapped[str] = mapped_column(sa.String(200))
    description: Mapped[str] = mapped_column(sa.Text())
    risk: Mapped[RiskLevel] = mapped_column(RISK_LEVEL)
    reversible: Mapped[bool] = mapped_column(default=True)
    adapter: Mapped[str] = mapped_column(sa.String(80), default="simulated")
    params: Mapped[dict[str, Any]] = mapped_column(default=dict)
    is_simulated: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(default=utc_now)

    plan: Mapped[RecoveryPlan] = relationship(back_populates="action_items")
    executions: Mapped[list[RecoveryExecution]] = relationship(
        back_populates="action", cascade="all, delete-orphan", passive_deletes=True
    )


class RecoveryExecution(IdMixin, Base):
    """One attempt to apply one action.

    Per-action rows are what make partial failure, retries, timeouts and
    per-action rollback representable: a plan can have three actions succeed and
    one time out, and the record shows exactly that, including who initiated it
    and how much traffic it affected.
    """

    __tablename__ = "recovery_executions"
    __table_args__ = (
        sa.UniqueConstraint("action_id", "attempt", name="action_attempt"),
        sa.CheckConstraint("attempt >= 1", name="attempt_positive"),
        sa.CheckConstraint(
            "affected_traffic_pct IS NULL "
            "OR (affected_traffic_pct >= 0 AND affected_traffic_pct <= 100)",
            name="traffic_range",
        ),
    )

    action_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("recovery_actions.id", ondelete="CASCADE"), index=True
    )
    plan_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("recovery_plans.id", ondelete="CASCADE"), index=True
    )
    state: Mapped[ExecutionState] = mapped_column(
        EXECUTION_STATE, default=ExecutionState.PENDING, index=True
    )
    attempt: Mapped[int] = mapped_column(default=1)
    actor: Mapped[str] = mapped_column(sa.String(120))
    actor_type: Mapped[ActorType] = mapped_column(ACTOR_TYPE, default=ActorType.SYSTEM)
    reason: Mapped[str | None] = mapped_column(sa.Text())
    affected_traffic_pct: Mapped[float | None] = mapped_column()
    started_at: Mapped[datetime | None] = mapped_column()
    finished_at: Mapped[datetime | None] = mapped_column()
    timeout_seconds: Mapped[int | None] = mapped_column()
    result: Mapped[dict[str, Any]] = mapped_column(default=dict)
    error: Mapped[str | None] = mapped_column(sa.Text())
    rolled_back_at: Mapped[datetime | None] = mapped_column()
    rollback_result: Mapped[dict[str, Any]] = mapped_column(default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utc_now)

    action: Mapped[RecoveryActionRecord] = relationship(back_populates="executions")


class VerificationRun(IdMixin, Base):
    """The check that decides whether a recovery actually worked.

    Success is defined by all four of: a score threshold, an evaluation window, a
    required request count, and no-regression checks. Each has a column so the
    definition is recorded with the result rather than assumed.
    """

    __tablename__ = "verification_runs"
    __table_args__ = (
        sa.CheckConstraint("required_requests >= 1", name="required_requests_positive"),
    )

    plan_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("recovery_plans.id", ondelete="CASCADE"), index=True
    )
    incident_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("incidents.id", ondelete="CASCADE"), index=True
    )
    snapshot_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("health_snapshots.id", ondelete="SET NULL")
    )
    required_requests: Mapped[int] = mapped_column(default=50)
    observed_requests: Mapped[int] = mapped_column(default=0)
    threshold: Mapped[float] = mapped_column(default=80.0)
    baseline_score: Mapped[float | None] = mapped_column()
    post_score: Mapped[float | None] = mapped_column()
    passed: Mapped[bool | None] = mapped_column()
    no_regression_checks: Mapped[list[dict[str, Any]]] = mapped_column(default=list)
    window_start: Mapped[datetime | None] = mapped_column()
    window_end: Mapped[datetime | None] = mapped_column()
    started_at: Mapped[datetime] = mapped_column(default=utc_now)
    finished_at: Mapped[datetime | None] = mapped_column()

    plan: Mapped[RecoveryPlan] = relationship(back_populates="verification_runs")


class ReviewQueueItem(IdMixin, Base):
    """Work routed to a human, either by policy or by a recovery action."""

    __tablename__ = "review_queue_items"

    model_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey(_MODEL_FK, ondelete="CASCADE"), index=True
    )
    trace_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("traces.id", ondelete="CASCADE")
    )
    incident_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("incidents.id", ondelete="CASCADE")
    )
    reason: Mapped[str] = mapped_column(sa.String(200))
    state: Mapped[ReviewState] = mapped_column(
        REVIEW_STATE, default=ReviewState.PENDING, index=True
    )
    assigned_to: Mapped[str | None] = mapped_column(sa.String(120))
    decided_by: Mapped[str | None] = mapped_column(sa.String(120))
    decided_at: Mapped[datetime | None] = mapped_column()
    notes: Mapped[str | None] = mapped_column(sa.Text())
    created_at: Mapped[datetime] = mapped_column(default=utc_now, index=True)


# --------------------------------------------------------------------------- #
# Signature evaluations
# --------------------------------------------------------------------------- #


class EvaluatorVersion(IdMixin, Base):
    """A pinned evaluator configuration.

    Evaluator outputs are fallible, so every judgement records which evaluator
    produced it. Pinning the prompt hash and configuration is what makes a
    replay meaningful.
    """

    __tablename__ = "evaluator_versions"
    __table_args__ = (sa.UniqueConstraint("name", "version", name="name_version"),)

    name: Mapped[str] = mapped_column(sa.String(120))
    version: Mapped[str] = mapped_column(sa.String(40))
    kind: Mapped[EvaluatorKind] = mapped_column(EVALUATOR_KIND, index=True)
    provider: Mapped[str] = mapped_column(sa.String(80), default="simulated")
    model_identifier: Mapped[str | None] = mapped_column(sa.String(160))
    prompt_hash: Mapped[str | None] = mapped_column(sa.String(64))
    config: Mapped[dict[str, Any]] = mapped_column(default=dict)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(default=utc_now)


class StabilityTest(IdMixin, Base):
    """A semantic or temporal stability evaluation.

    For temporal tests, ``inputs_changed`` and ``changed_inputs`` record whether
    the controlled inputs held. When they did not, the result annotates the
    change instead of reporting unexplained drift.
    """

    __tablename__ = "stability_tests"
    __table_args__ = (
        sa.Index("ix_stability_tests_model_run", "model_id", "run_at"),
        sa.CheckConstraint(
            "stability_score IS NULL OR (stability_score >= 0 AND stability_score <= 100)",
            name="stability_score_range",
        ),
        sa.CheckConstraint(
            "evaluator_confidence IS NULL "
            "OR (evaluator_confidence >= 0 AND evaluator_confidence <= 1)",
            name="evaluator_confidence_range",
        ),
    )

    model_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey(_MODEL_FK, ondelete="CASCADE"), index=True
    )
    model_version_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("model_versions.id", ondelete="SET NULL")
    )
    baseline_version_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("model_versions.id", ondelete="SET NULL")
    )
    evaluator_version_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("evaluator_versions.id", ondelete="SET NULL")
    )
    kind: Mapped[StabilityKind] = mapped_column(STABILITY_KIND, index=True)
    question_redacted: Mapped[str] = mapped_column(sa.Text())
    question_hash: Mapped[str] = mapped_column(sa.String(64), index=True)
    stability_score: Mapped[float | None] = mapped_column()
    evaluator_confidence: Mapped[float | None] = mapped_column()
    verdict: Mapped[StabilityVerdict] = mapped_column(
        STABILITY_VERDICT, default=StabilityVerdict.INCONCLUSIVE
    )
    inputs_changed: Mapped[bool] = mapped_column(default=False)
    changed_inputs: Mapped[dict[str, Any]] = mapped_column(default=dict)
    run_at: Mapped[datetime] = mapped_column(default=utc_now, index=True)
    window_start: Mapped[datetime | None] = mapped_column()
    window_end: Mapped[datetime | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(default=utc_now)

    variants: Mapped[list[StabilityVariant]] = relationship(
        back_populates="test",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="StabilityVariant.variant_index",
    )
    claims: Mapped[list[StabilityClaim]] = relationship(
        back_populates="test", cascade="all, delete-orphan", passive_deletes=True
    )


class StabilityVariant(IdMixin, Base):
    """One paraphrase (semantic) or one re-run (temporal) within a test."""

    __tablename__ = "stability_variants"
    __table_args__ = (
        sa.UniqueConstraint("test_id", "variant_index", name="test_variant_index"),
    )

    test_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("stability_tests.id", ondelete="CASCADE"), index=True
    )
    trace_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("traces.id", ondelete="SET NULL")
    )
    variant_index: Mapped[int] = mapped_column()
    prompt_redacted: Mapped[str] = mapped_column(sa.Text())
    answer_redacted: Mapped[str | None] = mapped_column(sa.Text())
    is_baseline: Mapped[bool] = mapped_column(default=False)
    captured_at: Mapped[datetime] = mapped_column(default=utc_now)

    test: Mapped[StabilityTest] = relationship(back_populates="variants")
    claims: Mapped[list[StabilityClaim]] = relationship(
        back_populates="variant", cascade="all, delete-orphan", passive_deletes=True
    )


class StabilityClaim(IdMixin, Base):
    """A material fact extracted from one variant's answer.

    Stability is judged on whether these agree, not on whether the wording
    matched, so ``claim_key`` is the normalised fact being asserted and
    ``value_text`` is what this variant said about it.
    """

    __tablename__ = "stability_claims"

    test_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("stability_tests.id", ondelete="CASCADE"), index=True
    )
    variant_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("stability_variants.id", ondelete="CASCADE"), index=True
    )
    claim_key: Mapped[str] = mapped_column(sa.String(120), index=True)
    claim_text_redacted: Mapped[str] = mapped_column(sa.Text())
    value_text: Mapped[str | None] = mapped_column(sa.String(300))
    agrees_with_baseline: Mapped[bool | None] = mapped_column()
    disagreement_note: Mapped[str | None] = mapped_column(sa.Text())
    created_at: Mapped[datetime] = mapped_column(default=utc_now)

    test: Mapped[StabilityTest] = relationship(back_populates="claims")
    variant: Mapped[StabilityVariant] = relationship(back_populates="claims")


class EvaluationFeedback(IdMixin, Base):
    """Human agreement or disagreement with an automated judgement."""

    __tablename__ = "evaluation_feedback"
    __table_args__ = (
        sa.Index("ix_evaluation_feedback_target", "target_type", "target_id"),
    )

    target_type: Mapped[str] = mapped_column(sa.String(40))
    target_id: Mapped[str] = mapped_column(sa.String(36))
    actor: Mapped[str] = mapped_column(sa.String(120))
    verdict: Mapped[FeedbackVerdict] = mapped_column(FEEDBACK_VERDICT)
    note: Mapped[str | None] = mapped_column(sa.Text())
    created_at: Mapped[datetime] = mapped_column(default=utc_now)


# --------------------------------------------------------------------------- #
# Governance: audit and alerting
# --------------------------------------------------------------------------- #


class AuditEvent(IdMixin, TenantMixin, Base):
    """An append-only record of who did what, why, and to which entity."""

    __tablename__ = "audit_events"
    __table_args__ = (
        sa.Index("ix_audit_events_entity", "entity_type", "entity_id"),
        sa.Index("ix_audit_events_model_created", "model_id", "created_at"),
    )

    model_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey(_MODEL_FK, ondelete="CASCADE"), index=True
    )
    event_type: Mapped[str] = mapped_column(sa.String(80), index=True)
    actor: Mapped[str] = mapped_column(sa.String(120))
    actor_type: Mapped[ActorType] = mapped_column(ACTOR_TYPE, default=ActorType.SYSTEM)
    entity_type: Mapped[str | None] = mapped_column(sa.String(40))
    entity_id: Mapped[str | None] = mapped_column(sa.String(36))
    reason: Mapped[str | None] = mapped_column(sa.Text())
    request_id: Mapped[str | None] = mapped_column(sa.String(120))
    details: Mapped[dict[str, Any]] = mapped_column(default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utc_now, index=True)


class AlertRule(IdMixin, Base):
    """A threshold that turns a metric into an alert."""

    __tablename__ = "alert_rules"
    __table_args__ = (
        sa.UniqueConstraint("model_id", "name", name="model_name"),
        sa.CheckConstraint("window_minutes > 0", name="window_positive"),
    )

    model_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey(_MODEL_FK, ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(sa.String(120))
    metric: Mapped[str] = mapped_column(sa.String(80))
    comparator: Mapped[str] = mapped_column(sa.String(10), default="lt")
    threshold: Mapped[float] = mapped_column()
    window_minutes: Mapped[int] = mapped_column(default=15)
    cooldown_minutes: Mapped[int] = mapped_column(default=30)
    severity: Mapped[Severity] = mapped_column(SEVERITY, default=Severity.MEDIUM)
    channel: Mapped[str] = mapped_column(sa.String(40), default="in_app")
    is_enabled: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(default=utc_now)

    alerts: Mapped[list[Alert]] = relationship(
        back_populates="rule", cascade="all, delete-orphan", passive_deletes=True
    )


class Alert(IdMixin, Base):
    """A firing, acknowledged or resolved alert."""

    __tablename__ = "alerts"
    __table_args__ = (sa.Index("ix_alerts_model_fired", "model_id", "fired_at"),)

    rule_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("alert_rules.id", ondelete="CASCADE"), index=True
    )
    model_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey(_MODEL_FK, ondelete="CASCADE"), index=True
    )
    snapshot_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("health_snapshots.id", ondelete="SET NULL")
    )
    incident_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("incidents.id", ondelete="SET NULL")
    )
    state: Mapped[AlertState] = mapped_column(ALERT_STATE, default=AlertState.FIRING, index=True)
    severity: Mapped[Severity] = mapped_column(SEVERITY, default=Severity.MEDIUM)
    message: Mapped[str] = mapped_column(sa.Text())
    fired_at: Mapped[datetime] = mapped_column(default=utc_now, index=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column()
    acknowledged_by: Mapped[str | None] = mapped_column(sa.String(120))
    resolved_at: Mapped[datetime | None] = mapped_column()
    notified_at: Mapped[datetime | None] = mapped_column()

    rule: Mapped[AlertRule | None] = relationship(back_populates="alerts")
