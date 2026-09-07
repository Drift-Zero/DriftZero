"""Refresh approved public evidence URLs without blocking API requests."""

from __future__ import annotations

import argparse
import signal
from threading import Event

from app.config import Settings
from app.database import Database
from app.evidence import EvidenceService, build_evidence_structurer
from app.observability import configure_database_logging, configure_logging


def run_worker(
    settings: Settings,
    *,
    once: bool = False,
    stop_event: Event | None = None,
) -> None:
    logger = configure_logging(settings)
    database = Database(settings.database_url)
    configure_database_logging(database.engine, slow_query_ms=settings.slow_query_ms)
    service = EvidenceService(
        settings,
        structurer=build_evidence_structurer(settings),
    )
    stop = stop_event or Event()
    try:
        while not stop.is_set():
            with database.session_factory() as session:
                summary = service.sync_due_sources(session)
            logger.info(
                "evidence_sync.completed",
                extra={"event": "evidence_sync.completed", **summary},
            )
            if once:
                break
            stop.wait(settings.evidence_sync_interval_seconds)
    finally:
        database.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh synchronized evidence URLs.")
    parser.add_argument("--once", action="store_true", help="Refresh due sources once and exit.")
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
