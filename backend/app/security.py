"""HTTP security boundary for the DriftZero control-plane API."""

from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass
from secrets import compare_digest
from threading import Lock

from fastapi import Request, Response, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.config import Settings
from app.schemas import ActorRole

_SAFE_ACTOR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9@._:+/-]{0,119}$")


class _RequestTooLarge(Exception):
    pass


class RequestBodyLimitMiddleware:
    """Enforce the body limit while streaming, including chunked requests."""

    def __init__(self, app: ASGIApp, *, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        header_response = self._content_length_rejection(scope)
        if header_response is not None:
            await header_response(scope, receive, send)
            return

        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise _RequestTooLarge
            return message

        try:
            await self.app(scope, limited_receive, send)
        except _RequestTooLarge:
            await self._too_large_response()(scope, receive, send)

    def _content_length_rejection(self, scope: Scope) -> Response | None:
        raw_value = next(
            (value for key, value in scope["headers"] if key == b"content-length"),
            None,
        )
        if raw_value is None:
            return None
        try:
            length = int(raw_value)
        except ValueError:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"error": "invalid_request", "detail": "Invalid Content-Length."},
            )
        return self._too_large_response() if length > self.max_bytes else None

    def _too_large_response(self) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            content={
                "error": "request_too_large",
                "detail": f"Request body exceeds the configured limit of {self.max_bytes} bytes.",
            },
        )


@dataclass(frozen=True, slots=True)
class SecurityPrincipal:
    """An identity established from a server-configured API credential."""

    actor: str
    role: ActorRole
    tenant_id: str
    credential_id: str


class SecurityMiddleware(BaseHTTPMiddleware):
    """Apply authentication, authorization, throttling, and browser defenses.

    The in-memory limiter protects a single demo process. A multi-instance
    deployment should additionally enforce a shared limit at its gateway.
    """

    def __init__(self, app: object, *, settings: Settings) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self.settings = settings
        self._rate_buckets: dict[str, tuple[int, float]] = {}
        self._rate_lock = Lock()

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        response = None
        if self._is_api_request(request):
            response = self._authenticate_api_request(request)
        if response is None and self._is_rate_limited(request):
            response = JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "error": "rate_limit_exceeded",
                    "detail": "Too many requests. Retry after the current minute window.",
                },
                headers={"Retry-After": "60"},
            )
        if response is None:
            response = await call_next(request)
        self._apply_security_headers(request, response)
        return response

    def _is_api_request(self, request: Request) -> bool:
        return request.url.path == self.settings.api_prefix or request.url.path.startswith(
            f"{self.settings.api_prefix}/"
        )

    def _auth_required(self) -> bool:
        return self.settings.api_require_auth or self.settings.environment.lower() in {
            "production",
            "prod",
        }

    def _authenticate_api_request(self, request: Request) -> Response | None:
        if request.method == "OPTIONS" or not self._auth_required():
            return None

        path = request.url.path
        if self._is_telemetry_ingest(path):
            return None
        # Keep the stable production denial contract for an endpoint that can
        # never execute in production anyway.
        if path == f"{self.settings.api_prefix}/demo/reset" and not self.settings.api_require_auth:
            return None

        configured = self._configured_credentials()
        if not configured:
            if re.fullmatch(
                rf"{re.escape(self.settings.api_prefix)}/recovery/[^/]+/"
                r"(?:approve|execute|verify|rollback)",
                path,
            ):
                return None
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={
                    "error": "security_misconfigured",
                    "detail": (
                        "Management API authentication is required but no API keys are configured."
                    ),
                },
            )

        authorization = request.headers.get("authorization", "")
        provided = authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
        matched = next(
            (
                (expected, role, credential_id)
                for expected, role, credential_id in configured
                if provided and compare_digest(provided, expected)
            ),
            None,
        )
        if matched is None:
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"error": "unauthorized", "detail": "A valid API credential is required."},
                headers={"WWW-Authenticate": "Bearer"},
            )

        _, role, credential_id = matched
        actor_header = request.headers.get("x-driftzero-actor", "").strip()
        actor = actor_header if _SAFE_ACTOR.fullmatch(actor_header) else credential_id
        request.state.principal = SecurityPrincipal(
            actor=actor,
            role=role,
            tenant_id="00000000-0000-0000-0000-000000000001",
            credential_id=credential_id,
        )

        if request.method not in {"GET", "HEAD"} and role is ActorRole.VIEWER:
            return self._forbidden("Viewer credentials are read-only.")
        if request.method == "DELETE" and role is not ActorRole.ADMIN:
            return self._forbidden("Administrator credentials are required for deletion.")
        if path == f"{self.settings.api_prefix}/demo/reset" and role is not ActorRole.ADMIN:
            return self._forbidden("Administrator credentials are required to reset demo data.")
        return None

    def _configured_credentials(self) -> list[tuple[str, ActorRole, str]]:
        credentials = (
            (self.settings.api_admin_key, ActorRole.ADMIN, "api-admin"),
            (self.settings.api_operator_key, ActorRole.OPERATOR, "api-operator"),
            (self.settings.api_viewer_key, ActorRole.VIEWER, "api-viewer"),
            (self.settings.recovery_admin_api_key, ActorRole.ADMIN, "recovery-admin"),
            (self.settings.recovery_operator_api_key, ActorRole.OPERATOR, "recovery-operator"),
        )
        return [item for item in credentials if item[0]]  # type: ignore[misc]

    def _is_telemetry_ingest(self, path: str) -> bool:
        prefix = re.escape(self.settings.api_prefix)
        return bool(re.fullmatch(rf"{prefix}/models/[^/]+/telemetry", path))

    def _is_rate_limited(self, request: Request) -> bool:
        limit = self.settings.api_rate_limit_per_minute
        if limit <= 0 or request.url.path == "/healthz":
            return False
        credential = request.headers.get("authorization") or request.headers.get(
            "x-driftzero-ingest-key"
        )
        identity = credential or (request.client.host if request.client else "unknown")
        bucket_key = hashlib.sha256(identity.encode()).hexdigest()
        now = time.monotonic()
        with self._rate_lock:
            count, started = self._rate_buckets.get(bucket_key, (0, now))
            if now - started >= 60:
                count, started = 0, now
            count += 1
            self._rate_buckets[bucket_key] = (count, started)
            if len(self._rate_buckets) > 10_000:
                self._rate_buckets = {
                    key: bucket
                    for key, bucket in self._rate_buckets.items()
                    if now - bucket[1] < 60
                }
        return count > limit

    @staticmethod
    def _forbidden(detail: str) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={"error": "forbidden", "detail": detail},
        )

    def _apply_security_headers(self, request: Request, response: Response) -> None:
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; frame-ancestors 'none'; base-uri 'self'; "
            "form-action 'self'; img-src 'self' data: https://fastapi.tiangolo.com; "
            "script-src 'self' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net"
        )
        if self._is_api_request(request):
            response.headers["Cache-Control"] = "no-store"
        if self.settings.environment.lower() in {"production", "prod"}:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
