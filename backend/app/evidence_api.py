"""HTTP boundary for trusted evidence ingestion and retrieval."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.database import Database
from app.evidence import EvidenceConflict, EvidenceError, EvidenceNotFound, EvidenceService
from app.schemas import (
    EvidenceImportRequest,
    EvidenceReviewRequest,
    EvidenceSearchHit,
    EvidenceSearchRequest,
    EvidenceSourceResponse,
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


def get_evidence_service(request: Request) -> EvidenceService:
    return request.app.state.evidence_service


SessionDependency = Annotated[Session, Depends(get_session)]
EvidenceServiceDependency = Annotated[EvidenceService, Depends(get_evidence_service)]


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
