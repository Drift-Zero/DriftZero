"""Shared SQLAlchemy foundations: metadata conventions, portable types, mixins.

Everything in this module exists to keep the schema honest across both supported
backends. SQLite powers the zero-setup demo; PostgreSQL is the deployment
target. Types are declared once here so no model has to care which one it is
running on.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum as PyEnum
from typing import Any
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.mutable import MutableDict, MutableList
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

# Deterministic constraint names. Alembic needs them to emit reproducible
# migrations, and SQLite's batch-ALTER needs them to rebuild a table without
# losing constraints it cannot name.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s",
    "pk": "pk_%(table_name)s",
}

# Single-tenant deployments still carry a tenant so multi-tenancy is a data
# change rather than a migration.
DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001"
DEFAULT_TENANT_SLUG = "default"


def new_id() -> str:
    """Return a fresh surrogate primary key."""

    return str(uuid4())


def utc_now() -> datetime:
    """Return the current time as a timezone-aware UTC datetime."""

    return datetime.now(UTC)


class UtcDateTime(sa.types.TypeDecorator):
    """A timestamp that is always timezone-aware UTC on the Python side.

    SQLite has no timezone-aware column type: its dialect drops the offset when
    writing and returns naive datetimes when reading, so ``DateTime(timezone=True)``
    is silently a no-op there. That leaves an application holding aware values
    from :func:`utc_now` alongside naive values loaded from the database, and
    subtracting one from the other raises ``TypeError``. Normalising in both
    directions removes the distinction entirely.
    """

    impl = sa.DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


def _json() -> sa.types.TypeEngine[Any]:
    """JSON that becomes JSONB on PostgreSQL and plain JSON elsewhere."""

    return sa.JSON().with_variant(JSONB, "postgresql")


# ``Mutable*`` wrappers make in-place edits (``row.items.append(...)``) dirty the
# instance. Without them SQLAlchemy compares the same object to itself, sees no
# change, and silently discards the write.
JSONDict = MutableDict.as_mutable(_json())
JSONList = MutableList.as_mutable(_json())


def enum_column(enum_type: type[PyEnum], name: str) -> sa.Enum:
    """Store a Python enum as its *value* in a CHECK-constrained VARCHAR.

    The enums live in ``app.schemas`` and are shared with the API contracts, so
    the database and the wire format cannot drift apart. ``validate_strings``
    rejects an unknown value at bind time; the CHECK constraint rejects one that
    reaches the database by any other route.
    """

    return sa.Enum(
        enum_type,
        name=name,
        native_enum=False,
        length=40,
        create_constraint=True,
        validate_strings=True,
        values_callable=lambda enum: [member.value for member in enum],
    )


class Base(DeclarativeBase):
    """Declarative base carrying the shared metadata and type mappings."""

    metadata = sa.MetaData(naming_convention=NAMING_CONVENTION)

    # Applied to every ``Mapped[...]`` annotation, so models get the portable
    # types by default and never restate them.
    type_annotation_map = {
        datetime: UtcDateTime,
        dict[str, Any]: JSONDict,
        list[str]: JSONList,
        list[dict[str, Any]]: JSONList,
    }

    def __repr__(self) -> str:
        identifier = getattr(self, "id", None)
        return f"<{type(self).__name__} id={identifier!r}>"


class IdMixin:
    """Surrogate string primary key, generated client-side."""

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=new_id)


class TimestampMixin:
    """Creation and modification timestamps maintained by the ORM."""

    created_at: Mapped[datetime] = mapped_column(default=utc_now, index=True)
    updated_at: Mapped[datetime] = mapped_column(default=utc_now, onupdate=utc_now)


class TenantMixin:
    """Tenant scoping for every row a customer could own."""

    @declared_attr
    @classmethod
    def tenant_id(cls) -> Mapped[str]:
        return mapped_column(
            sa.String(36),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            default=DEFAULT_TENANT_ID,
            index=True,
        )
