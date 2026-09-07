"""User registration and secure cookie-session endpoints."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.auth import AuthIdentity, AuthenticationError, AuthService, IssuedSession
from app.database import Database
from app.schemas import (
    AuthSessionResponse,
    AuthUserResponse,
    UserLoginRequest,
    UserRegisterRequest,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _session(request: Request) -> Iterator[Session]:
    database: Database = request.app.state.database
    with database.session_factory() as session:
        yield session


def _service(request: Request) -> AuthService:
    return request.app.state.auth_service


SessionDependency = Annotated[Session, Depends(_session)]
AuthServiceDependency = Annotated[AuthService, Depends(_service)]


@router.post("/register", response_model=AuthSessionResponse, status_code=status.HTTP_201_CREATED)
def register(
    payload: UserRegisterRequest,
    response: Response,
    request: Request,
    session: SessionDependency,
    service: AuthServiceDependency,
    registration_token: str | None = Header(
        default=None, alias="X-DriftZero-Registration-Token"
    ),
) -> AuthSessionResponse:
    try:
        issued = service.register(
            session,
            email=payload.email,
            password=payload.password.get_secret_value(),
            display_name=payload.display_name,
            tenant_name=payload.tenant_name,
            registration_token=registration_token,
        )
    except AuthenticationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    _set_session_cookie(request, response, issued)
    return _session_response(issued)


@router.post("/login", response_model=AuthSessionResponse)
def login(
    payload: UserLoginRequest,
    response: Response,
    request: Request,
    session: SessionDependency,
    service: AuthServiceDependency,
) -> AuthSessionResponse:
    try:
        issued = service.login(
            session,
            email=payload.email,
            password=payload.password.get_secret_value(),
            tenant_id=payload.tenant_id,
        )
    except AuthenticationError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    _set_session_cookie(request, response, issued)
    return _session_response(issued)


@router.get("/me", response_model=AuthUserResponse)
def me(request: Request) -> AuthUserResponse:
    principal = getattr(request.state, "principal", None)
    if principal is None or principal.user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="A user session is required.",
        )
    return AuthUserResponse(
        user_id=principal.user_id,
        email=principal.email,
        display_name=principal.display_name,
        tenant_id=principal.tenant_id,
        tenant_name=principal.tenant_name,
        role=principal.role,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    response: Response,
    session: SessionDependency,
    service: AuthServiceDependency,
) -> Response:
    token = request.cookies.get(request.app.state.settings.auth_cookie_name)
    if token:
        service.revoke(session, token)
    response.delete_cookie(request.app.state.settings.auth_cookie_name, path="/")
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


def _set_session_cookie(request: Request, response: Response, issued: IssuedSession) -> None:
    settings = request.app.state.settings
    production = settings.environment.lower() in {"production", "prod"}
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=issued.token,
        max_age=settings.auth_session_ttl_hours * 3600,
        expires=issued.expires_at,
        secure=production,
        httponly=True,
        samesite="lax",
        path="/",
    )


def _session_response(issued: IssuedSession) -> AuthSessionResponse:
    return AuthSessionResponse(
        user=_user_response(issued.identity),
        csrf_token=issued.csrf_token,
        expires_at=issued.expires_at,
    )


def _user_response(identity: AuthIdentity) -> AuthUserResponse:
    return AuthUserResponse(
        user_id=identity.user_id,
        email=identity.email,
        display_name=identity.display_name,
        tenant_id=identity.tenant_id,
        tenant_name=identity.tenant_name,
        role=identity.role,
    )
