"""HTTP routes for the DriftZero reliability lifecycle."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.orm import Session

from app.database import Database
from app.schemas import (
    ActorRequest,
    AlertEvaluationRequest,
    AlertEvaluationResponse,
    AlertFeedResponse,
    AlertResolveRequest,
    AlertResponse,
    AlertRuleCreate,
    AlertRuleResponse,
    AlertRuleUpdate,
    AlertState,
    AuditEventResponse,
    DemoResetResponse,
    DiagnosisResponse,
    EvaluationFeedbackCreate,
    EvaluationFeedbackResponse,
    HealthForecastRecordResponse,
    HealthSnapshotResponse,
    HealthTimelineResponse,
    IncidentResponse,
    ModelCreate,
    ModelLifecycleUpdate,
    ModelResponse,
    ModelUpdate,
    ModelVersionCreate,
    ModelVersionResponse,
    RecoveryCommandResponse,
    RecoveryDecisionRequest,
    RecoveryExecuteRequest,
    RecoveryExecutionResponse,
    RecoveryPlanResponse,
    RegistrationStatusResponse,
    ReviewDecisionRequest,
    ReviewQueueItemResponse,
    ReviewState,
    StabilityKind,
    StabilityRunRequest,
    StabilityTestResponse,
    TelemetryCreate,
    VerificationRunResponse,
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


@router.patch("/models/{model_id}", response_model=ModelResponse, tags=["models"])
def update_model(
    model_id: str,
    payload: ModelUpdate,
    session: SessionDependency,
    service: ServiceDependency,
) -> ModelResponse:
    return service.update_model(session, model_id, payload)


@router.post(
    "/models/{model_id}/lifecycle",
    response_model=ModelResponse,
    tags=["models"],
)
def update_model_lifecycle(
    model_id: str,
    payload: ModelLifecycleUpdate,
    session: SessionDependency,
    service: ServiceDependency,
) -> ModelResponse:
    return service.update_model_lifecycle(session, model_id, payload)


@router.post(
    "/models/{model_id}/versions",
    response_model=ModelVersionResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["models"],
)
def create_model_version(
    model_id: str,
    payload: ModelVersionCreate,
    session: SessionDependency,
    service: ServiceDependency,
) -> ModelVersionResponse:
    return service.create_model_version(
        session,
        model_id,
        payload,
        actor=payload.actor,
    )


@router.get(
    "/models/{model_id}/versions",
    response_model=list[ModelVersionResponse],
    tags=["models"],
)
def list_model_versions(
    model_id: str,
    session: SessionDependency,
    service: ServiceDependency,
) -> list[ModelVersionResponse]:
    return service.list_model_versions(session, model_id)


@router.post(
    "/models/{model_id}/versions/{version_id}/activate",
    response_model=ModelVersionResponse,
    tags=["models"],
)
def activate_model_version(
    model_id: str,
    version_id: str,
    payload: ActorRequest,
    session: SessionDependency,
    service: ServiceDependency,
) -> ModelVersionResponse:
    return service.activate_model_version(
        session,
        model_id,
        version_id,
        actor=payload.actor,
    )


@router.get(
    "/models/{model_id}/registration-status",
    response_model=RegistrationStatusResponse,
    tags=["models"],
)
def registration_status(
    model_id: str,
    session: SessionDependency,
    service: ServiceDependency,
) -> RegistrationStatusResponse:
    return service.registration_status(session, model_id)


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


@router.get(
    "/recovery/{plan_id}",
    response_model=RecoveryPlanResponse,
    tags=["recover"],
)
def get_recovery(
    plan_id: str,
    session: SessionDependency,
    service: ServiceDependency,
) -> RecoveryPlanResponse:
    return service.get_recovery(session, plan_id)


@router.post(
    "/recovery/{plan_id}/approve",
    response_model=RecoveryPlanResponse,
    tags=["recover"],
)
def approve_recovery(
    plan_id: str,
    payload: RecoveryDecisionRequest,
    session: SessionDependency,
    service: ServiceDependency,
) -> RecoveryPlanResponse:
    return service.approve_recovery(session, plan_id, payload)


@router.post(
    "/recovery/{plan_id}/reject",
    response_model=RecoveryPlanResponse,
    tags=["recover"],
)
def reject_recovery(
    plan_id: str,
    payload: RecoveryDecisionRequest,
    session: SessionDependency,
    service: ServiceDependency,
) -> RecoveryPlanResponse:
    return service.reject_recovery(session, plan_id, payload)


@router.post(
    "/recovery/{plan_id}/cancel",
    response_model=RecoveryPlanResponse,
    tags=["recover"],
)
def cancel_recovery(
    plan_id: str,
    payload: RecoveryDecisionRequest,
    session: SessionDependency,
    service: ServiceDependency,
) -> RecoveryPlanResponse:
    return service.cancel_recovery(session, plan_id, payload)


@router.post(
    "/recovery/{plan_id}/execute",
    response_model=RecoveryCommandResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["recover"],
)
def enqueue_recovery(
    plan_id: str,
    payload: RecoveryExecuteRequest,
    session: SessionDependency,
    service: ServiceDependency,
) -> RecoveryCommandResponse:
    return service.enqueue_recovery(session, plan_id, payload)


@router.get(
    "/recovery/{plan_id}/commands",
    response_model=list[RecoveryCommandResponse],
    tags=["recover"],
)
def recovery_commands(
    plan_id: str,
    session: SessionDependency,
    service: ServiceDependency,
) -> list[RecoveryCommandResponse]:
    return service.recovery_commands(session, plan_id)


@router.get(
    "/recovery-commands/{command_id}",
    response_model=RecoveryCommandResponse,
    tags=["recover"],
)
def get_recovery_command(
    command_id: str,
    session: SessionDependency,
    service: ServiceDependency,
) -> RecoveryCommandResponse:
    return service.get_recovery_command(session, command_id)


@router.get(
    "/recovery/{plan_id}/executions",
    response_model=list[RecoveryExecutionResponse],
    tags=["recover"],
)
def recovery_executions(
    plan_id: str,
    session: SessionDependency,
    service: ServiceDependency,
) -> list[RecoveryExecutionResponse]:
    return service.recovery_executions(session, plan_id)


@router.get(
    "/recovery/{plan_id}/verification",
    response_model=VerificationRunResponse,
    tags=["recover"],
)
def recovery_verification(
    plan_id: str,
    session: SessionDependency,
    service: ServiceDependency,
) -> VerificationRunResponse:
    return service.recovery_verification(session, plan_id)


@router.post(
    "/recovery/{plan_id}/rollback",
    response_model=RecoveryPlanResponse,
    tags=["recover"],
)
def rollback_recovery(
    plan_id: str,
    payload: RecoveryDecisionRequest,
    session: SessionDependency,
    service: ServiceDependency,
) -> RecoveryPlanResponse:
    return service.rollback_recovery(session, plan_id, payload)


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


@router.get(
    "/models/{model_id}/review-queue",
    response_model=list[ReviewQueueItemResponse],
    tags=["recover"],
)
def list_review_queue(
    model_id: str,
    session: SessionDependency,
    service: ServiceDependency,
    state: ReviewState | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[ReviewQueueItemResponse]:
    """Work a recovery playbook routed to a human."""

    return service.list_review_queue(session, model_id, state=state, limit=limit)


@router.post(
    "/review-queue/{item_id}/decide",
    response_model=ReviewQueueItemResponse,
    tags=["recover"],
)
def decide_review_item(
    item_id: str,
    payload: ReviewDecisionRequest,
    session: SessionDependency,
    service: ServiceDependency,
) -> ReviewQueueItemResponse:
    return service.decide_review_item(session, item_id, payload)


@router.post(
    "/feedback",
    response_model=EvaluationFeedbackResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["evaluate"],
)
def record_feedback(
    payload: EvaluationFeedbackCreate,
    session: SessionDependency,
    service: ServiceDependency,
) -> EvaluationFeedbackResponse:
    """Record agreement or disagreement with an automated judgement."""

    return service.record_feedback(session, payload)


@router.get(
    "/feedback/{target_type}/{target_id}",
    response_model=list[EvaluationFeedbackResponse],
    tags=["evaluate"],
)
def list_feedback(
    target_type: str,
    target_id: str,
    session: SessionDependency,
    service: ServiceDependency,
) -> list[EvaluationFeedbackResponse]:
    return service.list_feedback(session, target_type, target_id)


@router.post(
    "/models/{model_id}/alert-rules",
    response_model=AlertRuleResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["alerts"],
)
def create_alert_rule(
    model_id: str,
    payload: AlertRuleCreate,
    session: SessionDependency,
    service: ServiceDependency,
) -> AlertRuleResponse:
    return service.create_alert_rule(session, model_id, payload)


@router.get(
    "/models/{model_id}/alert-rules",
    response_model=list[AlertRuleResponse],
    tags=["alerts"],
)
def list_alert_rules(
    model_id: str,
    session: SessionDependency,
    service: ServiceDependency,
) -> list[AlertRuleResponse]:
    return service.list_alert_rules(session, model_id)


@router.get("/alert-rules/{rule_id}", response_model=AlertRuleResponse, tags=["alerts"])
def get_alert_rule(
    rule_id: str,
    session: SessionDependency,
    service: ServiceDependency,
) -> AlertRuleResponse:
    return service.get_alert_rule(session, rule_id)


@router.patch("/alert-rules/{rule_id}", response_model=AlertRuleResponse, tags=["alerts"])
def update_alert_rule(
    rule_id: str,
    payload: AlertRuleUpdate,
    session: SessionDependency,
    service: ServiceDependency,
) -> AlertRuleResponse:
    return service.update_alert_rule(session, rule_id, payload)


@router.delete(
    "/alert-rules/{rule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["alerts"],
)
def delete_alert_rule(
    rule_id: str,
    payload: ActorRequest,
    session: SessionDependency,
    service: ServiceDependency,
) -> Response:
    service.delete_alert_rule(session, rule_id, payload)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/models/{model_id}/alerts/evaluate",
    response_model=AlertEvaluationResponse,
    tags=["alerts"],
)
def evaluate_alerts(
    model_id: str,
    payload: AlertEvaluationRequest,
    session: SessionDependency,
    service: ServiceDependency,
) -> AlertEvaluationResponse:
    """Evaluate rules now; intended for freshness monitors and scheduled jobs."""

    return service.evaluate_alerts(session, model_id, payload)


@router.get(
    "/models/{model_id}/alerts",
    response_model=list[AlertResponse],
    tags=["alerts"],
)
def list_alerts(
    model_id: str,
    session: SessionDependency,
    service: ServiceDependency,
    state: AlertState | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[AlertResponse]:
    return service.list_alerts(session, model_id, state=state, limit=limit)


@router.get("/alerts", response_model=AlertFeedResponse, tags=["alerts"])
def alert_feed(
    session: SessionDependency,
    service: ServiceDependency,
    state: AlertState | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> AlertFeedResponse:
    """Cross-model in-product notification feed for the current tenant."""

    return service.alert_feed(session, state=state, limit=limit)


@router.get("/alerts/{alert_id}", response_model=AlertResponse, tags=["alerts"])
def get_alert(
    alert_id: str,
    session: SessionDependency,
    service: ServiceDependency,
) -> AlertResponse:
    return service.get_alert(session, alert_id)


@router.post("/alerts/{alert_id}/acknowledge", response_model=AlertResponse, tags=["alerts"])
def acknowledge_alert(
    alert_id: str,
    payload: ActorRequest,
    session: SessionDependency,
    service: ServiceDependency,
) -> AlertResponse:
    return service.acknowledge_alert(session, alert_id, payload)


@router.post("/alerts/{alert_id}/resolve", response_model=AlertResponse, tags=["alerts"])
def resolve_alert(
    alert_id: str,
    payload: AlertResolveRequest,
    session: SessionDependency,
    service: ServiceDependency,
) -> AlertResponse:
    return service.resolve_alert(session, alert_id, payload)


@router.post(
    "/models/{model_id}/stability/semantic",
    response_model=StabilityTestResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["evaluate"],
)
def run_semantic_stability(
    model_id: str,
    payload: StabilityRunRequest,
    session: SessionDependency,
    service: ServiceDependency,
) -> StabilityTestResponse:
    """Ask one question several ways and check whether the facts agree."""

    return service.run_semantic_stability(session, model_id, payload)


@router.post(
    "/models/{model_id}/stability/temporal",
    response_model=StabilityTestResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["evaluate"],
)
def run_temporal_stability(
    model_id: str,
    payload: StabilityRunRequest,
    session: SessionDependency,
    service: ServiceDependency,
) -> StabilityTestResponse:
    """Re-ask a controlled question, comparing only when the inputs held."""

    return service.run_temporal_stability(session, model_id, payload)


@router.get(
    "/models/{model_id}/stability",
    response_model=list[StabilityTestResponse],
    tags=["evaluate"],
)
def list_stability_tests(
    model_id: str,
    session: SessionDependency,
    service: ServiceDependency,
    kind: StabilityKind | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[StabilityTestResponse]:
    return service.list_stability_tests(session, model_id, kind=kind, limit=limit)


@router.get(
    "/models/{model_id}/forecasts",
    response_model=list[HealthForecastRecordResponse],
    tags=["pulse"],
)
def list_forecasts(
    model_id: str,
    session: SessionDependency,
    service: ServiceDependency,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[HealthForecastRecordResponse]:
    """Stored predictions and, once their horizon passed, what actually happened."""

    return service.list_forecasts(session, model_id, limit=limit)
