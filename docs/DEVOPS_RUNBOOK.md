# DriftZero DevOps runbook

## Scope and hard boundary

This setup is designed for a hackathon demo, not production. It proves one vertical slice:

```text
Browser → Dashboard proxy → FastAPI → SQLite
                              ├→ health scoring and forecast
                              ├→ diagnosis and incident
                              └→ approval → durable command queue
Alert worker ───────────────────────────────┤
Recovery worker → mock action → verification┤
Retention worker ───────────────────────────┘
Evidence sync worker → public source URL → reviewable evidence version
Browser → ShopAssist server → Groq or local grounded fallback
                            └→ 20-request window → DriftZero telemetry API
```

Recovery mutations have operator/admin API-key roles and the demo enables an explicit local identity. The backend still lacks managed OIDC and complete tenant-scoped authorization. Never attach consequential production credentials to the public hackathon deployment.

## 1. Install the minimum tools

Required:

- Docker Engine
- Docker Compose v2 (`docker compose version`)
- A web browser

Optional:

- Python 3.12+ for local backend development and the smoke/connector scripts
- Git for branch and pull-request work

Git is not required to run a ZIP download of the repository. On a locked Fedora machine where `dnf install` requires administrator rights, use your existing browser/GitHub workflow or ask the administrator to install Git; do not bypass the machine's privilege controls.

## 2. Start locally

From the repository root:

```bash
cp .env.example .env
docker compose up --build
```

Open:

- Dashboard: <http://localhost:3000>
- ShopAssist: <http://localhost:3100>
- ShopAssist presenter console: <http://localhost:3100/demo>
- API docs: <http://localhost:8000/docs>
- API health: <http://localhost:8000/healthz>
- Dashboard health: <http://localhost:3000/healthz>
- ShopAssist health: <http://localhost:3100>

Docker Compose waits for the API health check before starting the proxy and workers. The dashboard uses `/api/v1` on its own origin; Nginx forwards that traffic to the internal `api:8000` service. This avoids browser CORS configuration and prevents hard-coded local API URLs.

## 3. Environment variables

Copy `.env.example` to `.env`. Never commit `.env`.

| Variable | Default | Purpose |
|---|---|---|
| `DRIFTZERO_DASHBOARD_PORT` | `3000` | Host port for the dashboard |
| `DRIFTZERO_API_PORT` | `8000` | Host port for API/debug access |
| `SHOP_ASSIST_PORT` | `3100` | Host port for ShopAssist |
| `SHOPASSIST_PUBLIC_URL` | `http://localhost:3100` | Public ShopAssist origin used for metadata links |
| `GROQ_API_KEY` | unset | Optional server-only ShopAssist provider key; fallback mode needs no key |
| `GEMINI_API_KEY` | unset | Reserved server-only key for the future provider-failover adapter |
| `DRIFTZERO_DATABASE_URL` | `sqlite:////data/driftzero.db` | Shared local database |
| `DRIFTZERO_API_PREFIX` | `/api/v1` | Versioned API prefix |
| `DRIFTZERO_ENVIRONMENT` | `development` | Log and health-check environment label |
| `DRIFTZERO_API_REQUIRE_AUTH` | `false` | Require management Bearer keys outside production too |
| `DRIFTZERO_API_VIEWER_KEY` | unset | Read-only management credential |
| `DRIFTZERO_API_OPERATOR_KEY` | unset | Read/write credential without delete permission |
| `DRIFTZERO_API_ADMIN_KEY` | unset | Full-control management credential |
| `DRIFTZERO_API_RATE_LIMIT_PER_MINUTE` | `300` | Per-process limit keyed by credential or client |
| `DRIFTZERO_API_MAX_REQUEST_BYTES` | `8388608` | Maximum body size, including a 5 MiB base64 evidence upload |
| `DRIFTZERO_EVIDENCE_MAX_FILE_BYTES` | `5242880` | Maximum uploaded or URL-fetched evidence size |
| `DRIFTZERO_EVIDENCE_URL_TIMEOUT_SECONDS` | `15` | Timeout for public evidence URL fetches |
| `DRIFTZERO_EVIDENCE_SYNC_INTERVAL_SECONDS` | `60` | URL evidence worker poll interval |
| `DRIFTZERO_TRUSTED_HOSTS` | `localhost,127.0.0.1,testserver,api` | Accepted HTTP Host values, including the Compose API service name; supports `*.example.com` |
| `DRIFTZERO_TELEMETRY_MAX_FUTURE_SKEW_SECONDS` | `300` | Maximum clock lead for observed telemetry |
| `DRIFTZERO_DOCS_ENABLED` | `true` | Local docs switch; docs remain disabled in production |
| `DRIFTZERO_ALERT_EVALUATION_INTERVAL_SECONDS` | `60` | Alert worker poll interval |
| `DRIFTZERO_RECOVERY_WORKER_INTERVAL_SECONDS` | `2` | Recovery queue poll interval |
| `DRIFTZERO_RECOVERY_COMMAND_LEASE_SECONDS` | `60` | Lease before an abandoned recovery can be reclaimed |
| `DRIFTZERO_RECOVERY_COMMAND_MAX_ATTEMPTS` | `3` | Maximum command attempts |
| `DRIFTZERO_RECOVERY_ALLOW_LOCAL_IDENTITY` | `true` | Demo-only header identity; ignored in production |
| `DRIFTZERO_RECOVERY_VERIFICATION_REQUESTS` | `50` | Minimum post-action evidence count |
| `DRIFTZERO_RECOVERY_VERIFICATION_COVERAGE` | `0.90` | Minimum post-action traffic coverage |
| `DRIFTZERO_RECOVERY_OPERATOR_API_KEY` | unset | Server-side operator credential |
| `DRIFTZERO_RECOVERY_ADMIN_API_KEY` | unset | Server-side high-risk/rollback credential |
| `DRIFTZERO_RECOVERY_CONTROL_URL` | unset | Optional HTTPS model-gateway control plane |
| `DRIFTZERO_RECOVERY_CONTROL_TOKEN` | unset | Server-only control-plane bearer token |
| `DRIFTZERO_RETENTION_INTERVAL_SECONDS` | `3600` | Trace-retention worker interval |
| `DRIFTZERO_LOG_LEVEL` | `INFO` | Structured application log level |
| `DRIFTZERO_OTEL_ENABLED` | `false` | Optional OpenTelemetry export |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | unset | Optional collector endpoint |

The platform-provided `PORT` is handled by the container entrypoint. Do not place real provider keys in frontend files or variables; browser assets are public.

Production and `prod` environments require management authentication automatically. A
deployment with no configured management key returns `503` on protected routes. Store keys in
the platform secret manager, rotate them independently, and terminate TLS before the API. Keep
`DRIFTZERO_TRUSTED_HOSTS` limited to actual service and custom-domain hosts. The process-local
limiter is defense in depth for one instance; configure a shared gateway/WAF rate limit before
running multiple replicas.

## 4. Service responsibilities

| Service | Responsibility | Health signal |
|---|---|---|
| `dashboard` | Static UI and same-origin reverse proxy | `GET /healthz` |
| `shop-assist` | Customer demo, server-side provider/fallback, and telemetry connector | `GET /` |
| `api` | Registry, telemetry, scoring, diagnosis, recovery, audit | `GET /healthz` |
| `alert-worker` | Evaluates alert rules without waiting for API traffic | Process stays running and emits JSON completion logs |
| `recovery-worker` | Claims leased execute/verify/rollback commands and runs the configured adapter | Command becomes `succeeded`, retried, or `failed` |
| `retention-worker` | Applies each model's configured trace-retention window | Process stays running and logs failures |
| `evidence-sync-worker` | Rechecks opted-in public source URLs and versions changed content | Emits `evidence_sync.completed` logs |
| `driftzero-data` | Named SQLite volume shared by API and workers | API database operations |

SQLite works here because there is one local host and low demo traffic. It is the wrong choice for horizontally scaled services. Move to managed PostgreSQL before adding replicas or real users.

## 5. Telemetry integration

Use the contract in `docs/HEALTH_EVENT_SCHEMA.md`. A dependency-free connector is in `examples/connectors/send_sample_telemetry.py`.

```bash
python3 examples/connectors/send_sample_telemetry.py --base-url http://localhost:8000
```

The connector registers a synthetic model version and sends one normalized health window. Real provider adapters should remain outside the API and map provider observations into the same contract.

## 6. Demo failover and recovery

The dashboard performs this exact sequence:

1. `POST /api/v1/demo/reset` creates ShopAssist and seeds health `92 → 87 → 74 → 61`.
2. The API forecasts `48` and diagnoses `knowledge_freshness_failure`.
3. The operator approves the recommended plan.
4. Execution is stored as a durable command; the recovery worker claims it.
5. The mock adapter enables citations, suppresses unsupported output, refreshes retrieval, routes low-confidence traffic, and queues conflicts for review.
6. Verification simulates 50 requests and recovers health to `84.2`.
7. The API records approval, execution, verification, and incident closure in the audit trail.

The dashboard and smoke test send the local-demo actor headers. In hosted
non-demo environments, disable `DRIFTZERO_RECOVERY_ALLOW_LOCAL_IDENTITY`, store
operator/admin keys as secrets, and use `Authorization: Bearer ...`. The body
cannot override the role associated with that credential.

For a non-demo environment, set one of the server-side recovery keys and disable
local identity. The smoke test reads the selected operator key without putting it
in shell history:

```bash
export DRIFTZERO_RECOVERY_API_KEY='replace-at-runtime'
python3 scripts/smoke_test.py --base-url https://YOUR-DRIFTZERO-URL
unset DRIFTZERO_RECOVERY_API_KEY
```

Run the same sequence without the browser:

```bash
python3 scripts/smoke_test.py --base-url http://localhost:3000
```

If a demo state becomes inconsistent, use **Reset demo**. This intentionally replaces the prior seeded scenario. It does not represent a production disaster-recovery mechanism.

## 7. Logs and troubleshooting

Application logs are structured JSON on stdout. Docker rotates container logs at 10 MB and keeps three files.

```bash
docker compose ps
docker compose logs -f api
docker compose logs -f alert-worker
docker compose logs -f recovery-worker
docker compose logs -f retention-worker
docker compose logs -f evidence-sync-worker
docker compose logs -f dashboard
docker compose logs -f shop-assist
```

Common failures:

- Port already used: change `DRIFTZERO_DASHBOARD_PORT`, `DRIFTZERO_API_PORT`, or `SHOP_ASSIST_PORT` in `.env`.
- Dashboard says API unavailable: check `docker compose ps`; the API must be healthy before the proxy starts.
- Database cannot be opened: keep the container URL exactly `sqlite:////data/driftzero.db` and inspect the named volume.
- A stale demo remains: click **Reset demo** or run the smoke test.
- Container build fails downloading packages: confirm Docker has network access; no provider API key is required.

Stop while keeping data:

```bash
docker compose down
```

Delete demo data only when intended:

```bash
docker compose down --volumes
```

Exact clean-clone check on a Docker-equipped machine:

```bash
git clone git@github.com:parthbagwe/DriftZero.git
cd DriftZero
cp .env.example .env
docker compose up --build --detach
python3 scripts/smoke_test.py --base-url http://localhost:3000
python3 scripts/smoke_shop_assist.py
curl --fail http://localhost:3100
docker compose ps
docker compose logs --no-color api recovery-worker alert-worker retention-worker evidence-sync-worker shop-assist
docker compose down
```

Use `docker compose down --volumes` only when the local demo database should be
deleted. Never use that variant on a volume containing data you need.

## 8. CI

`.github/workflows/ci.yml` runs on pull requests and pushes to `main`:

1. install Python 3.12 dependencies;
2. run Ruff and all backend tests;
3. run ShopAssist `npm ci`, lint, tests, and production build on Node 22;
4. run dashboard `npm ci`, lint, and production build on Node 22;
5. validate and build Docker Compose, including ShopAssist;
6. start all services and wait for explicit API, dashboard, and ShopAssist checks;
7. verify the three long-running workers are still running;
8. run the complete recovery smoke test and single-container smoke test;
9. print container logs on failure and always clean up.

There is no automatic GitHub-to-production deployment job. Infrastructure changes must pass CI and then be promoted through the hosting platform.

## 9. Render demo deployment

`render.yaml` builds one public container that serves the FastAPI API and dashboard and runs the alert, recovery, retention, and evidence-sync workers. One container is deliberate: Render's free services have ephemeral filesystems, and separate SQLite services cannot safely share a database. The bundled process supervisor is a demo compromise; production should run the API and workers as separate services backed by PostgreSQL.

1. Merge the reviewed branch into the repository default branch.
2. In Render, create a new Blueprint and connect this repository.
3. Confirm `render.yaml` is selected and create the `driftzero-demo` service.
4. Wait for `/healthz` to pass.
5. Open the assigned URL and run the UI demo.
6. Run `python3 scripts/smoke_test.py --base-url https://YOUR-SERVICE.onrender.com`.
7. Delete or suspend the service after judging.

ShopAssist is deployed separately as a Next.js service. The repository includes
`shop-assist/vercel.json`; configure that deployment with:

- `DRIFTZERO_API_URL=https://YOUR-DRIFTZERO-SERVICE.onrender.com`
- `SHOPASSIST_PUBLIC_URL=https://YOUR-SHOPASSIST-DOMAIN`
- `GROQ_API_KEY` as a secret only when live provider answers are required
- `GEMINI_API_KEY` only after the future failover adapter is enabled

Do not publish the ShopAssist demo as integrated until its telemetry smoke test
passes against the public DriftZero URL. Without a reachable
`DRIFTZERO_API_URL`, chat falls back safely but telemetry is buffered and the
end-to-end demo is incomplete.

The free instance can sleep when idle and loses its SQLite data on restart or redeploy. That is acceptable for the resettable demo and unacceptable for production. A real deployment requires authentication, tenant isolation, managed PostgreSQL, secrets management, backups, rate limiting, and real recovery-adapter authorization.

## 10. Handoff checklist

- [ ] `.env` is not committed.
- [ ] `docker compose up --build --wait` succeeds.
- [ ] `python3 scripts/smoke_test.py` passes.
- [ ] Backend lint and tests pass.
- [ ] No provider credentials exist in Git history or frontend assets.
- [ ] Recovery UI remains labeled **simulation only**.
- [ ] Pull request is reviewed before merging.
- [ ] Public demo is removed after the event.
