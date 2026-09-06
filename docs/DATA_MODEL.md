# DriftZero data model

The contract between the persistence layer and everything above it. If you are
writing a service, a route or a seed script, this is the page you need.

- **Models and sessions:** `backend/app/db/`
- **Migrations:** `backend/alembic/`
- **Compatibility shim:** `backend/app/database.py` re-exports the original five
  model names, so existing imports keep working.

---

## Using it

```python
from app.db import HealthSnapshot, Incident, Trace, get_session
```

`app/db/__init__.py` exports every model, every enum, the session helpers and
the query helpers. Import from `app.db` in new code; `app.database` continues to
work and is kept deliberately.

### Sessions

```python
from fastapi import Depends
from sqlalchemy.orm import Session
from app.db import get_session

@router.get("/models/{model_id}/health")
def read_health(model_id: str, session: Session = Depends(get_session)):
    ...
```

`get_session` yields a request-scoped session, rolls back if the handler raises,
and closes when the request ends. **Committing is the caller's decision** — the
dependency never commits for you.

For scripts and background jobs use the transactional scope, which commits on
success and rolls back on failure:

```python
from app.db import get_database

with get_database().session_scope() as session:
    session.add(...)
```

`configure_database(url)` replaces the process-wide database (used by
`create_app` and tests); `reset_database()` disposes it.

---

## Shape

```mermaid
erDiagram
    tenants                ||--o{ monitored_models : owns
    monitored_models       ||--o{ model_versions : "fingerprints inputs"
    monitored_models       ||--o{ knowledge_sources : retrieves_from
    knowledge_sources      ||--o{ knowledge_documents : contains
    monitored_models       ||--o{ traces : produces
    monitored_models       ||--o{ health_snapshots : scored_as
    health_policies        ||--o{ health_snapshots : scored_by
    health_snapshots       ||--o{ health_forecasts : predicts
    monitored_models       ||--o{ incidents : degrades_into
    incidents              ||--o{ diagnoses : explained_by
    health_snapshots       ||--o{ diagnoses : evidenced_at
    diagnoses              ||--o{ diagnosis_evidence : supported_by
    diagnosis_evidence     }o--o{ traces : "drills down to"
    diagnoses              ||--o{ recovery_plans : recommends
    recovery_plans         ||--o{ recovery_actions : contains
    recovery_actions       ||--o{ recovery_executions : attempted_as
    recovery_plans         ||--o{ verification_runs : verified_by
    evaluator_versions     ||--o{ stability_tests : judged_by
    stability_tests        ||--o{ stability_variants : compares
    stability_variants     ||--o{ stability_claims : asserts
    alert_rules            ||--o{ alerts : fires
```

The path the product depends on is
`traces → health_snapshots → incidents → diagnoses → diagnosis_evidence → traces`.
That loop is what lets any number on screen be traced back to the requests
behind it.

---

## Tables

### Fleet and identity

| Table | Notes |
| --- | --- |
| `tenants` | One row in single-tenant deployments, created automatically by `create_schema()` and by migration `0001`. Do not delete it. |
| `monitored_models` | A system under observation. `name` is unique **per tenant**, not globally. Carries `retention_days`. |
| `model_versions` | The controlled-input fingerprint: model identifier, prompt version, config hash, tool-set hash, corpus version, evaluation policy. `comparable_with()` and `differences()` answer whether two runs may be compared. Required for a valid Temporal Stability Test. |

### Knowledge and retrieval

| Table | Notes |
| --- | --- |
| `knowledge_sources` | A corpus or index. `status` is `fresh` / `stale` / `disabled` — the target of the "refresh or disable stale source" recovery action. |
| `knowledge_documents` | `superseded_by_id` points at the newer document. That link is what makes "the retriever served a stale document" a citable fact rather than an assertion. |

### Pulse

| Table | Notes |
| --- | --- |
| `traces` | One request/response interaction. **Store redacted text only** — `question_redacted`, `answer_redacted`, plus `prompt_hash` / `answer_hash` and the `redaction_policy_version` that produced them. Never write raw prompts. |
| `health_policies` | Versioned weights, thresholds and gates. Mirrors `POLICY_VERSION` and `DIMENSION_WEIGHTS` in `app/scoring.py`; persist a row so the interface can show what a score weighted. |
| `health_snapshots` | A score over one window. Nine dimension columns, plus `window_start` / `window_end`, `sample_size`, `trace_count`, `coverage`, `confidence`, `policy_version` and `missing_dimensions`. `score` is nullable and **must** be null when `state` is `insufficient_data`. |
| `health_forecasts` | A stored prediction with `actual_score` backfilled once the horizon elapses, so forecasts can be checked for calibration. The ORM class is `HealthForecastRecord` (the Pydantic `HealthForecast` keeps its name). |

### Diagnose

| Table | Notes |
| --- | --- |
| `incidents` | Ties snapshot → diagnosis → recovery → verification into one story. |
| `diagnoses` | `rank` orders candidate causes; `confidence` is a probability in `[0, 1]` and `confidence_label` defaults to `"estimated"`. The `evidence` JSON column is kept for compatibility — prefer `evidence_items`. |
| `diagnosis_evidence` | One observation. `supports_diagnosis=False` records **contradicting** evidence, which is meant to be displayed, not filtered out. |
| `evidence_traces` | Link table. `evidence.traces` is the drill-down from a claim to the requests behind it. |

### Recover

Recommendation, approval, execution, verification and rollback are separate on
purpose:

| Stage | Where it lives |
| --- | --- |
| Recommendation | `recovery_plans` + `recovery_actions` |
| Approval | `recovery_plans.approved_at` / `approved_by` / `rejected_at` / `approval_level` |
| Execution | `recovery_executions` — one row per action attempt |
| Verification | `verification_runs` |
| Rollback | `recovery_executions.rolled_back_at` / `rollback_result` |

`recovery_executions` is what makes partial failure representable: three actions
succeeding and one timing out is four rows, each with its own actor, reason,
affected traffic, result and timeout. `recovery_plans.idempotency_key` is unique,
so a replayed approval cannot execute a playbook twice.

`verification_runs` carries all four parts of the definition of success:
`threshold`, the window, `required_requests`, and `no_regression_checks`.

### Signature evaluations

| Table | Notes |
| --- | --- |
| `evaluator_versions` | Pinned evaluator config, so a judgement can be replayed and an evaluator can be versioned. |
| `stability_tests` | `kind` is `semantic` or `temporal`. For temporal tests, set `inputs_changed` and `changed_inputs` when the fingerprint moved — annotate the change instead of reporting drift. |
| `stability_variants` | The paraphrases (semantic) or re-runs (temporal), each linkable to its trace. |
| `stability_claims` | Extracted material facts. Agreement is judged on `claim_key` / `value_text`, not on wording. |
| `evaluation_feedback` | Human agree/disagree against any diagnosis or test. |

### Governance

| Table | Notes |
| --- | --- |
| `audit_events` | Append-only. `entity_type` + `entity_id` are indexed, so you can pull the trail for one plan or one action. `model_id` is nullable for tenant-level events. |
| `alert_rules` / `alerts` | Threshold rules and their firing / acknowledged / resolved state. |
| `review_queue_items` | The human-review queue, and the target of the "send conflicts to human review" action. |

---

## Enums

Five vocabularies are shared with the API and imported from `app/schemas.py`:
`HealthState`, `SignalSource`, `DiagnosisStatus`, `RecoveryState`, `RiskLevel`.
The rest are in `app/db/enums.py`: `ModelStatus`, `KnowledgeStatus`,
`TraceStatus`, `Severity`, `IncidentState`, `ExecutionState`, `EvaluatorKind`,
`StabilityKind`, `StabilityVerdict`, `ReviewState`, `AlertState`, `ActorType`,
`FeedbackVerdict`.

All of them are stored as their **value** (`"insufficient_data"`, not
`"INSUFFICIENT_DATA"`) in a CHECK-constrained `VARCHAR(40)`. Assigning an
unknown value raises at bind time rather than being written. Import enums from
`app.db` rather than restating the strings.

---

## Migrations

```bash
cd backend
alembic upgrade head
alembic revision --autogenerate -m "describe the change"
alembic downgrade -1
```

`env.py` reads `DRIFTZERO_DATABASE_URL` through `app.config.Settings`, so a
migration always targets the database the service would open. Batch mode is
enabled on SQLite so ALTER-limited tables are rebuilt without losing
constraints.

A test asserts the migration and the models produce identical schemas, so a
model change without a migration fails the suite rather than drifting silently.

`Database.create_schema()` still exists for tests and throwaway demos. Use
Alembic for anything you intend to keep.

### PostgreSQL

The schema is portable — no model changes are needed.

```bash
python -m pip install -e "backend[postgres]"
export DRIFTZERO_DATABASE_URL="postgresql+psycopg://user:pass@localhost/driftzero"
cd backend && alembic upgrade head
```

JSON columns become `JSONB` and timestamps become `TIMESTAMP WITH TIME ZONE`
automatically. A test compiles the whole schema for PostgreSQL without needing a
server, so incompatibilities surface in CI.

---

## Adding a table

1. Add the class to `app/db/models.py`, in the section for its product layer.
2. Use `IdMixin` for the primary key, and `TenantMixin` if a customer owns the row.
3. Annotate timestamps as `Mapped[datetime]` — the type map applies `UtcDateTime`
   automatically. Do not use `sa.DateTime` directly.
4. Annotate JSON as `Mapped[dict[str, Any]]` or `Mapped[list[str]]`, which map to
   the mutation-tracking, JSONB-on-PostgreSQL types.
5. Export it from `app/db/__init__.py`.
6. `alembic revision --autogenerate -m "add <table>"`, then read the generated file.
7. `pytest` — the drift test will fail if you skipped step 6.

---

## Helpers

```python
from app.db import (
    ensure_default_tenant,   # bootstrap row; create_schema() already calls it
    latest_snapshot,         # most recent snapshot for a model
    snapshot_timeline,       # ascending (observed_at, score) pairs
    purge_expired_traces,    # retention, per model
    reset_all_data,          # delete every row in FK-safe order
)
```

`snapshot_timeline` is shaped for `app.scoring.forecast_health` and **excludes
unscored snapshots**, so an `insufficient_data` result is never read as a health
of zero.

`reset_all_data` derives its delete order from `metadata.sorted_tables`, so it
stays correct as tables are added. It preserves `tenants` and re-creates the
bootstrap row. Call it before seeding a demo; it writes no data of its own.

---

## Conventions and gotchas

**Timestamps are always aware UTC.** SQLite has no timezone-aware column type —
its dialect drops the offset on write and returns naive datetimes on read, so
`DateTime(timezone=True)` is silently a no-op there. `UtcDateTime` normalises in
both directions. Use `app.db.utc_now()`; never `datetime.now()` without a
timezone, and never `sa.DateTime` directly on a model.

**JSON columns track in-place mutation.** `snapshot.missing_dimensions.append(x)`
is persisted. Without the `Mutable*` wrappers it would not have been — SQLAlchemy
would compare the list to itself, see no change, and drop the write.

**Constraints are enforced by the database.** Scores are `0–100`, coverage and
confidence are `0–1`, `sample_size` is non-negative, `rank` and action `order`
are positive. A percentage passed where a probability belongs raises rather than
being stored.

**Cascades work at both levels.** `ondelete="CASCADE"` is in the DDL and the ORM
relationships use `cascade="all, delete-orphan"` with `passive_deletes=True`.
SQLite enforces foreign keys only because a `PRAGMA foreign_keys=ON` listener
runs on every connection.

**Redaction is not optional.** `traces` and `stability_*` store redacted text and
hashes. Do not add a column for raw prompt or response content.

---

## Notes for the API layer

`app/schemas.py` declares fields named `model_id` and `model`. Pydantic v2
protects the `model_` namespace and emits
`UserWarning: Field "model_id" has conflict with protected namespace "model_"`.
It is harmless, and silenced with one line on the affected models:

```python
model_config = ConfigDict(protected_namespaces=())
```

Left as-is deliberately — that file belongs to the API layer.

---

## Currently wired

`app/service.py` writes `monitored_models`, `traces`, `health_snapshots`,
`health_policies`, `diagnoses`, `diagnosis_evidence`, `evidence_traces`,
`knowledge_sources`, `knowledge_documents`, `recovery_plans` and `audit_events`.

**Traces and the drill-down.** `TelemetryCreate.traces` is optional; when
supplied, `_record_telemetry` redacts and stores each one, derives the
snapshot's `window_start`/`window_end` from the traffic they span, and records
`trace_count`. With no traces the window falls back to the configured horizon
ending at the observation, so a score always states its period. `policy_id`
links the snapshot to the `health-v1` row, so the weights behind a score are
visible.

`diagnose_latest` then writes one `diagnosis_evidence` row per observation and
links it, through `evidence_traces`, to the traces that demonstrate its metric
(`traces_for_metric`). Contradicting evidence is stored the same way as
supporting evidence. `EvidenceItem.trace_ids` exposes the drill-down on the
existing diagnosis response, so no extra route is needed.

Note that the stored link is a *set* of relevant traces, not a ranking: the
association table has no rank column, and `DiagnosisEvidence.traces` reads back
in chronological order.

**Redaction is enforced at the boundary.** `app/redaction.py` masks emails,
identifiers and phone numbers before storage and hashes the *original*, so
repeated questions stay correlatable without retaining what was asked. Every
trace records the `redaction_policy_version` that produced it. Do not add a
column for raw prompt or response content.

Still unwired, in the order worth adopting next:

1. **`incidents`** — needed for "recent incidents" on the fleet view, and it is
   what groups a diagnosis with its recovery and verification.
2. **`recovery_actions` + `recovery_executions`** — per-action execution, so
   partial failure and rollback are recorded rather than collapsed into a single
   `executed_at`.
3. **`verification_runs`** — records the threshold, window, request count and
   no-regression checks that define a successful recovery.
4. **`model_versions` + `stability_*`** — the signature evaluations.
