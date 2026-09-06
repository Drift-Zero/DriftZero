"""Engine ownership, session lifecycle and the FastAPI dependency."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.db.base import Base
from app.db.queries import ensure_default_tenant

IN_MEMORY_URLS = frozenset({"sqlite://", "sqlite:///:memory:"})


def normalize_database_url(database_url: str) -> str:
    """Select psycopg 3 for managed Postgres URLs that omit a driver."""

    if database_url.startswith("postgres://"):
        return database_url.replace("postgres://", "postgresql+psycopg://", 1)
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return database_url


class Database:
    """Owns the engine and creates short-lived sessions."""

    def __init__(self, database_url: str, *, echo: bool = False) -> None:
        database_url = normalize_database_url(database_url)
        self.database_url = database_url
        engine_kwargs: dict[str, Any] = {"echo": echo, "future": True}

        if database_url.startswith("sqlite"):
            # FastAPI serves requests from a thread pool, so the connection may
            # be handed to a different thread than the one that opened it.
            engine_kwargs["connect_args"] = {"check_same_thread": False}
        if database_url in IN_MEMORY_URLS:
            # Every connection must be the same connection, or each one gets its
            # own empty database.
            engine_kwargs["poolclass"] = StaticPool
        if database_url.startswith("postgresql"):
            engine_kwargs["pool_pre_ping"] = True

        self.engine: Engine = sa.create_engine(database_url, **engine_kwargs)
        self.session_factory = sessionmaker(
            bind=self.engine,
            class_=Session,
            expire_on_commit=False,
        )

        if database_url.startswith("sqlite"):
            sa.event.listen(self.engine, "connect", self._configure_sqlite)

    @staticmethod
    def _configure_sqlite(dbapi_connection: Any, _: Any) -> None:
        """SQLite ignores foreign keys unless asked, per connection."""

        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    def create_schema(self) -> None:
        """Create every table directly from the models, and bootstrap the tenant.

        Convenient for tests and throwaway demos. Use Alembic for any database
        whose contents you intend to keep.

        The default tenant is part of making the schema usable rather than demo
        data: every tenant-scoped table defaults its ``tenant_id`` to that row,
        so nothing can be inserted until it exists.
        """

        Base.metadata.create_all(self.engine)
        with self.session_factory() as session:
            ensure_default_tenant(session)
            session.commit()

    def drop_schema(self) -> None:
        Base.metadata.drop_all(self.engine)

    def session(self) -> Iterator[Session]:
        """Yield a session. Retained as a FastAPI dependency entry point."""

        with self.session_factory() as session:
            try:
                yield session
            except Exception:
                session.rollback()
                raise

    @contextmanager
    def session_scope(self) -> Iterator[Session]:
        """Transactional scope for scripts and background jobs."""

        with self.session_factory() as session:
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise

    def dispose(self) -> None:
        self.engine.dispose()


_database: Database | None = None


def configure_database(database_url: str | None = None) -> Database:
    """Create the process-wide database, replacing any existing one."""

    global _database
    if _database is not None:
        _database.dispose()
    _database = Database(database_url or Settings.from_env().database_url)
    return _database


def get_database() -> Database:
    """Return the process-wide database, creating it from settings on first use."""

    global _database
    if _database is None:
        _database = Database(Settings.from_env().database_url)
    return _database


def reset_database() -> None:
    """Dispose of the process-wide database. Intended for test teardown."""

    global _database
    if _database is not None:
        _database.dispose()
    _database = None


def get_session() -> Iterator[Session]:
    """FastAPI dependency yielding a request-scoped session.

    Usage::

        @router.get("/models")
        def list_models(session: Session = Depends(get_session)) -> list[ModelResponse]:
            ...

    The session is closed when the request ends and rolled back if the handler
    raises. Committing is the caller's decision.
    """

    yield from get_database().session()
