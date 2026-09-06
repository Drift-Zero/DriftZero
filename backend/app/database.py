"""Backwards-compatible entry point for the persistence layer.

The models and session management moved into :mod:`app.db` when the schema grew
past a single file. This module re-exports the original public names so existing
imports keep working:

    from app.database import Database, MonitoredModel, HealthSnapshot

New code should prefer :mod:`app.db`, which also exposes the traces, incidents,
recovery execution, stability and governance tables. See ``docs/DATA_MODEL.md``.
"""

from __future__ import annotations

from app.db import (
    AuditEvent,
    Base,
    Database,
    Diagnosis,
    HealthSnapshot,
    MonitoredModel,
    RecoveryPlan,
    configure_database,
    get_database,
    get_session,
    new_id,
    utc_now,
)

__all__ = [
    "AuditEvent",
    "Base",
    "Database",
    "Diagnosis",
    "HealthSnapshot",
    "MonitoredModel",
    "RecoveryPlan",
    "configure_database",
    "get_database",
    "get_session",
    "new_id",
    "utc_now",
]
