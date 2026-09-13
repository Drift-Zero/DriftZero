# DriftZero

**AI reliability monitoring platform for deployed LLM applications.**

DriftZero captures real application interactions, checks model responses against approved
evidence, calculates transparent reliability metrics and a policy-versioned Health-v2 score,
and opens incidents when behavior degrades.

The recommended way to evaluate this repository is to clone it and run the complete system
locally with Docker Compose.

## The problem

LLM applications can remain online while their answers become less reliable. A model may use
stale information, contradict a trusted source, invent a product detail, return the wrong record,
or report an incorrect number without producing a conventional service outage.

DriftZero makes those behavioral failures observable. It records what the application actually
returned, verifies factual claims against evidence the operator approved, stores the resulting
metrics and traces, and turns material degradation into a health state and incident.

## Validated demo

[`shop-assist/`](shop-assist/) is the reference application. It is a Next.js commerce assistant
that calls Groq's `openai/gpt-oss-120b` model through a server-side route and sends batches of 20
raw interactions to DriftZero.

The following result was validated end to end:

| Window | Health-v2 | Quality | Groundedness | Samples | Source |
| --- | ---: | ---: | ---: | ---: | --- |
| Healthy Groq traffic | **83.9 · HEALTHY** | 60 | 85.71 | 20 | `observed` |
| Controlled Wrong Number fault | **63.4 · CRITICAL** | 35 | 35 | 20 | `simulated` |

In the degraded run, the correct AeroBuds price was `$119` and the controlled response reported
`$129`. The Groq API calls were real; the incorrect context was deliberately injected by the
ShopAssist Presenter Console. DriftZero therefore labels the faulted window `simulated` and does
not pretend that Groq failed organically. The critical window opened a HIGH incident.

## Architecture

```text
Customer
  │
  ▼
ShopAssist (Next.js) ───────────────► Groq openai/gpt-oss-120b
  │                                      │
  │                                      └── real model response
  │
  └── every 20 interactions
          │
          ▼
POST /api/v1/models/{model_id}/interactions/evaluate
          │
          ▼
DriftZero API (FastAPI)
  ├── search approved evidence
  ├── verify response claims
  ├── derive quality, groundedness, reliability, latency, safety and cost signals
  ├── redact and persist request traces
  ├── calculate Health-v2
  ├── detect degradation and create incidents
  └── expose health, evidence, incident and audit APIs
          │
          ├────────► SQLite named volume
          │
          ├────────► alert / recovery / retention workers
          ├────────► evidence-sync / website workers
          │
          └────────► React dashboard
```

The local stack contains eight services: the API, dashboard, ShopAssist, alert worker, recovery
worker, retention worker, evidence-sync worker, and website worker. Docker Compose gives the
backend services a shared persistent SQLite volume and keeps the Presenter Console and chat route
inside one ShopAssist process, making the controlled scenario repeatable.

## Quick start

### Requirements

- Git
- Docker Engine or Docker Desktop
- Docker Compose v2
- A Groq API key belonging to the reviewer
- `curl` for the one-time local model registration command

### 1. Clone the repository

```bash
git clone https://github.com/Drift-Zero/DriftZero.git
cd DriftZero
```

### 2. Create the local environment file

```bash
cp .env.example .env
```

Open the root `.env` file in your editor and set these two server-side variables to your own Groq
key:

```dotenv
GROQ_API_KEY=your_groq_key_here
DRIFTZERO_GROQ_API_KEY=your_groq_key_here
```

`GROQ_API_KEY` enables real ShopAssist answers. `DRIFTZERO_GROQ_API_KEY` enables backend Groq
features such as optional webpage structuring. The same Groq key can be used for both. JSON
evidence in the walkthrough below is parsed deterministically and does not require an evaluator
model.

The root `.env` file is gitignored. Never commit it, paste a real key into documentation, or expose
the key through a `NEXT_PUBLIC_` or `VITE_` variable.

### 3. Start the complete stack

```bash
docker compose up --build
```

Wait until the API and web services report healthy. In another terminal, you can check them with:

```bash
docker compose ps
```

### 4. Register ShopAssist once

A fresh database intentionally starts empty. Register the monitored application before sending
interactions:

```bash
curl --fail --silent --show-error \
  --output /dev/null \
  --request POST http://localhost:8000/api/v1/models \
  --header 'Content-Type: application/json' \
  --data '{
    "name": "ShopAssist",
    "provider": "groq",
    "environment": "local-demo",
    "description": "Local ShopAssist reliability demonstration",
    "initial_version": {
      "label": "shopassist-groq-demo",
      "model_identifier": "openai/gpt-oss-120b",
      "prompt_version": "shopassist-grounded-v1",
      "corpus_version": "shopassist-local-evidence",
      "evaluation_policy_version": "health-v2",
      "actor": "local-reviewer"
    },
    "actor": "local-reviewer"
  }'
```

Run this only for a fresh database. ShopAssist resolves the unique model named `ShopAssist`
automatically, so `DRIFTZERO_MODEL_ID` can remain empty.

### 5. Approve the local evidence fixtures

Open the dashboard's **Evidence** page at <http://localhost:3000/evidence>. Select `ShopAssist`,
upload each file below, and choose **Use as truth** after every import:

- [`examples/evidence/shopassist-inventory-orders.json`](examples/evidence/shopassist-inventory-orders.json)
- [`examples/evidence/shopassist-policies.json`](examples/evidence/shopassist-policies.json)
- [`examples/evidence/shopassist-catalog.json`](examples/evidence/shopassist-catalog.json)

These files contain the product, inventory, order, and policy facts used by the local reference
application. They keep the primary demo self-contained instead of depending on a public website.

### Local URLs

| Service | URL |
| --- | --- |
| DriftZero dashboard | <http://localhost:3000> |
| ShopAssist | <http://localhost:3100> |
| Presenter Console | <http://localhost:3100/demo> |
| DriftZero backend | <http://localhost:8000> |
| Interactive API docs | <http://localhost:8000/docs> |

If the dashboard says **Demo data**, open **Settings → Connection**, select the live API mode, and
use `http://127.0.0.1:8000` as the API base URL. A fresh Docker browser session normally starts in
live mode.

## Full local demo walkthrough

Each completed ShopAssist response counts as one interaction. DriftZero receives a health window
when ShopAssist has buffered 20 interactions.

1. Open the [Presenter Console](http://localhost:3100/demo) and confirm that the current agent
   state says **Running normally**.
2. Open [ShopAssist](http://localhost:3100) in another tab.
3. Ask factual questions such as `What is the price of AeroBuds?`, `How many AeroBuds are in
   stock?`, or `What is the return policy for electronics?`.
4. Confirm the source row beneath the answer identifies `openai/gpt-oss-120b`, not
   `Local grounded fallback`.
5. Complete 20 healthy interactions. The twentieth response flushes the batch to DriftZero.
6. Reload the [dashboard](http://localhost:3000) and open the ShopAssist model. Inspect the latest
   Health-v2 window and its evidence-derived metrics.
7. Return to the [Presenter Console](http://localhost:3100/demo), select **Wrong Number**, and
   choose **Run Selected Tests**.
8. Ask `What is the price of AeroBuds?` and confirm the controlled response differs from the
   trusted `$119` value while still identifying the real Groq model.
9. Complete another 20 interactions with Wrong Number active.
10. Reload the DriftZero dashboard. Inspect the fall in quality and groundedness and the resulting
    critical Health-v2 state.
11. Open [Incidents](http://localhost:3000/incidents) and inspect the HIGH incident linked to the
    degraded window.
12. Return to the Presenter Console, choose **Apply recovery**, and then choose **Reset baseline**.
    Ask the AeroBuds price again and confirm normal `$119` behavior returns.

The validated `83.9` and `63.4` scores above are reference results from one completed run. Groq is
a live external model, so wording, latency, evidence coverage, and the precise score can vary
slightly between runs. The expected invariant is the direction of change: the deliberate wrong
number reduces evidence support and should lower quality, groundedness, and Health-v2.

To watch the interaction batch reach the backend without exposing request content or credentials:

```bash
docker compose logs --follow shop-assist api
```

A successful flush includes the structured event `shopassist.monitoring.sent` with a sample size
of 20.

Stop the stack while preserving its database volume:

```bash
docker compose down
```

## How evidence-backed evaluation works

ShopAssist sends raw observations rather than precomputed reliability scores. Each observation can
include the question, answer, provider/model identifiers, request status, latency, token counts,
safety flags, and whether the behavior was deliberately simulated.

For every batch, DriftZero:

1. extracts factual claims from each answer;
2. searches only evidence sources whose status is `approved`;
3. classifies claims as supported, contradicted, or unverified;
4. calculates groundedness from decided claims and quality from all extracted claims;
5. derives operational reliability, latency, safety, and optional cost signals;
6. redacts stored question and answer text while retaining safe trace metadata and hashes; and
7. persists one auditable health snapshot.

The main ingestion endpoint is:

```http
POST /api/v1/models/{model_id}/interactions/evaluate
```

JSON and GeoJSON evidence use deterministic parsing. Uploaded files and URL sources remain outside
the scoring trust boundary until an operator approves them. Unstructured webpage/PDF/text
structuring can use Groq, but generated facts still have to pass source and exact-quote validation.

More detail:

- [Owner connector contract](docs/OWNER_CONNECTOR.md)
- [Health event schema](docs/HEALTH_EVENT_SCHEMA.md)
- [Connections and evidence](docs/CONNECTIONS.md)
- [Website synchronization](docs/WEBSITE_SYNC.md)
- [Groq evaluation](docs/GROQ_EVALUATION.md)

## Health-v2 and incident detection

Health-v2 calculates a weighted mean over the dimensions that are actually present:

| Dimension | Weight |
| --- | ---: |
| Quality | 25% |
| Groundedness | 20% |
| Operational reliability | 20% |
| Semantic stability | 15% |
| Safety | 10% |
| Latency health | 5% |
| Cost efficiency | 5% |

The score is withheld as `insufficient_data` when the window has fewer than 20 samples, less than
30% evidence coverage, or less than 50% of the configured dimension weight. Scored windows are
classified as:

- **Healthy:** 80 or higher
- **Warning:** 65–79.9
- **Critical:** below 65

A warning snapshot opens a MEDIUM incident; a critical snapshot opens or escalates a HIGH
incident. The incident records the opening snapshot, last healthy baseline when available, and
lowest observed score. Diagnosis and recovery infrastructure exists, but the default recovery
adapter is simulated and autonomous real-world recovery is not the primary verified v1 demo.

## Tests and validation

Latest verified results:

| Area | Result |
| --- | --- |
| Backend | 342 Pytest tests passed; Ruff passed |
| ShopAssist | 46 Node tests passed; Oxlint and production build passed |
| Dashboard | ESLint, TypeScript, and production build passed |
| Containers | Compose validation/build, both smoke flows, service-log checks, and single-container verification passed |

Useful local commands:

```bash
# Compose configuration without printing resolved secret values
docker compose config --quiet

# Deterministic dashboard/recovery smoke flow
python3 scripts/smoke_test.py --base-url http://localhost:3000

# ShopAssist → DriftZero 20-interaction telemetry flow
python3 scripts/smoke_shop_assist.py
```

The complete CI workflow is defined in [`.github/workflows/ci.yml`](.github/workflows/ci.yml).

## Tech stack

- **Backend:** Python 3.12+, FastAPI, Pydantic, SQLAlchemy, Alembic, Uvicorn
- **Data:** SQLite for the local demo; optional PostgreSQL driver support
- **Dashboard:** React, TypeScript, Vite, React Router, Recharts, Nginx
- **Reference application:** Next.js, React, TypeScript, Tailwind CSS, Groq
- **Workers:** alert evaluation, recovery commands, retention, evidence synchronization, website refresh
- **Quality:** Pytest, Ruff, ESLint, Oxlint, TypeScript, Node test runner
- **Infrastructure:** Docker, Docker Compose, GitHub Actions; optional Render/Vercel configuration

## Project structure

```text
DriftZero/
├── backend/          FastAPI service, SQLAlchemy data layer, migrations, workers and tests
├── frontend/         React/Vite reliability dashboard and Nginx proxy configuration
├── shop-assist/      Next.js reference LLM application and Presenter Console
├── examples/         Local evidence fixtures and connector examples
├── docs/             Product, API, evidence, architecture and operations documentation
├── scripts/          Local runner and end-to-end smoke tests
├── deploy/           Optional single-container deployment supervisor
├── .github/          CI workflow
├── compose.yaml      Recommended complete local demonstration
└── render.yaml       Optional Render blueprint
```

## Optional deployment architecture

The repository retains deployment configuration for a Render backend and separate Vercel
dashboard and ShopAssist projects. Hosted deployment is optional and is not the recommended way to
judge the complete controlled-degradation experience.

The ShopAssist scenario state is process-local. A serverless host may send the Presenter Console
request and the later chat request to different instances, causing the selected fault to disappear.
The local Docker stack keeps those requests in one process and is therefore the reliable demo path.

A production deployment would replace process-local scenario state with shared storage such as
Redis, replace ephemeral/local SQLite with managed PostgreSQL, narrow CORS, enable production
authentication, and operate workers as independently scalable services. Existing deployment files
remain useful reference implementations; see [the DevOps runbook](docs/DEVOPS_RUNBOOK.md).

## Current limitations

- This is a portfolio-scale reference system, not a production SaaS control plane.
- Real Groq runs require the reviewer's network access, account quota, and API key.
- Live model wording and latency can vary, so exact scores may vary around the validated result.
- Fault injection is deliberate and clearly labeled `simulated`; it is not organic provider drift.
- Scenario selection is process-local and intended for the single-process local demonstration.
- The local database is SQLite and the default recovery adapter is simulated.
- DriftZero derives safety from supplied flags in this path; it does not claim independent
  safety-model evaluation.
- External alert delivery, managed identity, horizontal workers, and production recovery controls
  are outside the verified v1 scope.

## Project summary

DriftZero demonstrates an end-to-end AI reliability pipeline: real Groq responses, provider-neutral
raw interaction capture, approved-evidence claim verification, transparent metric derivation,
Health-v2 scoring, degradation detection, incident creation, diagnosis, and an auditable recovery
lifecycle. ShopAssist provides a repeatable local experiment that makes the healthy and degraded
states visible from the user response through the backend and dashboard.

## License

DriftZero is available under the [MIT License](LICENSE).
