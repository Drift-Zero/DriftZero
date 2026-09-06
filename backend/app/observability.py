"""Structured, correlated, and redacted operational observability."""

from __future__ import annotations

import json
import logging
import re
import sys
from contextvars import ContextVar, Token
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import uuid4

from fastapi import FastAPI
from sqlalchemy import event
from sqlalchemy.engine import Engine
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.config import Settings
from app.redaction import redact

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)

_SAFE_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_SECRET_VALUE = re.compile(
    r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+|"
    r"\b(sk|pk|api)[-_][A-Za-z0-9_-]{12,}\b|"
    r"((?:api[_-]?key|secret|password|token)\s*[=:]\s*)[^\s,;]+"
)
_SENSITIVE_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "cookie",
        "credential",
        "password",
        "secret",
        "set-cookie",
        "token",
    }
)
_LOG_FIELDS = (
    "event",
    "http_method",
    "http_route",
    "status_code",
    "duration_ms",
    "db_operation",
    "slow_query",
    "error_type",
    "model_id",
    "entity_type",
    "entity_id",
)


def get_request_id() -> str | None:
    return _request_id.get()


def get_correlation_id() -> str | None:
    return _correlation_id.get()


class JsonLogFormatter(logging.Formatter):
    """Emit one machine-readable event per line without request content."""

    def __init__(self, *, service_name: str, environment: str) -> None:
        super().__init__()
        self.service_name = service_name
        self.environment = environment

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname.lower(),
            "logger": record.name,
            "service": self.service_name,
            "environment": self.environment,
            "message": _sanitize_value(record.getMessage()),
        }
        request_id = getattr(record, "request_id", None) or get_request_id()
        correlation_id = getattr(record, "correlation_id", None) or get_correlation_id()
        if request_id:
            payload["request_id"] = request_id
        if correlation_id:
            payload["correlation_id"] = correlation_id
        for field in _LOG_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info:
            payload["exception"] = _sanitize_value(self.formatException(record.exc_info))
        return json.dumps(payload, separators=(",", ":"), default=str)


def configure_logging(settings: Settings) -> logging.Logger:
    """Configure DriftZero loggers for stdout and optional rotating files."""

    logger = logging.getLogger("driftzero")
    logger.disabled = False
    logger.setLevel(_log_level(settings.log_level))
    logger.propagate = False
    for name, candidate in logger.manager.loggerDict.items():
        if name.startswith("driftzero.") and isinstance(candidate, logging.Logger):
            candidate.disabled = False
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        handler.close()

    formatter = JsonLogFormatter(
        service_name=settings.otel_service_name,
        environment=settings.environment,
    )
    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(formatter)
    logger.addHandler(stream)

    if settings.log_file:
        log_path = Path(settings.log_file).expanduser().resolve()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        rotating = RotatingFileHandler(
            log_path,
            maxBytes=settings.log_file_max_bytes,
            backupCount=settings.log_file_backup_count,
            encoding="utf-8",
        )
        rotating.setFormatter(formatter)
        logger.addHandler(rotating)

    return logger


class RequestLoggingMiddleware:
    """Add correlation headers and log exactly one outcome per HTTP request."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.logger = logging.getLogger("driftzero.http")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        request_id = _header_identifier(headers.get(b"x-request-id")) or str(uuid4())
        correlation_id = _header_identifier(headers.get(b"x-correlation-id")) or request_id
        request_token = _request_id.set(request_id)
        correlation_token = _correlation_id.set(correlation_id)
        started = perf_counter()
        status_code = 500

        async def send_with_context(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                response_headers = list(message.get("headers", []))
                response_headers = [
                    (key, value)
                    for key, value in response_headers
                    if key.lower() not in {b"x-request-id", b"x-correlation-id"}
                ]
                response_headers.extend(
                    [
                        (b"x-request-id", request_id.encode("ascii")),
                        (b"x-correlation-id", correlation_id.encode("ascii")),
                    ]
                )
                message["headers"] = response_headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_context)
        except Exception as exc:
            self.logger.exception(
                "request.failed",
                extra=self._request_fields(scope, status_code, started, type(exc).__name__),
            )
            raise
        else:
            level = logging.WARNING if status_code >= 400 else logging.INFO
            self.logger.log(
                level,
                "request.completed",
                extra=self._request_fields(scope, status_code, started),
            )
        finally:
            _request_id.reset(request_token)
            _correlation_id.reset(correlation_token)

    @staticmethod
    def _request_fields(
        scope: Scope,
        status_code: int,
        started: float,
        error_type: str | None = None,
    ) -> dict[str, object]:
        route = scope.get("route")
        route_path = getattr(route, "path", None) or "<unmatched>"
        fields: dict[str, object] = {
            "event": "http.request",
            "request_id": get_request_id(),
            "correlation_id": get_correlation_id(),
            "http_method": scope.get("method", "UNKNOWN"),
            "http_route": route_path,
            "status_code": status_code,
            "duration_ms": round((perf_counter() - started) * 1000, 2),
        }
        if error_type:
            fields["error_type"] = error_type
        return fields


def configure_database_logging(engine: Engine, *, slow_query_ms: float) -> None:
    """Log query duration and failures without SQL text or bound parameters."""

    if getattr(engine, "_driftzero_logging_configured", False):
        return
    engine._driftzero_logging_configured = True
    logger = logging.getLogger("driftzero.database")

    def before_cursor_execute(
        _connection: Any,
        _cursor: Any,
        _statement: str,
        _parameters: Any,
        context: Any,
        _executemany: bool,
    ) -> None:
        context._driftzero_query_started = perf_counter()

    def after_cursor_execute(
        _connection: Any,
        _cursor: Any,
        statement: str,
        _parameters: Any,
        context: Any,
        _executemany: bool,
    ) -> None:
        started = getattr(context, "_driftzero_query_started", perf_counter())
        duration_ms = round((perf_counter() - started) * 1000, 2)
        slow = duration_ms >= slow_query_ms
        logger.log(
            logging.WARNING if slow else logging.DEBUG,
            "database.query",
            extra={
                "event": "database.query",
                "db_operation": _sql_operation(statement),
                "duration_ms": duration_ms,
                "slow_query": slow,
            },
        )

    def handle_error(context: Any) -> None:
        execution_context = context.execution_context
        started = getattr(execution_context, "_driftzero_query_started", perf_counter())
        logger.error(
            "database.error",
            extra={
                "event": "database.error",
                "db_operation": _sql_operation(context.statement),
                "duration_ms": round((perf_counter() - started) * 1000, 2),
                "error_type": type(context.original_exception).__name__,
            },
        )

    event.listen(engine, "before_cursor_execute", before_cursor_execute)
    event.listen(engine, "after_cursor_execute", after_cursor_execute)
    event.listen(engine, "handle_error", handle_error)


def configure_opentelemetry(app: FastAPI, engine: Engine, settings: Settings) -> bool:
    """Enable OTLP traces when the optional observability extra is installed."""

    if not settings.otel_enabled:
        return False
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        logging.getLogger("driftzero.observability").warning(
            "opentelemetry.unavailable",
            extra={"event": "opentelemetry.unavailable"},
        )
        return False

    provider = TracerProvider(
        resource=Resource.create({"service.name": settings.otel_service_name})
    )
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app)
    SQLAlchemyInstrumentor().instrument(engine=engine)
    return True


def _header_identifier(raw: bytes | None) -> str | None:
    if raw is None:
        return None
    try:
        value = raw.decode("ascii")
    except UnicodeDecodeError:
        return None
    return value if _SAFE_ID.fullmatch(value) else None


def _log_level(value: str) -> int:
    level = logging.getLevelName(value.strip().upper())
    return level if isinstance(level, int) else logging.INFO


def _sql_operation(statement: str | None) -> str:
    if not statement:
        return "UNKNOWN"
    first_word = statement.lstrip().split(maxsplit=1)
    return first_word[0].upper()[:20] if first_word else "UNKNOWN"


def _sanitize_value(value: object, *, key: str | None = None) -> object:
    if key and key.lower() in _SENSITIVE_KEYS:
        return "[redacted]"
    if isinstance(value, dict):
        return {
            str(item_key): _sanitize_value(item, key=str(item_key))
            for item_key, item in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        return [_sanitize_value(item) for item in value]
    if isinstance(value, str):
        masked = redact(value) or ""
        return _SECRET_VALUE.sub(_replace_secret, masked)
    return value


def _replace_secret(match: re.Match[str]) -> str:
    prefix = match.group(1) or match.group(3) or ""
    return f"{prefix}[redacted]"


def reset_request_context(
    request_token: Token[str | None],
    correlation_token: Token[str | None],
) -> None:
    """Test helper for code that binds context without ASGI middleware."""

    _request_id.reset(request_token)
    _correlation_id.reset(correlation_token)
