"""Refresh configured website evidence connections on their own schedules."""

from __future__ import annotations

import argparse
import logging
import signal
from datetime import UTC, datetime
from threading import Event

from sqlalchemy import select

from app.config import Settings
from app.database import Database
from app.db import ModelConnection
from app.evidence import EvidenceService, build_evidence_structurer
from app.observability import configure_database_logging, configure_logging
from app.website_sync import WebsiteSyncError, WebsiteSyncService, connection_is_due


def refresh_due_connections(database: Database, service: WebsiteSyncService) -> tuple[int, int]:
    now = datetime.now(UTC)
    with database.session_factory() as session:
        ids = list(
            session.scalars(
                select(ModelConnection.id).where(
                    ModelConnection.kind == "website",
                    ModelConnection.status != "paused",
                )
            ).all()
        )
    refreshed = failed = 0
    logger = logging.getLogger("driftzero.website_worker")
    for connection_id in ids:
        with database.session_factory() as session:
            connection = session.get(ModelConnection, connection_id)
            if connection is None or not connection_is_due(connection, now):
                continue
            session.info["tenant_id"] = connection.tenant_id
            try:
                service.refresh(session, connection_id)
                refreshed += 1
            except WebsiteSyncError as exc:
                failed += 1
                logger.warning(
                    "website_refresh.failed",
                    extra={
                        "event": "website_refresh.failed",
                        "connection_id": connection_id,
                        "error_type": type(exc).__name__,
                    },
                )
    return refreshed, failed


def run_worker(settings: Settings, *, once: bool = False, stop_event: Event | None = None) -> None:
    logger = configure_logging(settings)
    database = Database(settings.database_url)
    configure_database_logging(database.engine, slow_query_ms=settings.slow_query_ms)
    evidence = EvidenceService(settings, structurer=build_evidence_structurer(settings))
    service = WebsiteSyncService(settings, evidence)
    stop = stop_event or Event()
    try:
        while not stop.is_set():
            refreshed, failed = refresh_due_connections(database, service)
            logger.info(
                "website_refresh.completed",
                extra={
                    "event": "website_refresh.completed",
                    "refreshed_connections": refreshed,
                    "failed_connections": failed,
                },
            )
            if once:
                break
            stop.wait(settings.website_refresh_interval_seconds)
    finally:
        database.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh due website evidence connections.")
    parser.add_argument("--once", action="store_true")
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
