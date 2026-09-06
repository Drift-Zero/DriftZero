"""Dedicated alert evaluator process for rules that must run without traffic."""

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
from app.schemas import AlertEvaluationRequest
from app.service import DriftZeroService


@dataclass(frozen=True, slots=True)
class WorkerSummary:
    evaluated_at: datetime
    models: int
    rules: int
    fired: int
    resolved: int
    failed_models: int


def evaluate_all_models(
    database: Database,
    service: DriftZeroService,
    *,
    evaluated_at: datetime | None = None,
) -> WorkerSummary:
    """Evaluate every active model while isolating one model's failure."""

    evaluated_at = evaluated_at or datetime.now(UTC)
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

    rules = 0
    fired = 0
    resolved = 0
    failed_models = 0
    logger = logging.getLogger("driftzero.alert_worker")
    for model_id in model_ids:
        with database.session_factory() as session:
            try:
                result = service.evaluate_alerts(
                    session,
                    model_id,
                    AlertEvaluationRequest(
                        actor="alerting-worker",
                        evaluated_at=evaluated_at,
                    ),
                )
            except Exception as exc:  # keep other tenants/models observable
                session.rollback()
                failed_models += 1
                logger.error(
                    "alert_evaluation.failed",
                    extra={
                        "event": "alert_evaluation.failed",
                        "model_id": model_id,
                        "error_type": type(exc).__name__,
                    },
                )
                continue
        rules += result.evaluated_rules
        fired += len(result.fired)
        resolved += len(result.resolved)

    return WorkerSummary(
        evaluated_at=evaluated_at,
        models=len(model_ids),
        rules=rules,
        fired=fired,
        resolved=resolved,
        failed_models=failed_models,
    )


def run_worker(
    settings: Settings,
    *,
    once: bool = False,
    stop_event: Event | None = None,
) -> None:
    """Run alert evaluation once or at the configured polling interval."""

    logger = configure_logging(settings)
    database = Database(settings.database_url)
    configure_database_logging(database.engine, slow_query_ms=settings.slow_query_ms)
    service = DriftZeroService(settings)
    stop = stop_event or Event()
    try:
        while not stop.is_set():
            summary = evaluate_all_models(database, service)
            logger.info(
                "alert_evaluation.completed",
                extra={
                    "event": "alert_evaluation.completed",
                    "evaluated_models": summary.models,
                    "evaluated_rules": summary.rules,
                    "alerts_fired": summary.fired,
                    "alerts_resolved": summary.resolved,
                    "failed_models": summary.failed_models,
                },
            )
            if once:
                break
            stop.wait(settings.alert_evaluation_interval_seconds)
    finally:
        database.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate DriftZero alert rules.")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Evaluate all active models once and exit.",
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
