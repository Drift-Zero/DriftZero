# DriftZero backend

FastAPI service implementing DriftZero's first vertical slice:

```text
telemetry → health trajectory → diagnosis → recovery approval → execution → verification
```

The included recovery adapter and ShopAssist scenario are deterministic simulations. They never
modify an external model deployment.

## Run locally

Requires Python 3.12 or newer.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
python -m pip install -e ".[dev]"
uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000/docs` for the interactive OpenAPI documentation.

`production` and `prod` environments automatically protect management endpoints.
Configure distinct `DRIFTZERO_API_VIEWER_KEY`, `DRIFTZERO_API_OPERATOR_KEY`, and
`DRIFTZERO_API_ADMIN_KEY` secrets, then send the appropriate value as
`Authorization: Bearer <key>`. Viewer credentials are read-only, operators may
write but not delete, and administrators have full control. If production has no
management keys, protected routes return `503` instead of starting insecurely.
Set `DRIFTZERO_API_REQUIRE_AUTH=true` to enable the same behavior in staging.
The production OpenAPI UI is disabled.

Every response carries browser hardening headers. Requests are restricted by
`DRIFTZERO_API_MAX_REQUEST_BYTES`, throttled per credential or client by
`DRIFTZERO_API_RATE_LIMIT_PER_MINUTE`, and checked against
`DRIFTZERO_TRUSTED_HOSTS`. The built-in limiter is process-local; horizontally
scaled deployments must also enforce a shared limit at their gateway.

Recovery mutations are authenticated separately from read and telemetry routes.
For a local demo only, set `DRIFTZERO_RECOVERY_ALLOW_LOCAL_IDENTITY=true` and
send `X-DriftZero-Actor` plus `X-DriftZero-Role`. Hosted environments should set
distinct `DRIFTZERO_RECOVERY_OPERATOR_API_KEY` and
`DRIFTZERO_RECOVERY_ADMIN_API_KEY` secrets and send the selected secret as a
Bearer token. The server derives the role from the matched secret; JSON identity
fields are never trusted.

Initialize or reset the deterministic ShopAssist returns-policy scenario:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/demo/reset
```

The response contains a health trajectory of approximately `92 → 87 → 74 → 61`, a 30-minute
forecast of `48`, an evidence-backed `knowledge_freshness_failure` diagnosis, and an approval-gated
recovery plan.

## Important endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/healthz` | Service readiness |
| `POST` | `/api/v1/models` | Register a monitored AI system |
| `POST` | `/api/v1/shopassist/telemetry` | Legacy simulated-demo telemetry window (minimum 20 samples) |
| `POST` | `/api/v1/models/{model_id}/interactions/evaluate` | Evaluate raw interactions against approved evidence and record Health-v2 telemetry |
| `PATCH` | `/api/v1/models/{id}` | Update model metadata and retention |
| `POST` | `/api/v1/models/{id}/lifecycle` | Activate, pause, or retire a model |
| `POST` | `/api/v1/models/{id}/versions` | Register and activate controlled inputs |
| `GET` | `/api/v1/models/{id}/versions` | Read version and fingerprint history |
| `POST` | `/api/v1/models/{id}/versions/{version_id}/activate` | Reactivate a prior version |
| `GET` | `/api/v1/models/{id}/registration-status` | Validate monitoring readiness |
| `POST` | `/api/v1/models/{id}/telemetry` | Ingest normalized health dimensions |
| `GET` | `/api/v1/models/{id}/health` | Read health history and forecast |
| `POST` | `/api/v1/models/{id}/diagnoses` | Diagnose the latest deterioration |
| `GET` | `/api/v1/models/{id}/incidents` | List recent incidents for a model |
| `GET` | `/api/v1/incidents/{id}` | Read one incident and its lifecycle state |
| `POST` | `/api/v1/models/{id}/alert-rules` | Create an alert rule |
| `GET` | `/api/v1/models/{id}/alert-rules` | List a model's alert rules |
| `GET/PATCH/DELETE` | `/api/v1/alert-rules/{id}` | Manage one alert rule |
| `POST` | `/api/v1/models/{id}/alerts/evaluate` | Evaluate rules, including freshness |
| `GET` | `/api/v1/models/{id}/alerts` | List a model's alerts |
| `GET` | `/api/v1/alerts` | Read the cross-model notification feed |
| `GET` | `/api/v1/alerts/{id}` | Read alert evidence and lifecycle state |
| `POST` | `/api/v1/alerts/{id}/acknowledge` | Record an operator acknowledgement |
| `POST` | `/api/v1/alerts/{id}/resolve` | Resolve an alert with a reason |
| `GET` | `/api/v1/models/{id}/recovery/latest` | Read the recommended playbook |
| `POST` | `/api/v1/recovery/{id}/approve` | Record operator approval |
| `POST` | `/api/v1/recovery/{id}/reject` | Reject a recommended plan with rationale |
| `POST` | `/api/v1/recovery/{id}/execute` | Queue idempotent execution; returns `202` |
| `POST` | `/api/v1/recovery/{id}/cancel` | Cancel a plan that has not started |
| `POST` | `/api/v1/recovery/{id}/verify` | Queue verification against a snapshot |
| `POST` | `/api/v1/recovery/{id}/rollback` | Queue an idempotent rollback; returns `202` |
| `GET` | `/api/v1/recovery/{id}/commands` | Read durable command history |
| `GET` | `/api/v1/recovery/{id}/executions` | Read every action attempt and rollback |
| `GET` | `/api/v1/recovery/{id}/verification` | Read the latest verification verdict |
| `GET` | `/api/v1/recovery-commands/{id}` | Poll a queued command |
| `GET` | `/api/v1/models/{id}/audit` | Read the model's audit history |

## Register a model

Registration can create the model identity and its first controlled version in
one transaction:

```json
{
  "name": "SupportCopilot",
  "provider": "openai",
  "environment": "production",
  "description": "Answers support questions from the approved knowledge base.",
  "retention_days": 30,
  "actor": "owner@example.com",
  "initial_version": {
    "label": "release-1",
    "model_identifier": "gpt-production",
    "prompt_version": "support-prompt-v1",
    "configuration": {"temperature": 0.1, "max_tokens": 500},
    "tools": ["knowledge_search", "ticket_lookup"],
    "corpus_version": "support-2026-09",
    "evaluation_policy_version": "health-v1"
  }
}
```

DriftZero hashes the configuration and normalized tool set, then hashes the
complete set of controlled inputs into a stable version fingerprint. Creating
a new version closes the previous active interval. Activating an older version
closes the current one, preserving enough history to determine whether two
temporal stability runs are comparable.

`GET /api/v1/models/{id}/registration-status` distinguishes configuration from
traffic: `ready_for_telemetry` requires an active model with an active
fingerprinted version, while `monitoring_state` remains `awaiting_telemetry`
until a health snapshot arrives. Paused and retired models are not considered
ready. Retirement is terminal through the API.

Configuration values are hashed rather than copied into the audit log. Provider
secrets are not accepted by these endpoints and must eventually be supplied by
a dedicated secrets-manager integration.

## Database

SQLite is the zero-setup default. The schema is portable, so pointing
`DRIFTZERO_DATABASE_URL` at PostgreSQL requires no model changes; install the
driver with `python -m pip install -e ".[postgres]"`.

```bash
alembic upgrade head                              # apply migrations
alembic revision --autogenerate -m "describe it"  # after changing a model
```

Migrations are the source of truth for any database whose contents you intend
to keep. `Database.create_schema()` remains available for tests and throwaway
demos.

The data model, its enums, and the session dependency are documented in
[`docs/DATA_MODEL.md`](../docs/DATA_MODEL.md). Models live in `app/db/`;
`app/database.py` re-exports the original names so existing imports keep
working.

## Background workers

Unattended work runs as separate processes, not inside the API:

```bash
python -m app.alert_worker --once       # evaluate alert rules
python -m app.retention_worker --once   # apply each model's retention window
```

Omit `--once` to loop. Retention deletes traces older than a model's
`retention_days` and audits every deletion; the interval is
`DRIFTZERO_RETENTION_INTERVAL_SECONDS` (default 3600). Both workers open an
existing database and do not create the schema, so run migrations first.

## Health-score policy

All dimensions are normalized to `0–100`, where higher is healthier. The `health-v2` policy uses
published weights and renormalizes across available dimensions. It returns `insufficient_data`
instead of a score when sample size, request coverage, or weighted dimension coverage is too low.
Every snapshot retains its policy version, confidence, sample size, coverage, missing dimensions,
and whether the signal was observed, inferred, or simulated.

The MVP forecast uses the most recent observed slope with a variability-based interval. This is an
inspectable baseline, not a guarantee that an incident will occur.

## Alert rules

DriftZero supports five rule strategies:

| Strategy | Metric | Meaning |
| --- | --- | --- |
| `threshold` | `score` or a health dimension | A numeric metric crosses a boundary |
| `transition` | `state` | Health enters a target state |
| `trajectory` | `forecast_score` or `forecast_change_per_hour` | The projected trajectory crosses a boundary |
| `coverage` | `coverage` | Evaluation traffic coverage becomes inadequate |
| `evaluation_freshness` | `evaluation_age_minutes` | No recent evaluation has arrived |

Create a sustained groundedness rule:

```json
{
  "name": "groundedness degradation",
  "rule_type": "threshold",
  "metric": "groundedness",
  "comparator": "lt",
  "threshold": 70,
  "window_minutes": 30,
  "minimum_consecutive_windows": 2,
  "cooldown_minutes": 60,
  "severity": "high",
  "channel": "in_app",
  "actor": "reliability-owner"
}
```

Transition rules use `metric: "state"`, set `target_state` to `healthy`,
`warning`, or `critical`, and send both `comparator` and `threshold` as `null`.
Trajectory and freshness rules retain a numeric comparator and threshold.

Rules run automatically inside the telemetry transaction and are also checked
immediately when created or updated. A condition must hold for
`minimum_consecutive_windows` before firing. One active alert is kept per rule;
continued failure updates its evidence rather than creating alert spam.
Clearing the condition resolves it, and `cooldown_minutes` controls when the
same rule may fire again. Disabling or deleting a rule resolves active alerts,
while deleting preserves historical alert records.

Freshness rules need evaluation even when telemetry has stopped. Run the
dedicated worker alongside the API:

```bash
python -m app.alert_worker
```

It evaluates active models every
`DRIFTZERO_ALERT_EVALUATION_INTERVAL_SECONDS` (60 seconds by default), isolates
failures per model, and emits structured outcome counts. For a cron job or
container job, use `python -m app.alert_worker --once`. The equivalent HTTP
trigger is:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/models/MODEL_ID/alerts/evaluate \
  -H "Content-Type: application/json" \
  -d '{"actor":"alerting-scheduler"}'
```

The current delivery channel is `in_app`. Creating the alert sets
`notified_at`, and `GET /api/v1/alerts` provides the notification feed and
firing/acknowledged counts. External email, Slack, webhook, and paging delivery
are deliberately not claimed until authenticated delivery adapters exist.

## Configuration

Copy `.env.example` values into the deployment environment. Environment variables are read using
the `DRIFTZERO_` prefix. SQLite is the zero-setup default; set `DRIFTZERO_DATABASE_URL` to another
SQLAlchemy-compatible database URL for a persistent deployment.

To enable the Groq model workbench, set `DRIFTZERO_GROQ_API_KEY` on the backend.
The key is used only for model discovery and inference and is never returned to
the dashboard. DriftZero evaluates the resulting responses with deterministic
local calculations. See `docs/GROQ_EVALUATION.md` in the repository root for
the request flow and interpretation limits.

## Operational logging

The API writes one JSON object per line to stdout. Every HTTP response includes
`X-Request-ID` and `X-Correlation-ID`; callers may supply either header using up
to 128 letters, numbers, dots, underscores, colons, or hyphens. Invalid values
are replaced with a generated request ID. The same IDs flow into operational
logs and into audit events created during that request.

```json
{"timestamp":"2026-09-06T12:00:00+00:00","level":"info","logger":"driftzero.http","service":"driftzero-api","environment":"production","message":"request.completed","request_id":"request-123","correlation_id":"workflow-456","event":"http.request","http_method":"POST","http_route":"/api/v1/models","status_code":201,"duration_ms":24.7}
```

Request/response bodies, header values, SQL text, and bound query parameters are
not logged. Free-text messages and exception text are scrubbed for common direct
identifiers and secrets. Database errors are logged at `ERROR`, queries slower
than `DRIFTZERO_SLOW_QUERY_MS` at `WARNING`, and other query timings at `DEBUG`.

Set `DRIFTZERO_LOG_FILE` to also write rotating JSONL files. Rotation defaults
to five 10 MiB backups and is controlled by `DRIFTZERO_LOG_FILE_MAX_BYTES` and
`DRIFTZERO_LOG_FILE_BACKUP_COUNT`.

Distributed traces are opt-in:

```bash
python -m pip install -e ".[observability]"
export DRIFTZERO_OTEL_ENABLED=true
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
```

This instruments FastAPI and SQLAlchemy and exports spans through OTLP/HTTP.
If the optional packages are absent, the service remains available and records
an `opentelemetry.unavailable` warning instead of failing startup.

## Recovery control

Run the durable worker alongside the API:

```bash
python -m app.recovery_worker
```

Commands are persisted before execution, claimed with expiring leases, retried
with stable per-action idempotency keys, and moved to terminal success or failure.
Each action records the external operation ID, affected traffic, before/after
configuration, configuration verification, timeout, and rollback result.

The default adapter is a clearly labelled simulator. Configure a real HTTPS
control plane only from server-side environment variables:

```bash
export DRIFTZERO_RECOVERY_CONTROL_URL=https://control.example.internal
export DRIFTZERO_RECOVERY_CONTROL_TOKEN=replace-with-a-secret
```

The remote service must implement the allow-listed action endpoints, honor the
`Idempotency-Key` header, and explicitly confirm the applied configuration. A
real adapter never fabricates post-recovery telemetry: the plan remains
`verifying` until observed traffic supplies at least 50 requests, 90% coverage,
a healthy score, and no material quality, safety, latency, reliability, or cost
regression.

API-key roles are a deployable interim boundary, not managed user authentication.
Before a public multi-user deployment, add OIDC sessions, tenant-scoped
authorization, a secrets manager, adapter-specific permissions, and reviewed
rollback runbooks. Local identity is ignored in `production` even if its flag is
accidentally enabled.

## Verify

```bash
ruff check .
pytest
```

Autogenerated migrations under `alembic/versions/` are excluded from linting:
they are a historical record rather than hand-written source.
