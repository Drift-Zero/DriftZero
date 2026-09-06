"""FastAPI application factory for DriftZero."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.api import router
from app.config import Settings
from app.database import Database
from app.service import (
    DriftZeroService,
    InvalidTransition,
    ResourceConflict,
    ResourceNotFound,
)


def create_app(settings: Settings | None = None) -> FastAPI:
    runtime_settings = settings or Settings.from_env()
    database = Database(runtime_settings.database_url)
    service = DriftZeroService(runtime_settings)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        database.create_schema()
        application.state.database = database
        application.state.service = service
        yield
        database.dispose()

    application = FastAPI(
        title="DriftZero API",
        summary="Predict, diagnose, and recover from AI reliability degradation.",
        version="0.1.0",
        lifespan=lifespan,
        openapi_tags=[
            {"name": "models", "description": "Monitored AI system registry."},
            {"name": "pulse", "description": "Health scoring and trajectory."},
            {"name": "diagnose", "description": "Evidence-backed root causes."},
            {"name": "recover", "description": "Approved recovery playbooks."},
            {"name": "audit", "description": "Immutable operator action history."},
            {"name": "demo", "description": "Deterministic CampusGPT scenario."},
        ],
    )
    application.include_router(router, prefix=runtime_settings.api_prefix)

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

    return application


app = create_app()

