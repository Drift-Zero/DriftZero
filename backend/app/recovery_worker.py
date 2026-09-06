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
    RecoveryState,
)
from app.service import DriftZeroService


@dataclass(frozen=True, slots=True)
class RecoveryWorkerSummary:
    processed: int
    succeeded: int
    failed: int
    retried: int


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


def _retry_or_fail_command(
    database: Database,
    service: DriftZeroService,
    command_id: str,
    error: str,
) -> bool:
    """Schedule another idempotent attempt, or terminally fail the plan."""

    with database.session_factory() as session:
        command = session.get(RecoveryCommand, command_id)
        if command is None:
            return False
        if command.attempt < command.max_attempts:
            command.state = RecoveryCommandState.PENDING.value
            command.error = error
            command.available_at = datetime.now(UTC) + timedelta(
                seconds=min(60, 2 ** max(0, command.attempt - 1))
            )
            command.lease_expires_at = None
            session.commit()
            return True
        plan_id = command.plan_id

    _finish_command(
        database,
        command_id,
        state=RecoveryCommandState.FAILED,
        error=error,
    )
    with database.session_factory() as session:
        service.fail_recovery_after_retries(session, plan_id, error)
    return False


def process_recovery_commands(
    database: Database,
    service: DriftZeroService,
    *,
    limit: int = 10,
) -> RecoveryWorkerSummary:
    """Claim and process a bounded batch without losing failures."""

    processed = succeeded = failed = retried = 0
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
            recovery = None
            with database.session_factory() as session:
                if command_type is RecoveryCommandType.EXECUTE:
                    recovery = service.execute_recovery(session, plan_id, payload)
                elif command_type is RecoveryCommandType.ROLLBACK:
                    recovery = service.rollback_recovery(session, plan_id, payload)
                else:
                    if command.snapshot_id is None:
                        raise ValueError("Verification command is missing snapshot_id.")
                    recovery = service.verify_recovery(
                        session, plan_id, command.snapshot_id
                    )
            if recovery is not None and recovery.state is RecoveryState.FAILED:
                error = recovery.failure_reason or "Recovery verification failed."
                _finish_command(
                    database,
                    command_id,
                    state=RecoveryCommandState.FAILED,
                    error=error,
                )
                failed += 1
                continue
            _finish_command(
                database,
                command_id,
                state=RecoveryCommandState.SUCCEEDED,
            )
            succeeded += 1
        except Exception as exc:  # command failure must not stop the queue
            error = f"{type(exc).__name__}: {exc}"
            if _retry_or_fail_command(database, service, command_id, error):
                retried += 1
            else:
                failed += 1
            logger.exception(
                "recovery_command.failed",
                extra={
                    "event": "recovery_command.failed",
                    "command_id": command_id,
                    "plan_id": plan_id,
                },
            )

    return RecoveryWorkerSummary(
        processed=processed,
        succeeded=succeeded,
        failed=failed,
        retried=retried,
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
            summary = process_recovery_commands(database, service)
            if summary.processed:
                logger.info(
                    "recovery_commands.completed",
                    extra={
                        "event": "recovery_commands.completed",
                        "processed": summary.processed,
                        "succeeded": summary.succeeded,
                        "failed": summary.failed,
                        "retried": summary.retried,
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
