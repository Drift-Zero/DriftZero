"""Small persistence-layer helpers.

Deliberately narrow: business logic belongs in the service layer. These exist
because each one is easy to get subtly wrong against a schema this size.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.db.base import DEFAULT_TENANT_ID, DEFAULT_TENANT_SLUG, Base, utc_now
from app.db.enums import TraceStatus
from app.db.models import HealthPolicy, HealthSnapshot, MonitoredModel, Tenant, Trace


def ensure_default_tenant(session: Session) -> Tenant:
    """Return the single-tenant row, creating it if this is a fresh database.

    Schema bootstrap rather than demo data: every tenant-scoped row defaults to
    this id, so it has to exist before anything else can be inserted.
    """

    tenant = session.get(Tenant, DEFAULT_TENANT_ID)
    if tenant is None:
        tenant = Tenant(id=DEFAULT_TENANT_ID, slug=DEFAULT_TENANT_SLUG, name="Default")
        session.add(tenant)
        session.flush()
    return tenant


def snapshot_timeline(
    session: Session,
    model_id: str,
    *,
    limit: int = 50,
) -> list[tuple[datetime, float]]:
    """Return the most recent scored snapshots, oldest first.

    Shaped for :func:`app.scoring.forecast_health`, which expects ascending
    ``(observed_at, score)`` pairs. Snapshots without a score are excluded: an
    ``insufficient_data`` result must not be read as a health of zero.
    """

    rows = session.execute(
        sa.select(HealthSnapshot.observed_at, HealthSnapshot.score)
        .where(HealthSnapshot.model_id == model_id, HealthSnapshot.score.is_not(None))
        .order_by(HealthSnapshot.observed_at.desc())
        .limit(limit)
    ).all()
    return [(observed_at, float(score)) for observed_at, score in reversed(rows)]


def latest_snapshot(session: Session, model_id: str) -> HealthSnapshot | None:
    """Return the most recent snapshot for a model, scored or not."""

    return session.execute(
        sa.select(HealthSnapshot)
        .where(HealthSnapshot.model_id == model_id)
        .order_by(HealthSnapshot.observed_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def purge_expired_traces(
    session: Session,
    model: MonitoredModel,
    *,
    now: datetime | None = None,
) -> int:
    """Delete traces older than the model's retention window.

    Returns the number of rows removed. Retention is per model so a noisy demo
    system and a regulated one can differ.
    """

    cutoff = (now or utc_now()) - timedelta(days=model.retention_days)
    result = session.execute(
        sa.delete(Trace).where(Trace.model_id == model.id, Trace.occurred_at < cutoff)
    )
    return int(result.rowcount or 0)


def reset_all_data(session: Session, *, preserve: frozenset[str] = frozenset({"tenants"})) -> None:
    """Delete every row in foreign-key-safe order.

    Ordering comes from ``metadata.sorted_tables`` (dependencies first) reversed,
    so it stays correct as tables are added rather than drifting from a
    hand-maintained list. Callers seed afterwards; this writes no data of its own
    beyond re-creating the default tenant.
    """

    for table in reversed(Base.metadata.sorted_tables):
        if table.name not in preserve:
            session.execute(sa.delete(table))
    session.flush()
    ensure_default_tenant(session)


def ensure_health_policy(
    session: Session,
    *,
    version: str,
    weights: dict[str, float],
    thresholds: dict[str, float],
    minimum_sample_size: int,
    minimum_coverage: float,
) -> HealthPolicy:
    """Upsert the scoring policy a snapshot was scored under.

    A score is meaningless without the weights and gates behind it, so the
    policy is persisted rather than left implicit in the scoring module. Weights
    are refreshed on every call so the stored row cannot drift from the code
    that is actually scoring.
    """

    policy = session.scalar(sa.select(HealthPolicy).where(HealthPolicy.version == version))
    if policy is None:
        policy = HealthPolicy(version=version)
        session.add(policy)

    policy.weights = dict(weights)
    policy.thresholds = dict(thresholds)
    policy.minimum_sample_size = minimum_sample_size
    policy.minimum_coverage = minimum_coverage
    policy.is_active = True
    session.flush()
    return policy


def traces_in_window(
    session: Session,
    model_id: str,
    start: datetime | None,
    end: datetime | None,
) -> list[Trace]:
    """Return the traces a snapshot's evaluation window covers, oldest first."""

    statement = sa.select(Trace).where(Trace.model_id == model_id)
    if start is not None:
        statement = statement.where(Trace.occurred_at >= start)
    if end is not None:
        statement = statement.where(Trace.occurred_at <= end)
    return list(session.scalars(statement.order_by(Trace.occurred_at)).all())


def baseline_traces_before(
    session: Session,
    model_id: str,
    *,
    before: datetime,
    span: timedelta,
) -> list[Trace]:
    """Return the traces immediately preceding ``before``, for drift comparison.

    The lookback is the same length as the window being scored, so the two
    populations being compared are drawn from equal-sized periods rather than
    one window swamping the other.
    """

    statement = sa.select(Trace).where(
        Trace.model_id == model_id,
        Trace.occurred_at < before,
        Trace.occurred_at >= before - span,
    )
    return list(session.scalars(statement.order_by(Trace.occurred_at)).all())


# Evidence metrics are health dimension names. Each maps to the ordering that
# surfaces the requests actually demonstrating that metric, so a claim about
# groundedness drills down to unsupported answers rather than an arbitrary
# sample of traffic.
_METRIC_ORDERING: dict[str, tuple[sa.UnaryExpression, ...]] = {
    "groundedness": (
        Trace.unsupported_claim_count.desc(),
        Trace.groundedness_score.asc().nulls_last(),
    ),
    "quality": (Trace.quality_score.asc().nulls_last(),),
    "semantic_stability": (Trace.unsupported_claim_count.desc(),),
    "temporal_stability": (Trace.unsupported_claim_count.desc(),),
    "drift": (Trace.unsupported_claim_count.desc(),),
    "latency": (Trace.latency_ms.desc().nulls_last(),),
    "reliability": (Trace.occurred_at.desc(),),
    "safety": (Trace.occurred_at.desc(),),
}

_DEFAULT_ORDERING = (
    Trace.groundedness_score.asc().nulls_last(),
    Trace.occurred_at.desc(),
)


def traces_for_metric(
    session: Session,
    model_id: str,
    *,
    metric: str,
    start: datetime | None,
    end: datetime | None,
    limit: int = 5,
) -> list[Trace]:
    """Return the traces that best demonstrate ``metric`` within a window.

    This is the drill-down path: a diagnosis says groundedness fell, and these
    are the requests where it fell.

    Safety is filtered in Python rather than SQL because testing a JSON array
    for emptiness has no portable spelling across SQLite and PostgreSQL, and a
    window holds few enough traces that it is not worth a dialect branch. An
    unflagged request is not evidence of a safety regression, so if nothing was
    flagged the evidence links to nothing.
    """

    statement = sa.select(Trace).where(Trace.model_id == model_id)
    if start is not None:
        statement = statement.where(Trace.occurred_at >= start)
    if end is not None:
        statement = statement.where(Trace.occurred_at <= end)

    if metric == "reliability":
        statement = statement.where(Trace.status != TraceStatus.OK)

    ordering = _METRIC_ORDERING.get(metric, _DEFAULT_ORDERING)
    statement = statement.order_by(*ordering)

    if metric == "safety":
        flagged = [trace for trace in session.scalars(statement).all() if trace.safety_flags]
        return flagged[:limit]

    return list(session.scalars(statement.limit(limit)).all())
