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
```

The backend deliberately has no authentication, RBAC, or tenant isolation. Never attach production credentials or real recovery actions. A public deployment should exist only for the judging window.

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
- API docs: <http://localhost:8000/docs>
- API health: <http://localhost:8000/healthz>
- Dashboard health: <http://localhost:3000/healthz>

Docker Compose waits for the API health check before starting the proxy and workers. The dashboard uses `/api/v1` on its own origin; Nginx forwards that traffic to the internal `api:8000` service. This avoids browser CORS configuration and prevents hard-coded local API URLs.

## 3. Environment variables

Copy `.env.example` to `.env`. Never commit `.env`.

| Variable | Default | Purpose |
|---|---|---|
| `DRIFTZERO_DASHBOARD_PORT` | `3000` | Host port for the dashboard |
| `DRIFTZERO_API_PORT` | `8000` | Host port for API/debug access |
| `DRIFTZERO_DATABASE_URL` | `sqlite:////data/driftzero.db` | Shared local database |
| `DRIFTZERO_API_PREFIX` | `/api/v1` | Versioned API prefix |
| `DRIFTZERO_ENVIRONMENT` | `development` | Log and health-check environment label |
| `DRIFTZERO_ALERT_EVALUATION_INTERVAL_SECONDS` | `60` | Alert worker poll interval |
| `DRIFTZERO_RECOVERY_WORKER_INTERVAL_SECONDS` | `2` | Recovery queue poll interval |
| `DRIFTZERO_RECOVERY_COMMAND_LEASE_SECONDS` | `60` | Lease before an abandoned recovery can be reclaimed |
| `DRIFTZERO_RECOVERY_COMMAND_MAX_ATTEMPTS` | `3` | Maximum command attempts |
| `DRIFTZERO_RETENTION_INTERVAL_SECONDS` | `3600` | Trace-retention worker interval |
| `DRIFTZERO_LOG_LEVEL` | `INFO` | Structured application log level |
| `DRIFTZERO_OTEL_ENABLED` | `false` | Optional OpenTelemetry export |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | unset | Optional collector endpoint |

The platform-provided `PORT` is handled by the container entrypoint. Do not place real provider keys in frontend files or variables; browser assets are public.

## 4. Service responsibilities

| Service | Responsibility | Health signal |
|---|---|---|
| `dashboard` | Static UI and same-origin reverse proxy | `GET /healthz` |
| `api` | Registry, telemetry, scoring, diagnosis, recovery, audit | `GET /healthz` |
| `alert-worker` | Evaluates alert rules without waiting for API traffic | Process stays running and emits JSON completion logs |
| `recovery-worker` | Claims durable approved commands and runs the mock adapter | Command becomes `succeeded` or `failed` |
| `retention-worker` | Applies each model's configured trace-retention window | Process stays running and logs failures |
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

1. `POST /api/v1/demo/reset` seeds health `92 → 87 → 74 → 61`.
2. The API forecasts `48` and diagnoses `knowledge_freshness_failure`.
3. The operator approves the recommended plan.
4. Execution is stored as a durable command; the recovery worker claims it.
5. The mock adapter enables citations, suppresses unsupported output, refreshes retrieval, routes low-confidence traffic, and queues conflicts for review.
6. Verification simulates 50 requests and recovers health to `84.2`.
7. The API records approval, execution, verification, and incident closure in the audit trail.

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
docker compose logs -f dashboard
```

Common failures:

- Port already used: change `DRIFTZERO_DASHBOARD_PORT` or `DRIFTZERO_API_PORT` in `.env`.
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

## 8. CI

`.github/workflows/ci.yml` runs on pull requests and pushes to `main`:

1. install Python 3.12 dependencies;
2. run Ruff and all backend tests;
3. parse-check dashboard JavaScript;
4. validate and build Docker Compose;
5. start all services and wait for health checks;
6. run the complete recovery smoke test;
7. print container logs on failure and always clean up.

There is no automatic GitHub-to-production deployment job. Infrastructure changes must pass CI and then be promoted through the hosting platform.

## 9. Render demo deployment

`render.yaml` builds one public container that serves the FastAPI API and dashboard and runs the recovery worker. One container is deliberate: Render's free services have ephemeral filesystems, and separate SQLite services cannot safely share a database. The bundled process supervisor is a demo compromise; production should run the API and worker as separate services backed by PostgreSQL.

1. Merge the reviewed branch into the repository default branch.
2. In Render, create a new Blueprint and connect this repository.
3. Confirm `render.yaml` is selected and create the `driftzero-demo` service.
4. Wait for `/healthz` to pass.
5. Open the assigned URL and run the UI demo.
6. Run `python3 scripts/smoke_test.py --base-url https://YOUR-SERVICE.onrender.com`.
7. Delete or suspend the service after judging.

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
