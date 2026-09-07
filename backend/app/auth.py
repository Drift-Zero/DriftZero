"""Password and opaque-session authentication for tenant users."""

from __future__ import annotations

import hashlib
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from secrets import compare_digest

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import Tenant, TenantMembership, User, UserSession
from app.schemas import ActorRole

_EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class AuthenticationError(ValueError):
    pass


class RegistrationDenied(AuthenticationError):
    pass


@dataclass(frozen=True, slots=True)
class AuthIdentity:
    user_id: str
    email: str
    display_name: str
    tenant_id: str
    tenant_name: str
    role: ActorRole
    session_id: str
    csrf_token_hash: str


@dataclass(frozen=True, slots=True)
class IssuedSession:
    identity: AuthIdentity
    token: str
    csrf_token: str
    expires_at: datetime


class AuthService:
    """Create users and verify revocable, server-stored browser sessions."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.passwords = PasswordHasher(time_cost=3, memory_cost=65_536, parallelism=4)
        self._dummy_hash = self.passwords.hash("driftzero-invalid-password")

    def register(
        self,
        session: Session,
        *,
        email: str,
        password: str,
        display_name: str,
        tenant_name: str,
        registration_token: str | None,
    ) -> IssuedSession:
        self._authorize_registration(registration_token)
        normalized_email = self._normalize_email(email)
        if session.scalar(select(User.id).where(User.email == normalized_email)):
            raise AuthenticationError("An account with this email already exists.")

        tenant = Tenant(slug=self._tenant_slug(tenant_name), name=tenant_name.strip())
        user = User(
            email=normalized_email,
            display_name=display_name.strip(),
            password_hash=self.passwords.hash(password),
        )
        session.add_all([tenant, user])
        session.flush()
        session.add(
            TenantMembership(tenant_id=tenant.id, user_id=user.id, role=ActorRole.ADMIN.value)
        )
        session.flush()
        issued = self._issue_session(session, user, tenant, ActorRole.ADMIN)
        session.commit()
        return issued

    def login(
        self,
        session: Session,
        *,
        email: str,
        password: str,
        tenant_id: str | None = None,
    ) -> IssuedSession:
        normalized_email = self._normalize_email(email)
        user = session.scalar(select(User).where(User.email == normalized_email))
        password_hash = user.password_hash if user else self._dummy_hash
        try:
            password_valid = self.passwords.verify(password_hash, password)
        except (VerifyMismatchError, InvalidHashError):
            password_valid = False
        if user is None or not user.is_active or not password_valid:
            raise AuthenticationError("Invalid email or password.")

        statement = select(TenantMembership).where(TenantMembership.user_id == user.id)
        if tenant_id:
            statement = statement.where(TenantMembership.tenant_id == tenant_id)
        membership = session.scalar(statement.order_by(TenantMembership.created_at))
        if membership is None:
            raise AuthenticationError("The account has no access to this tenant.")
        tenant = session.get(Tenant, membership.tenant_id)
        if tenant is None:
            raise AuthenticationError("The account tenant no longer exists.")
        issued = self._issue_session(session, user, tenant, ActorRole(membership.role))
        session.commit()
        return issued

    def authenticate(self, session: Session, token: str) -> AuthIdentity | None:
        token_hash = self._hash_token(token)
        record = session.scalar(
            select(UserSession).where(
                UserSession.token_hash == token_hash,
                UserSession.revoked_at.is_(None),
                UserSession.expires_at > datetime.now(UTC),
            )
        )
        if record is None:
            return None
        user = session.get(User, record.user_id)
        membership = session.scalar(
            select(TenantMembership).where(
                TenantMembership.user_id == record.user_id,
                TenantMembership.tenant_id == record.tenant_id,
            )
        )
        tenant = session.get(Tenant, record.tenant_id)
        if user is None or not user.is_active or membership is None or tenant is None:
            return None
        record.last_used_at = datetime.now(UTC)
        session.commit()
        return AuthIdentity(
            user_id=user.id,
            email=user.email,
            display_name=user.display_name,
            tenant_id=tenant.id,
            tenant_name=tenant.name,
            role=ActorRole(membership.role),
            session_id=record.id,
            csrf_token_hash=record.csrf_token_hash,
        )

    def revoke(self, session: Session, token: str) -> None:
        record = session.scalar(
            select(UserSession).where(UserSession.token_hash == self._hash_token(token))
        )
        if record is not None and record.revoked_at is None:
            record.revoked_at = datetime.now(UTC)
            session.commit()

    def csrf_matches(self, identity: AuthIdentity, supplied: str) -> bool:
        return bool(supplied) and compare_digest(
            identity.csrf_token_hash, self._hash_token(supplied)
        )

    def _issue_session(
        self, session: Session, user: User, tenant: Tenant, role: ActorRole
    ) -> IssuedSession:
        token = secrets.token_urlsafe(32)
        csrf_token = secrets.token_urlsafe(32)
        expires_at = datetime.now(UTC) + timedelta(hours=self.settings.auth_session_ttl_hours)
        record = UserSession(
            token_hash=self._hash_token(token),
            csrf_token_hash=self._hash_token(csrf_token),
            user_id=user.id,
            tenant_id=tenant.id,
            expires_at=expires_at,
        )
        session.add(record)
        session.flush()
        return IssuedSession(
            identity=AuthIdentity(
                user_id=user.id,
                email=user.email,
                display_name=user.display_name,
                tenant_id=tenant.id,
                tenant_name=tenant.name,
                role=role,
                session_id=record.id,
                csrf_token_hash=record.csrf_token_hash,
            ),
            token=token,
            csrf_token=csrf_token,
            expires_at=expires_at,
        )

    def _authorize_registration(self, supplied: str | None) -> None:
        production = self.settings.environment.lower() in {"production", "prod"}
        expected = self.settings.auth_registration_token
        if production and (not expected or not supplied or not compare_digest(expected, supplied)):
            raise RegistrationDenied("A valid registration bootstrap token is required.")

    @staticmethod
    def _normalize_email(email: str) -> str:
        normalized = email.strip().lower()
        if len(normalized) > 320 or not _EMAIL.fullmatch(normalized):
            raise AuthenticationError("Enter a valid email address.")
        return normalized

    @staticmethod
    def _tenant_slug(name: str) -> str:
        base = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")[:55]
        if not base:
            raise AuthenticationError("Tenant name must contain letters or numbers.")
        return f"{base}-{secrets.token_hex(4)}"

    @staticmethod
    def _hash_token(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()
