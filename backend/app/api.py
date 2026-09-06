"""HTTP routes for the DriftZero reliability lifecycle."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from app.database import Database
from app.schemas import (
    ActorRequest,
    AuditEventResponse,
    DemoResetResponse,
    DiagnosisResponse,
    HealthSnapshotResponse,
    HealthTimelineResponse,
    IncidentResponse,
    ModelCreate,
    ModelResponse,
    RecoveryPlanResponse,
    TelemetryCreate,
)
from app.service import DriftZeroService

router = APIRouter()


def get_session(request: Request) -> Iterator[Session]:
    database: Database = request.app.state.database
    yield from database.session()


def get_service(request: Request) -> DriftZeroService:
    return request.app.state.service


SessionDependency = Annotated[Session, Depends(get_session)]
ServiceDependency = Annotated[DriftZeroService, Depends(get_service)]


@router.post(
    "/models",
    response_model=ModelResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["models"],
)
def create_model(
    payload: ModelCreate,
    session: SessionDependency,
    service: ServiceDependency,
) -> ModelResponse:
    return service.create_model(session, payload)


@router.get("/models", response_model=list[ModelResponse], tags=["models"])
def list_models(
    session: SessionDependency,
    service: ServiceDependency,
) -> list[ModelResponse]:
    return service.list_models(session)


@router.get("/models/{model_id}", response_model=ModelResponse, tags=["models"])
def get_model(
    model_id: str,
    session: SessionDependency,
    service: ServiceDependency,
) -> ModelResponse:
    return service.get_model(session, model_id)


@router.post(
    "/models/{model_id}/telemetry",
    response_model=HealthSnapshotResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["pulse"],
)
def record_telemetry(
    model_id: str,
    payload: TelemetryCreate,
    session: SessionDependency,
    service: ServiceDependency,
) -> HealthSnapshotResponse:
    return service.record_telemetry(session, model_id, payload)


@router.get(
    "/models/{model_id}/health",
    response_model=HealthTimelineResponse,
    tags=["pulse"],
)
def health_timeline(
    model_id: str,
    session: SessionDependency,
    service: ServiceDependency,
    limit: Annotated[int, Query(ge=2, le=500)] = 50,
) -> HealthTimelineResponse:
    return service.health_timeline(session, model_id, limit=limit)


@router.post(
    "/models/{model_id}/diagnoses",
    response_model=DiagnosisResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["diagnose"],
)
def diagnose_latest(
    model_id: str,
    session: SessionDependency,
    service: ServiceDependency,
) -> DiagnosisResponse:
    return service.diagnose_latest(session, model_id)


@router.get(
    "/models/{model_id}/diagnoses/latest",
    response_model=DiagnosisResponse,
    tags=["diagnose"],
)
def latest_diagnosis(
    model_id: str,
    session: SessionDependency,
    service: ServiceDependency,
) -> DiagnosisResponse:
    return service.latest_diagnosis(session, model_id)


@router.get(
    "/models/{model_id}/incidents",
    response_model=list[IncidentResponse],
    tags=["diagnose"],
)
def list_incidents(
    model_id: str,
    session: SessionDependency,
    service: ServiceDependency,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[IncidentResponse]:
    """Recent incidents for a model, most recently opened first."""

    return service.list_incidents(session, model_id, limit=limit)


@router.get(
    "/incidents/{incident_id}",
    response_model=IncidentResponse,
    tags=["diagnose"],
)
def get_incident(
    incident_id: str,
    session: SessionDependency,
    service: ServiceDependency,
) -> IncidentResponse:
    return service.get_incident(session, incident_id)


@router.get(
    "/models/{model_id}/recovery/latest",
    response_model=RecoveryPlanResponse,
    tags=["recover"],
)
def latest_recovery(
    model_id: str,
    session: SessionDependency,
    service: ServiceDependency,
) -> RecoveryPlanResponse:
    return service.latest_recovery(session, model_id)


@router.post(
    "/recovery/{plan_id}/approve",
    response_model=RecoveryPlanResponse,
    tags=["recover"],
)
def approve_recovery(
    plan_id: str,
    payload: ActorRequest,
    session: SessionDependency,
    service: ServiceDependency,
) -> RecoveryPlanResponse:
    return service.approve_recovery(session, plan_id, payload)


@router.post(
    "/recovery/{plan_id}/execute",
    response_model=RecoveryPlanResponse,
    tags=["recover"],
)
def execute_recovery(
    plan_id: str,
    payload: ActorRequest,
    session: SessionDependency,
    service: ServiceDependency,
) -> RecoveryPlanResponse:
    return service.execute_recovery(session, plan_id, payload)


@router.get(
    "/models/{model_id}/audit",
    response_model=list[AuditEventResponse],
    tags=["audit"],
)
def audit_events(
    model_id: str,
    session: SessionDependency,
    service: ServiceDependency,
) -> list[AuditEventResponse]:
    return service.audit_events(session, model_id)


@router.post(
    "/demo/reset",
    response_model=DemoResetResponse,
    tags=["demo"],
)
def reset_demo(
    session: SessionDependency,
    service: ServiceDependency,
) -> DemoResetResponse:
    return service.reset_demo(session)

