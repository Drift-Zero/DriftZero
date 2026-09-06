"""Authentication boundary for privileged recovery mutations."""

from __future__ import annotations

from secrets import compare_digest

from fastapi import HTTPException, Request, status

from app.config import Settings
from app.schemas import ActorRequest, ActorRole


def recovery_principal(request: Request) -> ActorRequest:
    """Derive the audit actor and role from server-controlled credentials.

    Request JSON is intentionally not consulted. Hosted deployments configure
    separate operator and admin secrets; local identity is available only when
    explicitly enabled outside production.
    """

    settings: Settings = request.app.state.settings
    authorization = request.headers.get("authorization", "")
    provided = authorization[7:] if authorization.lower().startswith("bearer ") else ""
    actor_header = request.headers.get("x-driftzero-actor", "").strip()

    configured = (
        (settings.recovery_admin_api_key, ActorRole.ADMIN, "recovery-admin"),
        (settings.recovery_operator_api_key, ActorRole.OPERATOR, "recovery-operator"),
    )
    for expected, role, default_actor in configured:
        if expected and provided and compare_digest(provided, expected):
            actor = actor_header or default_actor
            return ActorRequest(actor=actor, role=role)

    local_allowed = (
        settings.recovery_allow_local_identity
        and settings.environment.lower() in {"development", "test", "demo", "hackathon-demo"}
    )
    if local_allowed and not provided:
        requested_role = request.headers.get(
            "x-driftzero-role", ActorRole.OPERATOR.value
        ).lower()
        try:
            role = ActorRole(requested_role)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Unknown local recovery role.",
            ) from exc
        return ActorRequest(actor=actor_header or "local-operator", role=role)

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="A valid recovery credential is required.",
        headers={"WWW-Authenticate": "Bearer"},
    )
