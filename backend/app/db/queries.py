"""Small persistence-layer helpers.

Deliberately narrow: business logic belongs in the service layer. These exist
because each one is easy to get subtly wrong against a schema this size.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.db.base import DEFAULT_TENANT_ID, DEFAULT_TENANT_SLUG, Base, utc_now
from app.db.models import HealthSnapshot, MonitoredModel, Tenant, Trace


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
