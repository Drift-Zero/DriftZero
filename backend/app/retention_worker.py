"""Retention enforcement for stored request traces.

Traces hold redacted user traffic and grow faster than anything else in the
schema, and every model carries a `retention_days` the system did not previously
honour. This worker applies it.

Deliberately a separate process rather than part of the API lifespan, matching
`alert_worker`: deleting user data should not be a side effect of serving
traffic, and it has to be runnable on demand.
"""

from __future__ import annotations

import argparse
import logging
import signal
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Event

from sqlalchemy import select

from app.config import Settings
from app.db import DEFAULT_TENANT_ID, Database, ModelStatus, MonitoredModel
from app.observability import configure_database_logging, configure_logging
from app.service import DriftZeroService


@dataclass(frozen=True, slots=True)
class RetentionSummary:
    purged_at: datetime
    models: int
    removed_traces: int
    failed_models: int


def purge_all_models(
    database: Database,
    service: DriftZeroService,
    *,
    purged_at: datetime | None = None,
) -> RetentionSummary:
    """Apply each active model's retention window, isolating per-model failure."""

    purged_at = purged_at or datetime.now(UTC)
    with database.session_factory() as session:
        model_ids = list(
            session.scalars(
                select(MonitoredModel.id)
                .where(
                    MonitoredModel.tenant_id == DEFAULT_TENANT_ID,
                    MonitoredModel.status == ModelStatus.ACTIVE.value,
                )
                .order_by(MonitoredModel.id)
            ).all()
        )

    removed_traces = 0
    failed_models = 0
    logger = logging.getLogger("driftzero.retention_worker")
    for model_id in model_ids:
        with database.session_factory() as session:
            try:
                removed = service.purge_expired_traces(session, model_id)
            except Exception as exc:  # one model must not stop the rest
                session.rollback()
                failed_models += 1
                logger.error(
                    "retention.failed",
                    extra={
                        "event": "retention.failed",
                        "model_id": model_id,
                        "error_type": type(exc).__name__,
                    },
                )
                continue
        removed_traces += removed

    return RetentionSummary(
        purged_at=purged_at,
        models=len(model_ids),
        removed_traces=removed_traces,
        failed_models=failed_models,
    )


def run_worker(
    settings: Settings,
    *,
    once: bool = False,
    stop_event: Event | None = None,
) -> None:
    logger = configure_logging(settings)
    database = Database(settings.database_url)
    configure_database_logging(database.engine, slow_query_ms=settings.slow_query_ms)
    service = DriftZeroService(settings)
    stop = stop_event or Event()
    try:
        while not stop.is_set():
            summary = purge_all_models(database, service)
            logger.info(
                "retention.completed",
                extra={
                    "event": "retention.completed",
                    "evaluated_models": summary.models,
                    "removed_traces": summary.removed_traces,
                    "failed_models": summary.failed_models,
                },
            )
            if once:
                break
            stop.wait(settings.retention_interval_seconds)
    finally:
        database.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply DriftZero trace retention.")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Purge every active model once and exit.",
    )
    args = parser.parse_args()
    stop = Event()

    def request_stop(_signum: int, _frame: object) -> None:
        stop.set()

    signal.signal(signal.SIGINT, request_stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, request_stop)
    run_worker(Settings.from_env(), once=args.once, stop_event=stop)


if __name__ == "__main__":
    main()
