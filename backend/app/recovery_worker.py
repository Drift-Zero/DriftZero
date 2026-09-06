"""Durable worker for privileged recovery commands."""

from __future__ import annotations

import argparse
import logging
import signal
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import Event

from sqlalchemy import and_, or_, select

from app.config import Settings
from app.db import Database, RecoveryCommand
from app.observability import configure_database_logging, configure_logging
from app.schemas import (
    ActorRole,
    RecoveryCommandState,
    RecoveryCommandType,
    RecoveryExecuteRequest,
)
from app.service import DriftZeroService


@dataclass(frozen=True, slots=True)
class RecoveryWorkerSummary:
    processed: int
    succeeded: int
    failed: int


def _claim_next(database: Database, settings: Settings) -> str | None:
    """Atomically claim one ready command, including an abandoned lease."""

    now = datetime.now(UTC)
    with database.session_factory() as session:
        command = session.scalar(
            select(RecoveryCommand)
            .where(
                RecoveryCommand.available_at <= now,
                RecoveryCommand.attempt < RecoveryCommand.max_attempts,
                or_(
                    RecoveryCommand.state == RecoveryCommandState.PENDING.value,
                    and_(
                        RecoveryCommand.state == RecoveryCommandState.RUNNING.value,
                        RecoveryCommand.lease_expires_at < now,
                    ),
                ),
            )
            .order_by(RecoveryCommand.requested_at, RecoveryCommand.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if command is None:
            return None
        command.state = RecoveryCommandState.RUNNING.value
        command.attempt += 1
        command.claimed_at = now
        command.lease_expires_at = now + timedelta(
            seconds=settings.recovery_command_lease_seconds
        )
        command.error = None
        session.commit()
        return command.id


def _finish_command(
    database: Database,
    command_id: str,
    *,
    state: RecoveryCommandState,
    error: str | None = None,
) -> None:
    with database.session_factory() as session:
        command = session.get(RecoveryCommand, command_id)
        if command is None:
            return
        command.state = state.value
        command.error = error
        command.completed_at = datetime.now(UTC)
        command.lease_expires_at = None
        session.commit()


def process_recovery_commands(
    database: Database,
    service: DriftZeroService,
    *,
    limit: int = 10,
) -> RecoveryWorkerSummary:
    """Claim and process a bounded batch without losing failures."""

    processed = succeeded = failed = 0
    logger = logging.getLogger("driftzero.recovery_worker")
    for _ in range(limit):
        command_id = _claim_next(database, service.settings)
        if command_id is None:
            break
        processed += 1

        with database.session_factory() as session:
            command = session.get(RecoveryCommand, command_id)
            if command is None:
                continue
            command_type = RecoveryCommandType(command.command_type)
            payload = RecoveryExecuteRequest(
                actor=command.actor,
                role=ActorRole(command.actor_role),
                reason=command.reason,
                idempotency_key=command.idempotency_key,
                max_traffic_pct=command.max_traffic_pct,
            )
            plan_id = command.plan_id

        try:
            with database.session_factory() as session:
                if command_type is RecoveryCommandType.EXECUTE:
                    service.execute_recovery(session, plan_id, payload)
                else:
                    service.rollback_recovery(session, plan_id, payload)
            _finish_command(
                database,
                command_id,
                state=RecoveryCommandState.SUCCEEDED,
            )
            succeeded += 1
        except Exception as exc:  # command failure must not stop the queue
            _finish_command(
                database,
                command_id,
                state=RecoveryCommandState.FAILED,
                error=f"{type(exc).__name__}: {exc}",
            )
            failed += 1
            logger.exception(
                "recovery_command.failed",
                extra={
                    "event": "recovery_command.failed",
                    "command_id": command_id,
                    "plan_id": plan_id,
                },
            )

    return RecoveryWorkerSummary(processed=processed, succeeded=succeeded, failed=failed)


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
            summary = process_recovery_commands(database, service)
            if summary.processed:
                logger.info(
                    "recovery_commands.completed",
                    extra={
                        "event": "recovery_commands.completed",
                        "processed": summary.processed,
                        "succeeded": summary.succeeded,
                        "failed": summary.failed,
                    },
                )
            if once:
                break
            stop.wait(settings.recovery_worker_interval_seconds)
    finally:
        database.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Process queued DriftZero recoveries.")
    parser.add_argument("--once", action="store_true", help="Process one batch and exit.")
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
