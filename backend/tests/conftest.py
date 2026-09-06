"""Shared fixtures for the persistence tests."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.db import (
    Database,
    HealthSnapshot,
    HealthState,
    MonitoredModel,
    SignalSource,
    ensure_default_tenant,
    utc_now,
)


@pytest.fixture
def database() -> Iterator[Database]:
    """An isolated in-memory database with the schema applied."""

    db = Database("sqlite://")
    db.create_schema()
    yield db
    db.dispose()


@pytest.fixture
def session(database: Database) -> Iterator[Session]:
    with database.session_factory() as session:
        ensure_default_tenant(session)
        session.commit()
        yield session


@pytest.fixture
def model(session: Session) -> MonitoredModel:
    model = MonitoredModel(name="CampusGPT", provider="openai", environment="production")
    session.add(model)
    session.commit()
    return model


def make_snapshot(
    model_id: str,
    *,
    observed_at: datetime | None = None,
    score: float | None = 92.0,
    state: HealthState = HealthState.HEALTHY,
) -> HealthSnapshot:
    """Build a valid snapshot; tests override only what they are exercising."""

    now = observed_at or utc_now()
    return HealthSnapshot(
        model_id=model_id,
        observed_at=now,
        window_start=now - timedelta(minutes=15),
        window_end=now,
        score=score,
        state=state,
        confidence=0.8,
        sample_size=120,
        coverage=0.9,
        policy_version="health-v1",
        source=SignalSource.SIMULATED,
    )
