"""HTTP routes for the DriftZero reliability lifecycle."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import Database
from app.db.models import EvaluationRun, VerificationSource
from app.recovery_auth import recovery_principal
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
    ClaimImportance,
    ConnectionCheckResponse,
    ConnectionCreate,
    ConnectionCreatedResponse,
    ConnectionResponse,
    ConnectionUpdate,
    DemoResetResponse,
    DiagnosisResponse,
    EvaluationFeedbackCreate,
    EvaluationFeedbackResponse,
    EvaluationRequest,
    EvaluationResponse,
    EvaluationSummaryResponse,
    GroqEvaluationRequest,
    GroqEvaluationResponse,
    GroqModelCatalogResponse,
    GroqModelImportRequest,
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
    RecoveryRollbackRequest,
    RecoveryVerifyRequest,
    RegistrationStatusResponse,
    ReviewDecisionRequest,
    ReviewQueueItemResponse,
    ReviewState,
    ShopAssistTelemetryCreate,
    StabilityKind,
    StabilityRunRequest,
    StabilityTestResponse,
    TelemetryCreate,
    VerificationChunkResponse,
    VerificationRunResponse,
    VerificationSourceDecision,
    VerificationSourceResponse,
)
from app.service import DriftZeroService, InvalidTransition, ResourceNotFound
from app.verification.api_support import (
    evaluation_claims,
    evaluation_summary,
    evidence_response,
    groundedness_breakdown,
    quality_breakdown,
    source_response,
    stored_evaluation_claims,
)
from app.verification.metrics import ClaimOutcome, score_groundedness
from app.verification.pipeline import evaluate_response
from app.verification.sources import (
    SourceError,
    approve_source,
    reject_source,
    retire_source,
    seed_shopassist_corpus,
)

router = APIRouter()


def get_session(request: Request) -> Iterator[Session]:
    database: Database = request.app.state.database
    with database.session_factory() as session:
        principal = getattr(request.state, "principal", None)
        if principal is not None:
            session.info["tenant_id"] = principal.tenant_id
        try:
            yield session
        except Exception:
            session.rollback()
            raise


def get_service(request: Request) -> DriftZeroService:
    return request.app.state.service


SessionDependency = Annotated[Session, Depends(get_session)]
ServiceDependency = Annotated[DriftZeroService, Depends(get_service)]
RecoveryPrincipalDependency = Annotated[ActorRequest, Depends(recovery_principal)]


def _trusted_recovery_request[RecoveryRequest: ActorRequest](
    payload: RecoveryRequest,
    principal: ActorRequest,
) -> RecoveryRequest:
    """Keep command parameters while replacing untrusted identity fields."""

    return payload.model_copy(update={"actor": principal.actor, "role": principal.role})


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


@router.get(
    "/integrations/groq/models",
    response_model=GroqModelCatalogResponse,
    tags=["models"],
)
def list_groq_models(service: ServiceDependency) -> GroqModelCatalogResponse:
    """Discover models with the backend-owned Groq credential."""

    return service.groq_models()


@router.post(
    "/integrations/groq/models",
    response_model=ModelResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["models"],
)
def import_groq_model(
    payload: GroqModelImportRequest,
    session: SessionDependency,
    service: ServiceDependency,
) -> ModelResponse:
    return service.import_groq_model(session, payload)


@router.post(
    "/models/{model_id}/evaluations/groq",
    response_model=GroqEvaluationResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["pulse"],
)
def evaluate_groq_model(
    model_id: str,
    payload: GroqEvaluationRequest,
    session: SessionDependency,
    service: ServiceDependency,
) -> GroqEvaluationResponse:
    return service.evaluate_groq_model(session, model_id, payload)


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
    "/models/{model_id}/connections",
    response_model=ConnectionCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["models"],
)
def create_connection(
    model_id: str,
    payload: ConnectionCreate,
    session: SessionDependency,
    service: ServiceDependency,
) -> ConnectionCreatedResponse:
    return service.create_connection(session, model_id, payload)


@router.get(
    "/models/{model_id}/connections",
    response_model=list[ConnectionResponse],
    tags=["models"],
)
def list_connections(
    model_id: str,
    session: SessionDependency,
    service: ServiceDependency,
) -> list[ConnectionResponse]:
    return service.list_connections(session, model_id)


@router.get(
    "/connections/{connection_id}", response_model=ConnectionResponse, tags=["models"]
)
def get_connection(
    connection_id: str,
    session: SessionDependency,
    service: ServiceDependency,
) -> ConnectionResponse:
    return service.get_connection(session, connection_id)


@router.patch(
    "/connections/{connection_id}", response_model=ConnectionResponse, tags=["models"]
)
def update_connection(
    connection_id: str,
    payload: ConnectionUpdate,
    session: SessionDependency,
    service: ServiceDependency,
) -> ConnectionResponse:
    return service.update_connection(session, connection_id, payload)


@router.post(
    "/connections/{connection_id}/check",
    response_model=ConnectionCheckResponse,
    tags=["models"],
)
def check_connection(
    connection_id: str,
    payload: ActorRequest,
    session: SessionDependency,
    service: ServiceDependency,
) -> ConnectionCheckResponse:
    return service.check_connection(session, connection_id, actor=payload.actor)


@router.delete(
    "/connections/{connection_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["models"]
)
def delete_connection(
    connection_id: str,
    session: SessionDependency,
    service: ServiceDependency,
    actor: str = Query(default="system", min_length=1, max_length=120),
) -> Response:
    service.delete_connection(session, connection_id, actor=actor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
    ingestion_key: str | None = Header(default=None, alias="X-DriftZero-Ingest-Key"),
) -> HealthSnapshotResponse:
    return service.record_telemetry(
        session, model_id, payload, ingestion_key=ingestion_key
    )


@router.post(
    "/shopassist/telemetry",
    response_model=HealthSnapshotResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["pulse"],
)
@router.post(
    "/integrations/shopassist/telemetry",
    response_model=HealthSnapshotResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["pulse"],
    include_in_schema=False,
)
def record_shopassist_telemetry(
    payload: ShopAssistTelemetryCreate,
    session: SessionDependency,
    service: ServiceDependency,
) -> HealthSnapshotResponse:
    """Server-owned telemetry proxy for the ShopAssist demo deployment."""

    return service.record_shopassist_telemetry(session, payload)


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
    principal: RecoveryPrincipalDependency,
) -> RecoveryPlanResponse:
    return service.approve_recovery(
        session, plan_id, _trusted_recovery_request(payload, principal)
    )


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
    principal: RecoveryPrincipalDependency,
) -> RecoveryPlanResponse:
    return service.reject_recovery(
        session, plan_id, _trusted_recovery_request(payload, principal)
    )


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
    principal: RecoveryPrincipalDependency,
) -> RecoveryPlanResponse:
    return service.cancel_recovery(
        session, plan_id, _trusted_recovery_request(payload, principal)
    )


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
    principal: RecoveryPrincipalDependency,
) -> RecoveryCommandResponse:
    return service.enqueue_recovery(
        session, plan_id, _trusted_recovery_request(payload, principal)
    )


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
    "/recovery/{plan_id}/verify",
    response_model=RecoveryCommandResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["recover"],
)
def enqueue_recovery_verification(
    plan_id: str,
    payload: RecoveryVerifyRequest,
    session: SessionDependency,
    service: ServiceDependency,
    principal: RecoveryPrincipalDependency,
) -> RecoveryCommandResponse:
    return service.enqueue_verification(
        session, plan_id, _trusted_recovery_request(payload, principal)
    )


@router.post(
    "/recovery/{plan_id}/rollback",
    response_model=RecoveryCommandResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["recover"],
)
def rollback_recovery(
    plan_id: str,
    payload: RecoveryRollbackRequest,
    session: SessionDependency,
    service: ServiceDependency,
    principal: RecoveryPrincipalDependency,
) -> RecoveryCommandResponse:
    return service.enqueue_rollback(
        session, plan_id, _trusted_recovery_request(payload, principal)
    )


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


# --------------------------------------------------------------------------- #
# Verification sources and evidence-grounded evaluation
# --------------------------------------------------------------------------- #


def _require_source(
    session: Session, service: DriftZeroService, source_id: str
) -> VerificationSource:
    """Load a source, refusing to cross the tenant boundary."""

    tenant_id = service._tenant_id(session)
    source = session.get(VerificationSource, source_id)
    if source is None or source.tenant_id != tenant_id:
        raise ResourceNotFound("Verification source not found.")
    return source


@router.get(
    "/verification-sources",
    response_model=list[VerificationSourceResponse],
    tags=["verify"],
)
def list_verification_sources(
    session: SessionDependency,
    service: ServiceDependency,
) -> list[VerificationSourceResponse]:
    """Every trusted source this tenant has connected, with version history."""

    tenant_id = service._tenant_id(session)
    sources = session.scalars(
        select(VerificationSource)
        .where(VerificationSource.tenant_id == tenant_id)
        .order_by(VerificationSource.created_at)
    ).all()
    return [source_response(session, source) for source in sources]


@router.post(
    "/verification-sources/demo",
    response_model=list[VerificationSourceResponse],
    status_code=status.HTTP_201_CREATED,
    tags=["verify"],
)
def load_demo_verification_source(
    session: SessionDependency,
    service: ServiceDependency,
) -> list[VerificationSourceResponse]:
    """Load the built-in ShopAssist corpus, awaiting review.

    Deliberately not approved on arrival: a source has to be reviewed before
    anything can be verified against it, which is the point the demo makes.
    """

    tenant_id = service._tenant_id(session)
    current, retired = seed_shopassist_corpus(session, tenant_id=tenant_id, approve=False)
    service._audit(
        session,
        None,
        "verification.source_imported",
        "operator",
        {"source_id": current.id, "name": current.name},
    )
    session.commit()
    return [source_response(session, current), source_response(session, retired)]


@router.get(
    "/verification-sources/{source_id}",
    response_model=VerificationSourceResponse,
    tags=["verify"],
)
def get_verification_source(
    source_id: str,
    session: SessionDependency,
    service: ServiceDependency,
) -> VerificationSourceResponse:
    return source_response(session, _require_source(session, service, source_id))


@router.get(
    "/verification-sources/{source_id}/evidence",
    response_model=list[VerificationChunkResponse],
    tags=["verify"],
)
def get_verification_evidence(
    source_id: str,
    session: SessionDependency,
    service: ServiceDependency,
    include_retired: bool = False,
) -> list[VerificationChunkResponse]:
    """The passages an operator reads before approving a source."""

    source = _require_source(session, service, source_id)
    return evidence_response(session, source, include_retired=include_retired)


@router.post(
    "/verification-sources/{source_id}/approve",
    response_model=VerificationSourceResponse,
    tags=["verify"],
)
def approve_verification_source(
    source_id: str,
    payload: VerificationSourceDecision,
    session: SessionDependency,
    service: ServiceDependency,
) -> VerificationSourceResponse:
    source = _require_source(session, service, source_id)
    try:
        approve_source(session, source=source, actor=payload.actor)
    except SourceError as exc:
        raise InvalidTransition(str(exc)) from exc
    service._audit(
        session,
        None,
        "verification.source_approved",
        payload.actor,
        {"source_id": source.id, "name": source.name, "reason": payload.reason},
    )
    session.commit()
    return source_response(session, source)


@router.post(
    "/verification-sources/{source_id}/reject",
    response_model=VerificationSourceResponse,
    tags=["verify"],
)
def reject_verification_source(
    source_id: str,
    payload: VerificationSourceDecision,
    session: SessionDependency,
    service: ServiceDependency,
) -> VerificationSourceResponse:
    source = _require_source(session, service, source_id)
    reject_source(session, source=source, actor=payload.actor)
    service._audit(
        session,
        None,
        "verification.source_rejected",
        payload.actor,
        {"source_id": source.id, "reason": payload.reason},
    )
    session.commit()
    return source_response(session, source)


@router.post(
    "/verification-sources/{source_id}/retire",
    response_model=VerificationSourceResponse,
    tags=["verify"],
)
def retire_verification_source(
    source_id: str,
    payload: VerificationSourceDecision,
    session: SessionDependency,
    service: ServiceDependency,
) -> VerificationSourceResponse:
    """Retire every version. The content stays readable; it stops being truth."""

    source = _require_source(session, service, source_id)
    retire_source(session, source=source, actor=payload.actor)
    service._audit(
        session,
        None,
        "verification.source_retired",
        payload.actor,
        {"source_id": source.id, "reason": payload.reason},
    )
    session.commit()
    return source_response(session, source)


@router.post(
    "/models/{model_id}/evaluate",
    response_model=EvaluationResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["verify"],
)
def evaluate_model_response(
    model_id: str,
    payload: EvaluationRequest,
    session: SessionDependency,
    service: ServiceDependency,
) -> EvaluationResponse:
    """Verify one response against approved evidence and record the reasoning."""

    service._require_model(session, model_id)
    tenant_id = service._tenant_id(session)
    result = evaluate_response(
        session,
        tenant_id=tenant_id,
        model_id=model_id,
        question=payload.question,
        answer=payload.answer,
        trace_id=payload.trace_id,
    )
    run = session.get(EvaluationRun, result.run_id)
    service._audit(
        session,
        model_id,
        "verification.evaluated",
        "evaluator",
        {
            "evaluation_id": result.run_id,
            "groundedness": result.groundedness.groundedness,
            "claims": len(result.claims),
        },
    )
    session.commit()
    return EvaluationResponse(
        id=result.run_id,
        model_id=model_id,
        status=run.status,
        evaluator_provider=result.evaluator_provider,
        evaluator_model=result.evaluator_model,
        extractor_version=run.extractor_version,
        verifier_version=run.verifier_version,
        corpus_versions=result.corpus_versions,
        created_at=run.created_at,
        completed_at=run.completed_at,
        claims=evaluation_claims(result),
        groundedness=groundedness_breakdown(result.groundedness),
        quality=quality_breakdown(result.quality),
    )


@router.get(
    "/evaluations/{evaluation_id}",
    response_model=EvaluationResponse,
    tags=["verify"],
)
def get_evaluation(
    evaluation_id: str,
    session: SessionDependency,
    service: ServiceDependency,
) -> EvaluationResponse:
    """The stored reasoning chain behind a displayed metric."""

    tenant_id = service._tenant_id(session)
    run = session.get(EvaluationRun, evaluation_id)
    if run is None or run.tenant_id != tenant_id:
        raise ResourceNotFound("Evaluation not found.")

    claims = stored_evaluation_claims(session, run)
    outcomes = [
        ClaimOutcome(importance=ClaimImportance(claim.importance), verdict=claim.verdict)
        for claim in claims
    ]
    return EvaluationResponse(
        id=run.id,
        model_id=run.model_id,
        status=run.status,
        evaluator_provider=run.evaluator_provider,
        evaluator_model=run.evaluator_model,
        extractor_version=run.extractor_version,
        verifier_version=run.verifier_version,
        corpus_versions=run.corpus_versions or [],
        created_at=run.created_at,
        completed_at=run.completed_at,
        error=run.error,
        claims=claims,
        groundedness=groundedness_breakdown(score_groundedness(outcomes)),
    )


@router.get(
    "/models/{model_id}/evaluation-summary",
    response_model=EvaluationSummaryResponse,
    tags=["verify"],
)
def get_evaluation_summary(
    model_id: str,
    session: SessionDependency,
    service: ServiceDependency,
) -> EvaluationSummaryResponse:
    """Window aggregate. ``meets_minimum`` gates any health claim built on it."""

    service._require_model(session, model_id)
    return evaluation_summary(session, model_id=model_id)
