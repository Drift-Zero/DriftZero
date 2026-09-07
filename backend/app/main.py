"""FastAPI application factory for DriftZero."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api import router
from app.auth import AuthService
from app.auth_api import router as auth_router
from app.config import Settings
from app.database import Database
from app.observability import (
    RequestLoggingMiddleware,
    configure_database_logging,
    configure_logging,
    configure_opentelemetry,
)
from app.security import RequestBodyLimitMiddleware, SecurityMiddleware
from app.service import (
    AuthorizationDenied,
    ConnectionConfigurationError,
    DriftZeroService,
    ExternalProviderError,
    InvalidTransition,
    ResourceConflict,
    ResourceNotFound,
    TelemetryIngestionError,
)


def create_app(settings: Settings | None = None) -> FastAPI:
    runtime_settings = settings or Settings.from_env()
    production = runtime_settings.environment.lower() in {"production", "prod"}
    logger = configure_logging(runtime_settings)
    database = Database(runtime_settings.database_url)
    configure_database_logging(database.engine, slow_query_ms=runtime_settings.slow_query_ms)
    service = DriftZeroService(runtime_settings)
    auth_service = AuthService(runtime_settings)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        database.create_schema()
        application.state.database = database
        application.state.service = service
        logger.info(
            "service.started",
            extra={"event": "service.lifecycle"},
        )
        yield
        logger.info(
            "service.stopped",
            extra={"event": "service.lifecycle"},
        )
        database.dispose()

    application = FastAPI(
        title="DriftZero API",
        summary="Predict, diagnose, and recover from AI reliability degradation.",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if runtime_settings.docs_enabled and not production else None,
        redoc_url="/redoc" if runtime_settings.docs_enabled and not production else None,
        openapi_url=(
            "/openapi.json" if runtime_settings.docs_enabled and not production else None
        ),
        openapi_tags=[
            {"name": "models", "description": "Monitored AI system registry."},
            {"name": "auth", "description": "Tenant user sessions."},
            {"name": "pulse", "description": "Health scoring and trajectory."},
            {"name": "diagnose", "description": "Evidence-backed root causes."},
            {"name": "recover", "description": "Approved recovery playbooks."},
            {"name": "alerts", "description": "Rules, alert lifecycle, and notifications."},
            {"name": "audit", "description": "Immutable operator action history."},
            {"name": "demo", "description": "Deterministic ShopAssist scenario."},
        ],
    )
    application.state.settings = runtime_settings
    application.state.auth_service = auth_service
    cors_origins = list(runtime_settings.cors_origins)
    if not cors_origins and runtime_settings.environment.lower() not in {"production", "prod"}:
        cors_origins = ["http://127.0.0.1:5173", "http://localhost:5173"]
    if cors_origins or runtime_settings.cors_origin_regex:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_origin_regex=runtime_settings.cors_origin_regex,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=[
                "Authorization",
                "Content-Type",
                "X-DriftZero-Actor",
                "X-DriftZero-Ingest-Key",
                "X-DriftZero-Registration-Token",
                "X-DriftZero-Role",
                "X-CSRF-Token",
                "X-Request-ID",
            ],
        )
    application.add_middleware(RequestLoggingMiddleware)
    application.add_middleware(
        RequestBodyLimitMiddleware,
        max_bytes=runtime_settings.api_max_request_bytes,
    )
    application.add_middleware(SecurityMiddleware, settings=runtime_settings)
    if runtime_settings.trusted_hosts:
        application.add_middleware(
            TrustedHostMiddleware,
            allowed_hosts=list(runtime_settings.trusted_hosts),
        )
    application.include_router(router, prefix=runtime_settings.api_prefix)
    application.include_router(auth_router, prefix=runtime_settings.api_prefix)
    application.state.opentelemetry_enabled = configure_opentelemetry(
        application,
        database.engine,
        runtime_settings,
    )

    @application.get("/healthz", tags=["system"])
    def healthcheck() -> dict[str, str]:
        return {"status": "ok", "environment": runtime_settings.environment}

    @application.exception_handler(ResourceNotFound)
    async def not_found_handler(_: Request, exc: ResourceNotFound) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"error": "not_found", "detail": str(exc)},
        )

    @application.exception_handler(ResourceConflict)
    async def conflict_handler(_: Request, exc: ResourceConflict) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"error": "conflict", "detail": str(exc)},
        )

    @application.exception_handler(InvalidTransition)
    async def transition_handler(_: Request, exc: InvalidTransition) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"error": "invalid_transition", "detail": str(exc)},
        )

    @application.exception_handler(AuthorizationDenied)
    async def authorization_handler(_: Request, exc: AuthorizationDenied) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={"error": "forbidden", "detail": str(exc)},
        )

    @application.exception_handler(TelemetryIngestionError)
    async def telemetry_handler(_: Request, exc: TelemetryIngestionError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={"error": "telemetry_ingestion_failed", "detail": str(exc)},
        )

    @application.exception_handler(ConnectionConfigurationError)
    async def connection_configuration_handler(
        _: Request, exc: ConnectionConfigurationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={"error": "connection_configuration_failed", "detail": str(exc)},
        )

    @application.exception_handler(ExternalProviderError)
    async def external_provider_handler(_: Request, exc: ExternalProviderError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content={"error": "external_provider_failed", "detail": str(exc)},
        )

    if runtime_settings.frontend_dir:
        frontend_dir = Path(runtime_settings.frontend_dir)
        if not frontend_dir.is_dir():
            raise RuntimeError(f"DRIFTZERO_FRONTEND_DIR does not exist: {frontend_dir}")
        application.mount(
            "/",
            StaticFiles(directory=frontend_dir, html=True),
            name="dashboard",
        )

    return application


app = create_app()
