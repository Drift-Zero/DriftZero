"""HTTP boundary for trusted evidence ingestion and retrieval."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.claim_verification import verify_answer
from app.database import Database
from app.evidence import EvidenceConflict, EvidenceError, EvidenceNotFound, EvidenceService
from app.schemas import (
    ClaimVerificationRequest,
    ClaimVerificationResponse,
    DimensionScores,
    EvidenceImportRequest,
    EvidenceRefreshRequest,
    EvidenceReviewRequest,
    EvidenceSearchHit,
    EvidenceSearchRequest,
    EvidenceSourceResponse,
    EvidenceUrlImportRequest,
    InteractionBatchEvaluateRequest,
    InteractionBatchEvaluateResponse,
    InteractionResultResponse,
    TelemetryCreate,
    TraceCreate,
    WebsiteRefreshRequest,
    WebsiteRefreshResponse,
)
from app.service import DriftZeroService
from app.website_sync import WebsiteSyncError, WebsiteSyncService

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


def get_evidence_service(request: Request) -> EvidenceService:
    return request.app.state.evidence_service


def get_driftzero_service(request: Request) -> DriftZeroService:
    return request.app.state.service


SessionDependency = Annotated[Session, Depends(get_session)]
EvidenceServiceDependency = Annotated[EvidenceService, Depends(get_evidence_service)]
DriftZeroServiceDependency = Annotated[DriftZeroService, Depends(get_driftzero_service)]


def get_website_sync_service(request: Request) -> WebsiteSyncService:
    return request.app.state.website_sync_service


WebsiteSyncServiceDependency = Annotated[WebsiteSyncService, Depends(get_website_sync_service)]


def _translate_error(exc: Exception) -> HTTPException:
    if isinstance(exc, EvidenceNotFound):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, EvidenceConflict):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))


@router.post(
    "/models/{model_id}/evidence-sources/import",
    response_model=EvidenceSourceResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["evidence"],
)
def import_evidence_source(
    model_id: str,
    payload: EvidenceImportRequest,
    session: SessionDependency,
    service: EvidenceServiceDependency,
) -> EvidenceSourceResponse:
    try:
        return service.import_source(session, model_id, payload)
    except (EvidenceError, EvidenceConflict, EvidenceNotFound) as exc:
        raise _translate_error(exc) from exc


@router.post(
    "/models/{model_id}/evidence-sources/import-url",
    response_model=EvidenceSourceResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["evidence"],
)
def import_evidence_url(
    model_id: str,
    payload: EvidenceUrlImportRequest,
    session: SessionDependency,
    service: EvidenceServiceDependency,
) -> EvidenceSourceResponse:
    try:
        return service.import_url(session, model_id, payload)
    except (EvidenceError, EvidenceConflict, EvidenceNotFound) as exc:
        raise _translate_error(exc) from exc


@router.get(
    "/models/{model_id}/evidence-sources",
    response_model=list[EvidenceSourceResponse],
    tags=["evidence"],
)
def list_evidence_sources(
    model_id: str,
    session: SessionDependency,
    service: EvidenceServiceDependency,
) -> list[EvidenceSourceResponse]:
    return service.list_sources(session, model_id)


@router.get(
    "/evidence-sources/{source_id}",
    response_model=EvidenceSourceResponse,
    tags=["evidence"],
)
def get_evidence_source(
    source_id: str,
    session: SessionDependency,
    service: EvidenceServiceDependency,
) -> EvidenceSourceResponse:
    try:
        return service.get_source(session, source_id)
    except EvidenceNotFound as exc:
        raise _translate_error(exc) from exc


@router.post(
    "/evidence-sources/{source_id}/review",
    response_model=EvidenceSourceResponse,
    tags=["evidence"],
)
def review_evidence_source(
    source_id: str,
    payload: EvidenceReviewRequest,
    session: SessionDependency,
    service: EvidenceServiceDependency,
) -> EvidenceSourceResponse:
    try:
        return service.review_source(session, source_id, payload)
    except (EvidenceConflict, EvidenceNotFound) as exc:
        raise _translate_error(exc) from exc


@router.post(
    "/evidence-sources/{source_id}/refresh",
    response_model=EvidenceSourceResponse,
    tags=["evidence"],
)
def refresh_evidence_source(
    source_id: str,
    payload: EvidenceRefreshRequest,
    session: SessionDependency,
    service: EvidenceServiceDependency,
) -> EvidenceSourceResponse:
    try:
        return service.refresh_source(session, source_id, payload)
    except (EvidenceError, EvidenceConflict, EvidenceNotFound) as exc:
        raise _translate_error(exc) from exc


@router.post(
    "/models/{model_id}/evidence/search",
    response_model=list[EvidenceSearchHit],
    tags=["evidence"],
)
def search_evidence(
    model_id: str,
    payload: EvidenceSearchRequest,
    session: SessionDependency,
    service: EvidenceServiceDependency,
) -> list[EvidenceSearchHit]:
    return service.search(session, model_id, payload)


@router.post(
    "/connections/{connection_id}/website-refresh",
    response_model=WebsiteRefreshResponse,
    tags=["evidence"],
)
def refresh_website_source(
    connection_id: str,
    payload: WebsiteRefreshRequest,
    session: SessionDependency,
    service: WebsiteSyncServiceDependency,
) -> WebsiteRefreshResponse:
    try:
        return WebsiteRefreshResponse.model_validate(
            service.refresh(session, connection_id, actor=payload.actor),
            from_attributes=True,
        )
    except WebsiteSyncError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc


@router.post(
    "/models/{model_id}/claims/verify",
    response_model=ClaimVerificationResponse,
    tags=["evidence"],
)
def preview_claim_verification(
    model_id: str,
    payload: ClaimVerificationRequest,
    session: SessionDependency,
    service: EvidenceServiceDependency,
) -> ClaimVerificationResponse:
    """Preview auditable claim decisions without creating a health snapshot."""

    claims = verify_answer(
        payload.answer,
        lambda claim: service.search(
            session,
            model_id,
            EvidenceSearchRequest(query=claim, limit=3),
        ),
    )
    return ClaimVerificationResponse(
        supported_claims=sum(claim.verdict == "supported" for claim in claims),
        contradicted_claims=sum(claim.verdict == "contradicted" for claim in claims),
        unverified_claims=sum(claim.verdict == "unverified" for claim in claims),
        claims=claims,
    )


@router.post(
    "/models/{model_id}/interactions/evaluate",
    response_model=InteractionBatchEvaluateResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["evidence", "pulse"],
)
def evaluate_interactions(
    model_id: str,
    payload: InteractionBatchEvaluateRequest,
    session: SessionDependency,
    evidence_service: EvidenceServiceDependency,
    driftzero_service: DriftZeroServiceDependency,
    ingestion_key: str | None = Header(default=None, alias="X-DriftZero-Ingest-Key"),
) -> InteractionBatchEvaluateResponse:
    """Verify provider-neutral interactions and persist one auditable health window."""

    interaction_results: list[InteractionResultResponse] = []
    traces: list[TraceCreate] = []
    supported_total = 0
    contradicted_total = 0
    unverified_total = 0

    for observation in payload.interactions:
        claims = verify_answer(
            observation.answer,
            lambda claim: evidence_service.search(
                session,
                model_id,
                EvidenceSearchRequest(query=claim, limit=3),
            ),
        )
        supported = sum(claim.verdict == "supported" for claim in claims)
        contradicted = sum(claim.verdict == "contradicted" for claim in claims)
        unverified = sum(claim.verdict == "unverified" for claim in claims)
        decided = supported + contradicted
        total = decided + unverified
        groundedness = round(100 * supported / decided, 2) if decided else None
        quality = round(100 * supported / total, 2) if total else None
        document_ids = sorted(
            {claim.evidence.source_id for claim in claims if claim.evidence is not None}
        )
        interaction_results.append(
            InteractionResultResponse(
                request_id=observation.request_id,
                groundedness_score=groundedness,
                supported_claims=supported,
                contradicted_claims=contradicted,
                unverified_claims=unverified,
                claims=claims,
            )
        )
        traces.append(
            TraceCreate(
                occurred_at=observation.occurred_at,
                request_id=observation.request_id,
                question=observation.question,
                answer=observation.answer,
                provider=observation.provider,
                status=observation.status,
                error_code=observation.error_code,
                latency_ms=observation.latency_ms,
                input_tokens=observation.input_tokens,
                output_tokens=observation.output_tokens,
                cost_usd=observation.cost_usd,
                retrieved_document_ids=document_ids,
                citation_count=supported,
                unsupported_claim_count=contradicted,
                groundedness_score=groundedness,
                quality_score=quality,
                safety_flags=observation.safety_flags,
                is_simulated=observation.is_simulated,
            )
        )
        supported_total += supported
        contradicted_total += contradicted
        unverified_total += unverified

    claim_total = supported_total + contradicted_total + unverified_total
    decided_total = supported_total + contradicted_total
    coverage = decided_total / claim_total if claim_total else 0.0
    groundedness_score = round(100 * supported_total / decided_total, 2) if decided_total else None
    quality_score = round(100 * supported_total / claim_total, 2) if claim_total else None
    reliability_score = round(
        100
        * sum(observation.status.value == "ok" for observation in payload.interactions)
        / len(payload.interactions),
        2,
    )
    observed_latencies = [
        observation.latency_ms
        for observation in payload.interactions
        if observation.latency_ms is not None
    ]
    latency_score = None
    if observed_latencies:
        average_latency = sum(observed_latencies) / len(observed_latencies)
        latency_score = round(
            min(100.0, 100 * payload.latency_target_ms / max(1, average_latency)), 2
        )
    observed_costs = [
        observation.cost_usd
        for observation in payload.interactions
        if observation.cost_usd is not None
    ]
    cost_score = None
    if observed_costs and payload.cost_target_usd_per_interaction is not None:
        average_cost = sum(observed_costs) / len(observed_costs)
        cost_score = round(
            min(
                100.0,
                100 * payload.cost_target_usd_per_interaction / max(1e-12, average_cost),
            ),
            2,
        )
    flagged_interactions = sum(
        bool(observation.safety_flags) for observation in payload.interactions
    )
    safety_score = round(100 * (1 - flagged_interactions / len(payload.interactions)), 2)
    event_id = payload.event_id or f"connector:{uuid4()}"
    snapshot = driftzero_service.record_telemetry(
        session,
        model_id,
        TelemetryCreate(
            event_id=event_id,
            observed_at=max(item.occurred_at for item in payload.interactions),
            dimensions=DimensionScores(
                quality=quality_score,
                groundedness=groundedness_score,
                safety=safety_score,
                reliability=reliability_score,
                latency=latency_score,
                cost=cost_score,
            ),
            sample_size=len(payload.interactions),
            coverage=coverage,
            source=payload.source,
            traces=traces,
        ),
        ingestion_key=ingestion_key,
    )
    return InteractionBatchEvaluateResponse(
        model_id=model_id,
        event_id=event_id,
        supported_claims=supported_total,
        contradicted_claims=contradicted_total,
        unverified_claims=unverified_total,
        evidence_coverage=round(coverage, 4),
        groundedness_score=groundedness_score,
        interactions=interaction_results,
        health_snapshot=snapshot,
    )
