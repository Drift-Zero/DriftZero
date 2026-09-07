# DriftZero

**Detect AI reliability degradation early. Diagnose it with evidence. Recover with verification.**

DriftZero is an early-warning reliability monitoring and recovery platform for deployed AI systems. It turns normalized evaluation telemetry into health scores, forecasts, incidents, diagnoses, controlled recovery workflows, and an auditable record of what happened. The repository currently provides a working, deterministic vertical slice designed for development and demonstration—not a production-ready control plane.

## The problem

AI applications can degrade without a conventional service outage. Hallucinations, grounding failures, inconsistent outputs, prompt or configuration changes, retrieval and data changes, latency regressions, safety failures, and model or data drift can all reduce reliability while the application remains online.

DriftZero helps operators detect these changes early, inspect the evidence behind them, coordinate a proportionate response, and determine whether the response actually improved observed behavior.

## What DriftZero does

DriftZero organizes the reliability lifecycle around a common telemetry contract:

```text
AI application
    → evaluator / telemetry collector
    → normalized telemetry and redacted trace evidence
    → DriftZero Telemetry API
    → Health Score and forecast
    → incident detection and diagnosis
    → approved recovery actions
    → verification against new telemetry
```

Recovery is a lifecycle rather than a button click. A plan can be recommended, approved or rejected, queued, executed, verified, and rolled back. For observed traffic, verification requires post-execution telemetry that meets configured request and coverage gates; a plan is not marked recovered simply because its actions ran.

## Key features

- **Model registry and versioning** — register monitored systems, track lifecycle state, and fingerprint model, prompt, tool, corpus, and evaluation-policy versions.
- **Telemetry ingestion** — accept provider-neutral health dimensions and optional request-level traces through a versioned API.
- **Owner connector evaluation** — capture interactions from any hosted or local model, verify claims against approved evidence with deterministic rules, and derive auditable health windows.
- **Live evidence URLs** — fetch public direct data URLs, preserve provenance, detect changes, and require approval before a new version replaces trusted evidence.
- **Privacy-aware evidence** — redact prompt and response text before storage while retaining hashes, safe trace fields, and configurable retention periods.
- **Model Health Score** — combine available reliability dimensions into a transparent score with state, confidence, sample size, coverage, policy version, and missing-dimension reporting.
- **Health history and forecasting** — store health snapshots and short-horizon forecasts, then record forecast outcomes when the horizon passes.
- **Incident detection and diagnosis** — open incidents from degraded health and generate rule-based probable causes with supporting and contradicting evidence linked to relevant traces.
- **Alerting** — define threshold, transition, trajectory, coverage, and evaluation-freshness rules with an in-application alert feed and acknowledgement/resolution states.
- **Recovery lifecycle** — recommend playbooks, enforce approval and role checks, queue idempotent commands, execute through an adapter, record action attempts, and support cancellation and rollback.
- **Recovery verification** — evaluate new telemetry against health, request-count, coverage, and no-regression checks before resolving an incident.
- **Stability evaluation** — run semantic and temporal stability tests, preserve evaluator versions, distinguish changed inputs from unexplained drift, and retain claim-level disagreements.
- **Human review and feedback** — route selected work to a review queue and record human agreement or disagreement with automated judgments.
- **Audit history** — record model, telemetry, alert, diagnosis, recovery, verification, and governance events.
- **Dashboard** — explore fleet health, models, model details, incidents, events, recovery state, and deterministic demo controls in a React interface.
- **Dashboard settings** — set the operator identity used for audited actions, repoint the dashboard at another API and test it before committing, switch between demo and live data, enable background refresh, manage alert rules and per-model retention and lifecycle, tune density, timestamp, and precision formatting, and export, import, or reset the whole configuration.
- **Groq evaluation workbench** — discover and import a Groq model with a server-owned key, capture real responses, then calculate transparent evidence, safety, stability, reliability, latency, cost, and health metrics locally without an evaluator-model call.

## Architecture

```text
Users
  ↓
AI application ───────────────→ Hosted, local, or custom model
  ↓
Evaluator / telemetry collector / connector
  ↓
POST /api/v1/models/{model_id}/interactions/evaluate
  ↓
FastAPI service
  ├── trace redaction and signal inference
  ├── Health Score and confidence
  ├── forecast storage and settlement
  ├── incident detection and diagnosis
  ├── alert evaluation
  └── recovery verification queueing
  ├──────────────→ SQLAlchemy data layer → SQLite by default
  │                      ↑                 (PostgreSQL driver optional)
  │                      │
  │                Background workers
  │                  ├── alert evaluation
  │                  ├── recovery command execution
  │                  └── trace retention
  │
  └──────────────→ Versioned read/control API ← React dashboard
```

The Docker Compose stack runs the API, dashboard, alert worker, recovery worker, and retention worker. Nginx serves the Vite production build and proxies same-origin `/api/` requests to FastAPI.

## Model-agnostic design

DriftZero is designed around the behavior of a monitored application, not a particular model vendor. The monitored system may use a hosted LLM, a local LLM, or another custom AI model. A connector or evaluator maps provider-specific observations into the common telemetry contract and sends them to:

```http
POST /api/v1/models/{model_id}/telemetry
```

The owner connector sends raw application observations—not invented scores—to the interaction endpoint. DriftZero verifies factual claims against approved evidence and derives groundedness, quality, reliability, latency, safety, sample size, and coverage. Applications with their own domain evaluator can continue sending normalized `0–100` dimensions directly to the telemetry endpoint.

See [`docs/HEALTH_EVENT_SCHEMA.md`](docs/HEALTH_EVENT_SCHEMA.md) for the current contract.
See [`docs/CONNECTIONS.md`](docs/CONNECTIONS.md) for GitHub, telemetry, website, and API
onboarding, credential handling, and connection checks.
See [`docs/GROQ_EVALUATION.md`](docs/GROQ_EVALUATION.md) for the server-side Groq import and deterministic evaluation flow.
See [`docs/OWNER_CONNECTOR.md`](docs/OWNER_CONNECTOR.md) for live URL evidence and hosted or local model integration.

## Evaluation layer

The evaluator answers: **How did this model or application behave?**

DriftZero answers: **Is that behavior degrading over time, what evidence points to the cause, and did recovery work?**

Upstream evaluators can combine deterministic task measurements, latency and error signals, grounding checks, safety results, drift statistics, task-specific tests, and optional model-based judgments. They are responsible for normalizing those observations before ingestion. When groundedness or drift is omitted but suitable trace evidence is present, the backend can infer those two dimensions from stored trace signals and historical windows.

The built-in semantic and temporal stability evaluator is a deterministic simulated adapter for the repository's demo scenario. It generates paraphrases or controlled re-runs, extracts material claims, compares agreement, versions its judgments, and records confidence. It does not call an external model. The adapter boundary is intended to support real evaluators later without coupling DriftZero's reliability pipeline to one provider.

## Model Health

The Model Health Score is a policy-versioned summary of available signals, not an objective statement about a model. The current `health-v2` policy uses these dimensions, where higher always means healthier:

- quality
- groundedness
- semantic stability
- safety
- operational reliability
- latency health
- cost health

The backend calculates a weighted score from the dimensions that are present and reports missing dimensions explicitly. It also derives confidence from traffic coverage, sample size, and available dimension coverage. By default, fewer than 20 samples, less than 30% traffic coverage, or insufficient dimension weight produces an `insufficient_data` state instead of a misleading score.

The published weights are quality 25%, groundedness 20%, reliability 20%, semantic consistency 15%, safety 10%, latency 5%, and cost efficiency 5%. Temporal stability and drift remain available diagnostic signals but are not inputs to the `health-v2` aggregate.

Health snapshots preserve the evidence window and scoring policy. The current forecast is an inspectable short-horizon slope projection with a variability-based interval; it is a baseline forecast, not a guarantee of a future incident.

## Incident → recovery → verification

```text
Healthy
  → degradation detected
  → incident opened
  → diagnosis generated with evidence
  → recovery plan recommended
  → approval and durable execution
  → verification against post-action telemetry
  → recovered, failed, or rolled back
```

Diagnosis is currently deterministic and rule-based. It can identify supported patterns such as knowledge freshness failures, safety regressions, operational reliability failures, and semantic or temporal instability; otherwise it reports insufficient evidence.

The default recovery adapter is clearly marked as simulated. The backend also contains an optional HTTPS control-plane adapter, disabled unless server-side configuration is supplied. Recovery commands are persisted before execution, claimed by a worker, retried with stable idempotency keys, and audited. Verification checks a healthy threshold, evidence volume, coverage, and material regressions in quality, safety, latency, reliability, and cost.

## Demo and reference application

[`shop-assist/`](shop-assist/) is the current reference application. It is an e-commerce support assistant with deterministic scenarios for stale return policies, inventory mismatch, expired promotions, outdated warranties, conflicting shipping guidance, and recovery. Its presenter console makes these states repeatable for demonstrations.

ShopAssist is not the core DriftZero product. It uses a deterministic local answer path and can optionally call Groq through a server-side route when `GROQ_API_KEY` is configured. The key is never sent to browser code. Its server route evaluates observed answers, batches 20 interactions, and posts one normalized telemetry window to DriftZero. Failed delivery remains buffered in the server process for retry.

The backend also retains a deterministic CampusGPT knowledge-freshness fixture for API, stability, recovery, and test coverage. Both scenarios are simulations and do not modify a real model deployment.

## Screenshots

Dashboard screenshots and demo visuals will be added once the frontend is finalized.

## Tech stack

- **Backend:** Python 3.12+, FastAPI, Pydantic, SQLAlchemy, Alembic, Uvicorn
- **Data:** SQLite for the zero-setup demo; optional PostgreSQL driver support
- **Dashboard:** React, TypeScript, Vite, React Router, Recharts, Lucide React
- **Reference app:** Next.js, React, TypeScript, Tailwind CSS, optional server-side Groq request path
- **Quality:** Pytest, Ruff, ESLint, TypeScript compiler, Node test runner
- **Deployment:** Docker, Docker Compose, Nginx, background worker processes

## Repository structure

```text
DriftZero/
├── backend/        FastAPI service, data layer, workers, migrations, and tests
├── frontend/       React/Vite operations dashboard and Nginx configuration
├── shop-assist/    Deterministic e-commerce reference application
├── examples/       Provider-neutral connector example
├── docs/           Product, schema, data-model, demo, and operations documentation
├── scripts/        End-to-end smoke-test tooling
├── deploy/         Single-container demo deployment files
├── .github/        Continuous-integration workflow
├── compose.yaml    Local multi-service stack
└── render.yaml     Render demo blueprint
```

## Getting started

### Clone the repository

```bash
git clone https://github.com/Drift-Zero/DriftZero.git
cd DriftZero
```

### Run the full local stack with Docker

Requirements: Docker Engine and Docker Compose v2.

```bash
cp .env.example .env
docker compose up --build
```

Open the dashboard at <http://localhost:3000>, ShopAssist at
<http://localhost:3100>, and the API documentation at <http://localhost:8000/docs>.

Run the deterministic end-to-end recovery smoke test:

```bash
python3 scripts/smoke_test.py
```

Stop the stack without deleting its database:

```bash
docker compose down
```

See [`docs/DEVOPS_RUNBOOK.md`](docs/DEVOPS_RUNBOOK.md) for service wiring, logs, troubleshooting, and deployment notes.

### Run the full local stack without Docker

Requirements: Python 3.12 or newer with the backend dependencies installed, and Node.js with
`frontend/node_modules` present (see the two sections below for the one-time setup).

```bash
python scripts/run_local.py
```

That starts seven processes and shuts them all down together on Ctrl+C:

| Service | URL | Role |
| --- | --- | --- |
| API | <http://127.0.0.1:8000> | REST surface, OpenAPI docs at `/docs` |
| Recovery worker | — | Applies approved recovery plans and records verification |
| Alert worker | — | Evaluates alert rules |
| Retention worker | — | Removes traces beyond each model's retention window |
| Evidence sync worker | — | Rechecks opted-in URL sources and versions changed content |
| Dashboard | <http://localhost:5173> | Operator view: health, incidents, recovery |
| ShopAssist | <http://localhost:3000> | The monitored chatbot; presenter controls at `/demo` |

It also seeds the deterministic ShopAssist scenario, writes `frontend/.env.local` so the
dashboard talks to the API it just started, and sets `DRIFTZERO_API_URL` for ShopAssist so its
telemetry flows back to that same API. Every twenty chat interactions become one health
snapshot, which is what drives the dashboard's incidents.

The recovery worker is what makes **Approve & apply recovery** complete. Approving a plan only
queues a command, so an API running on its own leaves every recovery stuck in `queued`.

ShopAssist needs no model credentials — without `GROQ_API_KEY` it answers from its local
grounded fallback, with citations. Set the key in `shop-assist/.env.local` to route through Groq
instead.

Useful flags:

| Flag | Purpose |
| --- | --- |
| `--api-port` / `--dashboard-port` / `--shop-assist-port` | Move off the 8000 / 5173 / 3000 defaults when they are taken. |
| `--no-seed` | Keep the existing database instead of reseeding the demo scenario. |
| `--no-dashboard` / `--no-shop-assist` | Leave one of the web apps out. |
| `--database` | Point at a different SQLAlchemy URL. |

Next.js allows only one dev server per project directory, so stop any existing
`shop-assist` dev server before starting this one.


### Run the backend directly

Requires Python 3.12 or newer.

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
uvicorn app.main:app --reload
```

The API starts at <http://127.0.0.1:8000>. For the complete asynchronous lifecycle, run `python -m app.alert_worker`, `python -m app.recovery_worker`, and `python -m app.retention_worker` in separate backend terminals as needed.

### Run the dashboard directly

```bash
cd frontend
npm install
npm run dev
```

The frontend defaults to its deterministic demo mode. Copy [`frontend/.env.example`](frontend/.env.example) to `frontend/.env.local` to change the mode or API base URL. The Docker stack avoids CORS through its same-origin Nginx proxy. Running Vite against FastAPI directly is cross-origin, so the backend allows `localhost:5173` and `127.0.0.1:5173` outside production; set `DRIFTZERO_CORS_ORIGINS` for any other port. Privileged recovery actions also need a credential — either run the API with `DRIFTZERO_RECOVERY_ALLOW_LOCAL_IDENTITY=true` or set `VITE_RECOVERY_API_KEY`. `scripts/run_local.py` configures both for you.

### Run ShopAssist

ShopAssist requires the Node version declared in its package configuration.

```bash
cd shop-assist
npm install
npm run dev
```

Open <http://localhost:3000> for the customer experience or <http://localhost:3000/demo> for presenter controls. See [`shop-assist/README.md`](shop-assist/README.md) for its current behavior and telemetry setup.

### Send sample telemetry

With the backend running:

```bash
python3 examples/connectors/send_sample_telemetry.py --base-url http://localhost:8000
```

The example registers a synthetic model and submits one normalized health window. It requires no model-provider API key.

## Deploying to Vercel

Both web apps ship a `vercel.json`, and neither is a repository-root project, so each needs its
own Vercel project with **Root Directory** set:

| Vercel project | Root Directory | Framework |
| --- | --- | --- |
| Dashboard | `frontend` | Vite |
| ShopAssist | `shop-assist` | Next.js |

The API is not deployed to Vercel; it runs on Render from [`render.yaml`](render.yaml).

Set these in each project's environment variables. Both default to `127.0.0.1` in code, so a
deployment that omits them builds successfully and then fails at runtime against localhost:

| Project | Variable | Value |
| --- | --- | --- |
| Dashboard | `VITE_API_BASE_URL` | The Render service URL, e.g. `https://driftzero-demo.onrender.com` |
| Dashboard | `VITE_DEMO_MODE` | `false` for live data, `true` for the offline demo |
| ShopAssist | `DRIFTZERO_API_URL` | The same Render service URL |
| ShopAssist | `GROQ_API_KEY` | Optional; without it ShopAssist uses its local grounded fallback |
| ShopAssist | `SHOPASSIST_PUBLIC_URL` | The public ShopAssist origin used for social metadata |

`frontend/.env.local` is gitignored, so whatever the local stack writes there does not reach a
deployment — the Vercel values are the only ones that apply.

The API's `DRIFTZERO_CORS_ORIGIN_REGEX` in `render.yaml` already allows `https://*.vercel.app`.
Recovery approval works against that deployment because it sets
`DRIFTZERO_RECOVERY_ALLOW_LOCAL_IDENTITY=true`; leave `VITE_RECOVERY_API_KEY` unset.

## Environment variables

Copy the relevant example file before changing local configuration. Never commit real credentials.

- **Root Docker stack:** `DRIFTZERO_DASHBOARD_PORT`, `DRIFTZERO_API_PORT`, `DRIFTZERO_DATABASE_URL`, `DRIFTZERO_API_PREFIX`, `DRIFTZERO_ENVIRONMENT`
- **API security:** `DRIFTZERO_API_REQUIRE_AUTH`, `DRIFTZERO_API_VIEWER_KEY`, `DRIFTZERO_API_OPERATOR_KEY`, `DRIFTZERO_API_ADMIN_KEY`, `DRIFTZERO_API_RATE_LIMIT_PER_MINUTE`, `DRIFTZERO_API_MAX_REQUEST_BYTES`, `DRIFTZERO_TRUSTED_HOSTS`, `DRIFTZERO_DOCS_ENABLED`
- **Scoring and workers:** `DRIFTZERO_MINIMUM_SAMPLE_SIZE`, `DRIFTZERO_MINIMUM_COVERAGE`, `DRIFTZERO_FORECAST_HORIZON_MINUTES`, `DRIFTZERO_ALERT_EVALUATION_INTERVAL_SECONDS`, `DRIFTZERO_RECOVERY_WORKER_INTERVAL_SECONDS`, `DRIFTZERO_RETENTION_INTERVAL_SECONDS`
- **Recovery:** `DRIFTZERO_RECOVERY_ALLOW_LOCAL_IDENTITY`, `DRIFTZERO_RECOVERY_OPERATOR_API_KEY`, `DRIFTZERO_RECOVERY_ADMIN_API_KEY`, `DRIFTZERO_RECOVERY_CONTROL_URL`, `DRIFTZERO_RECOVERY_CONTROL_TOKEN`
- **Connections:** `DRIFTZERO_CONNECTION_SECRET_KEY`, `DRIFTZERO_CONNECTION_CHECK_TIMEOUT_SECONDS`
- **Evidence ingestion:** `DRIFTZERO_EVIDENCE_MAX_FILE_BYTES`, `DRIFTZERO_EVIDENCE_LLM_PROVIDER`, `DRIFTZERO_EVIDENCE_LLM_MODEL`, `DRIFTZERO_EVIDENCE_LLM_TIMEOUT_SECONDS`, plus server-only `GEMINI_API_KEY` or `DRIFTZERO_GROQ_API_KEY`
- **Observability:** `DRIFTZERO_LOG_LEVEL`, `DRIFTZERO_OTEL_ENABLED`, `OTEL_EXPORTER_OTLP_ENDPOINT`
- **Dashboard:** `VITE_API_BASE_URL`, `VITE_DEMO_MODE`, `VITE_RECOVERY_API_KEY`, `VITE_RECOVERY_ACTOR`, `VITE_RECOVERY_ROLE`
- **ShopAssist:** `DRIFTZERO_API_URL`, `SHOPASSIST_PUBLIC_URL`, `GROQ_API_KEY`; `GEMINI_API_KEY` may also be used server-side by the evidence-ingestion service

`GROQ_API_KEY` and DriftZero recovery credentials are server-side secrets. They must not be
exposed through `NEXT_PUBLIC_` variables or committed environment files. Note that every
`VITE_` variable is inlined into the dashboard's public bundle at build time, so
`VITE_RECOVERY_API_KEY` is readable by anyone who loads the page: prefer running the API
with `DRIFTZERO_RECOVERY_ALLOW_LOCAL_IDENTITY=true`, which needs no key.

Production API behavior is fail-closed: every management route requires a configured
viewer, operator, or administrator Bearer key, interactive API docs are disabled, telemetry
must have a registered ingestion connection, and untrusted host headers are rejected. Viewer
keys are read-only, operator keys may mutate but not delete, and administrator keys may delete
or reset demo state. Never put these management keys in a browser bundle; place a real user-auth
gateway or backend-for-frontend in front of DriftZero for a multi-user deployment. The
`hackathon-demo` environment remains explicitly keyless so the public demonstration works.

For multi-user deployments, DriftZero also provides `POST /api/v1/auth/register`,
`/login`, `/logout`, and `/me`. Passwords are Argon2id hashes; browser sessions are opaque,
revocable, `HttpOnly`, `SameSite=Lax` cookies; and every cookie-authenticated mutation requires
an in-memory `X-CSRF-Token`. Registration creates an isolated tenant and administrator membership.
Production registration requires `DRIFTZERO_AUTH_REGISTRATION_TOKEN`. Dashboard health projections
are cached only in tenant-namespaced, short-lived server memory and are invalidated on telemetry
writes; credentials, tokens, and passwords are never cacheable.

## API overview

The FastAPI service exposes versioned groups for:

- model registry, lifecycle, and controlled versions
- telemetry ingestion, traces, health timelines, and forecast history
- incidents and evidence-backed diagnoses
- alert rules, alert evaluation, and the in-application notification feed
- recovery plans, approval decisions, durable commands, execution, verification, cancellation, and rollback
- review queues and evaluation feedback
- semantic and temporal stability tests
- per-model audit history
- deterministic demo reset

Interactive OpenAPI documentation is available at `/docs` when the backend is running, normally <http://127.0.0.1:8000/docs>. The API prefix defaults to `/api/v1`; service readiness is exposed separately at `/healthz`.

## Project status

DriftZero is under active development. The repository implements and tests a substantial end-to-end demo lifecycle: registry and versioning, telemetry and trace storage, health scoring, forecasts, incidents, diagnosis, alerts, recovery command processing, verification, stability evaluation, human feedback, audit history, and a dashboard with independent demo data.

Important current boundaries:

- the default evaluator and recovery adapter are deterministic simulations;
- ShopAssist is a reference application, not a production commerce assistant;
- the default database is SQLite and the current service model is intended for a local or single-host demo;
- recovery authentication uses local demo identity or interim operator/admin API keys rather than managed OIDC;
- the alert delivery channel is currently in-application only;
- direct standalone browser/API development still needs CORS configuration;
- the single-container Render deployment files should be revalidated against the current Vite frontend build before use.

Do not attach consequential production credentials or recovery permissions to the demo configuration.

Website reference sources can also be refreshed into source-verifiable JSON on a schedule, with
optional xAI/Grok structuring. See [`docs/WEBSITE_SYNC.md`](docs/WEBSITE_SYNC.md) for the trust
boundary, configuration, API, and worker behavior.

## Roadmap

- Add production evaluator and model/provider connectors behind the existing adapter boundaries.
- Provide SDK instrumentation for common application and agent frameworks.
- Make health and evaluation policies configurable per monitored system.
- Expand task-specific and model-assisted evaluator strategies with calibration and replay.
- Add authenticated external alert delivery and observability integrations.
- Replace demo authentication with managed identity and tenant-scoped authorization.
- Support managed PostgreSQL, horizontally scalable workers, and production deployment patterns.
- Improve team workflows, collaboration, and operational reporting.

## Team

Built by the DriftZero team.

<!-- Add team member names and roles here -->

## License

DriftZero is available under the [MIT License](LICENSE).
