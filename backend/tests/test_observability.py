from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.config import Settings
from app.db import Database
from app.main import create_app
from app.observability import (
    JsonLogFormatter,
    configure_database_logging,
    configure_logging,
)


class CollectingHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def test_configure_logging_reenables_driftzero_namespace() -> None:
    parent = logging.getLogger("driftzero")
    child = logging.getLogger("driftzero.http")
    parent.disabled = True
    child.disabled = True

    configured = configure_logging(Settings(environment="test"))

    assert configured.disabled is False
    assert child.disabled is False


def test_request_logging_adds_safe_correlation_headers() -> None:
    app = create_app(Settings(database_url="sqlite://", environment="test"))
    handler = CollectingHandler()
    logger = logging.getLogger("driftzero.http")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        with TestClient(app) as client:
            response = client.get(
                "/healthz",
                headers={
                    "X-Request-ID": "request-123",
                    "X-Correlation-ID": "workflow:456",
                },
            )
    finally:
        logger.removeHandler(handler)

    assert response.headers["x-request-id"] == "request-123"
    assert response.headers["x-correlation-id"] == "workflow:456"
    completed = next(record for record in handler.records if record.msg == "request.completed")
    assert completed.http_method == "GET"
    assert completed.http_route == "/healthz"
    assert completed.status_code == 200
    assert completed.duration_ms >= 0
    assert completed.request_id == "request-123"
    assert completed.correlation_id == "workflow:456"


def test_invalid_request_identifier_is_not_reflected() -> None:
    app = create_app(Settings(database_url="sqlite://", environment="test"))
    with TestClient(app) as client:
        response = client.get(
            "/healthz",
            headers={"X-Request-ID": "unsafe identifier with spaces"},
        )

    assert response.status_code == 200
    assert response.headers["x-request-id"] != "unsafe identifier with spaces"
    assert len(response.headers["x-request-id"]) == 36


def test_audit_event_carries_request_and_entity_context() -> None:
    app = create_app(Settings(database_url="sqlite://", environment="test"))
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/models",
            headers={"X-Request-ID": "registration-123"},
            json={
                "name": "AuditModel",
                "provider": "custom",
                "actor": "owner@example.com",
            },
        )
        model_id = created.json()["id"]
        audit = client.get(f"/api/v1/models/{model_id}/audit")

    event = next(item for item in audit.json() if item["event_type"] == "model.created")
    assert event["request_id"] == "registration-123"
    assert event["actor_type"] == "human"
    assert event["entity_type"] == "model"
    assert event["entity_id"] == model_id


def test_database_logging_records_timing_without_sql_text() -> None:
    database = Database("sqlite://")
    configure_database_logging(database.engine, slow_query_ms=0)
    handler = CollectingHandler()
    logger = logging.getLogger("driftzero.database")
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    try:
        with database.engine.connect() as connection:
            connection.execute(text("SELECT 'private-value'"))
    finally:
        logger.removeHandler(handler)
        database.dispose()

    query = next(record for record in handler.records if record.msg == "database.query")
    assert query.db_operation == "SELECT"
    assert query.duration_ms >= 0
    assert query.slow_query is True
    assert not hasattr(query, "statement")
    assert "private-value" not in query.getMessage()


def test_json_formatter_redacts_identifiers_and_secrets() -> None:
    formatter = JsonLogFormatter(service_name="driftzero-api", environment="test")
    record = logging.LogRecord(
        name="driftzero.test",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg=(
            "Contact student@example.com with Bearer abcdefghijklmnop "
            "and password=hunter2"
        ),
        args=(),
        exc_info=None,
    )
    record.model_id = "12345678-1234-1234-1234-123456789012"

    payload = json.loads(formatter.format(record))

    datetime.fromisoformat(payload["timestamp"])
    assert payload["model_id"] == record.model_id
    assert "student@example.com" not in payload["message"]
    assert "abcdefghijklmnop" not in payload["message"]
    assert "hunter2" not in payload["message"]
    assert payload["message"].count("[redacted]") == 2
    assert "[email]" in payload["message"]


def test_optional_log_file_uses_json_and_rotation_settings(tmp_path: Path) -> None:
    log_file = tmp_path / "driftzero.jsonl"
    logger = configure_logging(
        Settings(
            environment="test",
            log_file=str(log_file),
            log_file_max_bytes=1024,
            log_file_backup_count=1,
        )
    )
    logger.info("file.logging.ready", extra={"event": "logging.test"})
    for handler in logger.handlers:
        handler.flush()

    payload = json.loads(log_file.read_text(encoding="utf-8").strip())
    assert payload["message"] == "file.logging.ready"
    assert payload["event"] == "logging.test"
    assert payload["environment"] == "test"
