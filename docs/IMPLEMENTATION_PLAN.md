# DriftZero Implementation Plan

**Status:** Draft; depends on PRD approval  
**PRD:** [`docs/PRD.md`](PRD.md)  
**Planning principle:** complete and verify one production-shaped vertical slice before expanding breadth.

## 1. Objective

Deliver a polished DriftZero MVP that demonstrates the complete ShopAssist lifecycle:

```text
seeded traces and telemetry
  → health trajectory and forecast
  → incident and evidence-backed diagnosis
  → policy decision and human approval
  → simulated action execution
  → 50-request verification
  → recovered health and audit trail
```

The current backend already implements a simplified version of this path. The plan hardens and exposes that behavior without discarding working contracts.

## 2. Delivery constraints

- Do not begin application implementation until `docs/PRD.md` is approved.
- Preserve deterministic ShopAssist behavior and existing API tests.
- Never expose the existing unauthenticated service publicly.
- Keep all mock telemetry and recovery behavior clearly labeled as simulated.
- Do not enable consequential production recovery adapters during the MVP.
- Store no raw prompt or response text; redaction occurs before persistence.
- Make migrations, not runtime schema creation, the source of truth for persistent environments.
- Maintain backward compatibility for existing `/api/v1` endpoints or document/version intentional changes.

## 3. Current-state assessment

### Already implemented

- FastAPI application and stable error handling;
- model CRUD subset and telemetry ingestion;
- trace redaction, hashes, normalized metadata, and evidence links;
- `health-v1` weighted score and insufficient-data gates;
- recent-slope forecast with bounds;
- rule-based diagnosis for four cause families plus insufficient evidence;
- cause-specific playbook generation;
- approval-gated simulated recovery and verification;
- persisted threshold, transition, trajectory, coverage, and freshness alerts;
- alert cooldown, deduplication, acknowledgement, resolution, incident linking,
  audit events, and an in-product notification feed;
- audit events and deterministic demo reset;
- relational entities for future incidents, action executions, verification, stability tests, alerts, review, evaluator versions, and tenancy;
- Alembic migration and SQLite/PostgreSQL schema compatibility tests.

### Partially implemented

- tenancy exists in storage but is not enforced through authentication context;
- recovery stages exist in models, but service/API behavior is plan-level and simplified;
- policy and source administration remain incomplete user-facing flows;
- evidence links exist, but pagination and complete trace exploration contracts are incomplete;
- forecast calculation exists, but forecasts are not persisted and evaluated end to end;
- demo verification produces a final snapshot, but full criterion-by-criterion verification records need wiring.

### Not implemented

- frontend;
- authentication and RBAC;
- async ingestion/evaluation jobs;
- production deployment stack and observability;
- real provider/recovery adapters;
- full security controls and operational runbooks.

## 4. Target architecture

```text
Next.js web application
        │ authenticated API calls / streamed job status
        ▼
FastAPI API boundary
        │
        ├── application services ── policy/authorization
        │        │
        │        ├── Pulse: scoring, detection, forecast
        │        ├── Diagnose: taxonomy, evidence ranking
        │        ├── Recover: approval, execution, verification, rollback
        │        └── Evaluations: semantic and temporal stability
        │
        ├── job boundary ── evaluator and adapter workers
        │
        └── SQLAlchemy repositories / PostgreSQL
                  │
                  ├── versioned policies and model fingerprints
                  ├── redacted traces and evidence lineage
                  └── append-only audit events
```

External providers and action systems connect only through typed, allow-listed adapters. The deterministic simulator implements the same interfaces.

## 5. Workstreams

| Workstream | Responsibility | Primary outputs |
| --- | --- | --- |
| Product contracts | Resolve decisions and freeze acceptance criteria | Approved PRD, API schemas, UI state inventory |
| Backend lifecycle | Complete incident/action/verification behaviors | Services, endpoints, migrations, tests |
| Evaluations | Semantic and temporal stability engines | Versioned evaluator contracts, APIs, tests |
| Frontend | Fleet-to-recovery experience | Accessible Next.js application |
| Governance | Auth, tenancy, permissions, retention, audit | Middleware/dependencies, policy tests |
| Platform | Local setup, CI, containers, observability | Compose/config, workflows, runbooks |
| Demo | Deterministic fixtures and presentation | Reset, guided state, script, backup evidence |

## 6. Milestone plan

### Milestone 0 — Approve product and technical contracts

**Goal:** remove decisions that would cause expensive rework.

Tasks:

1. Review and approve the MVP boundary, safety policy, health semantics, and ShopAssist criteria.
2. Resolve the open decisions in PRD Section 24.
3. Inventory existing API schemas against the proposed screens.
4. Define API additions and error/pagination/idempotency conventions.
5. Define the complete UI state matrix and responsive/accessibility baseline.
6. Create architecture decision records for frontend, authentication, jobs, and policy versioning.
7. Freeze a deterministic fixture version and expected numerical outputs.

Deliverables:

- approved PRD;
- `docs/DECISIONS.md` or individual ADRs;
- OpenAPI change proposal;
- screen/state checklist;
- fixture manifest with seed and expected results.

Verification:

- each Must requirement has an owner, milestone, and verification method;
- no unresolved decision blocks the vertical slice;
- existing tests still pass without product code changes.

Exit criteria:

- product owner records approval;
- security boundary explicitly accepts simulated recovery only for MVP.

### Milestone 1 — Harden the existing backend contract

**Goal:** make the current vertical slice robust enough to support a real UI.

Tasks:

1. Add cursor pagination and filters for models, snapshots, traces, evidence, and audit events.
2. Add explicit model detail fields: description, status, retention, latest data time, current version.
3. Persist forecasts and backfill actual outcomes after the horizon.
4. Introduce versioned degradation rules and incident deduplication/state transitions.
5. Wire incident records into diagnosis, recovery, and verification instead of relying only on model links.
6. Replace JSON-only plan actions with authoritative `recovery_actions` records while retaining response compatibility.
7. Record one execution row per action, including status, timeout, scope, result, and rollback fields.
8. Persist verification runs with thresholds, required requests, window, and no-regression results.
9. Add idempotency keys and transition concurrency checks.
10. Expand stable error contracts and request/correlation IDs.
11. Add migrations for any schema changes and preserve downgrade/schema parity checks.

Tests:

- duplicate incident suppression;
- concurrent or repeated approval/execution;
- action partial failure, timeout, skip, and retry;
- verification pass and fail paths;
- persisted forecast actual/error;
- pagination and invalid cursor behavior;
- migration upgrade/downgrade and PostgreSQL compilation;
- old endpoint response compatibility.

Exit criteria:

- all existing tests pass;
- new backend lifecycle tests pass;
- one API-only ShopAssist run produces incident, evidence, action executions, verification, and audit records.

### Milestone 2 — Build the frontend vertical slice

**Goal:** make the approved ShopAssist story understandable and operable end to end.

Recommended stack pending approval: Next.js + TypeScript + Tailwind + accessible component primitives.

Tasks:

1. Create typed API client from or checked against OpenAPI.
2. Build global shell with environment, simulation, time range, data freshness, and navigation.
3. Build Fleet page with state summaries, filters, score/coverage/freshness, and incident link.
4. Build Model Pulse page with timeline, forecast interval, version markers, dimension contributions, score explanation, and trace list.
5. Build Incident/Diagnose page with ranked causes, confidence label, supporting/contradicting evidence, and trace drawer.
6. Build Recovery page with ordered risks, approval policy, distinct approve/execute controls, action progress, verification, rollback state, and audit timeline.
7. Add deterministic reset/start control in explicit demo mode.
8. Implement all required loading, empty, insufficient, partial, stale, failure, and permission states.
9. Apply keyboard navigation, focus management, semantic labels, contrast, and reduced-motion support.

Tests:

- component tests for state rendering and score labels;
- mocked API integration tests for all recovery transitions;
- browser E2E: reset → inspect decline → diagnose → blocked unapproved execution → approve → execute → verify;
- browser E2E for insufficient-data and failed-recovery states;
- automated accessibility checks plus keyboard walkthrough;
- viewport checks for supported desktop/tablet widths.

Exit criteria:

- primary narrative completes without direct API or database interaction;
- every key number exposes definition, window, coverage, sample, source, and version;
- simulated state is unmistakable;
- no console errors or failed requests in the golden path.

### Milestone 3 — Implement signature evaluations

**Goal:** deliver credible Semantic and Temporal Stability Tests.

Tasks:

1. Define an evaluator adapter interface with versioned configuration and deterministic fixture adapter.
2. Implement semantic test creation, variant generation/import, response association, claim extraction, normalization, and agreement calculation.
3. Store variant seeds, generator versions, evaluator versions, claims, confidence, coverage, verdict, and traces.
4. Implement temporal schedules/manual runs and controlled-input fingerprint comparison.
5. Return changed-input attribution and inconclusive states explicitly.
6. Build evaluation list/detail screens and claim comparison matrix.
7. Add human feedback and replay by evaluator version.
8. Feed eligible stability results into health snapshots without circular or stale data use.

Tests:

- paraphrases with equivalent wording and identical facts score stable;
- one material conflicting claim is surfaced and lowers stability;
- absent/low-confidence claims yield inconclusive rather than false certainty;
- changed temporal fingerprint identifies exact changed fields and does not label unexplained drift;
- matching fingerprint with conflicting material claims detects temporal instability;
- evaluator replay preserves old results and creates version-linked new results.

Exit criteria:

- both tests can be run through UI and API;
- every result links to variants/runs, claims, traces, and evaluator version;
- ShopAssist knowledge-freshness evidence includes a semantic disagreement.

### Milestone 4 — Alerts, review, and policy administration

**Goal:** turn analysis into an operable workflow beyond the guided demo.

**Status:** Alert rules, lifecycle, audit integration, and the in-product feed
are complete. External delivery remains deliberately deferred. Policy
administration is still outstanding.

Tasks:

1. Implement versioned health and degradation policy reads; add safe create-new-version admin flow if approved.
2. Complete — alert rules cover thresholds, transitions, trajectory, coverage, and evaluation freshness.
3. Complete — cooldown, deduplication, acknowledgement, resolution, severity, and incident linking.
4. Implement human review queue for traces, claim conflicts, diagnosis feedback, and recovery exceptions.
5. Add assignment, priority, status, decision, notes, and due date.
6. Complete — the tenant alert feed is the in-product notification center;
   external channels remain deferred unless separately approved.
7. Complete for alert and review state changes.

Tests:

- rule evaluation at threshold boundaries;
- cooldown and deduplication;
- alert-to-incident linkage and lifecycle;
- review permissions, assignment, and resolution;
- immutable historical policy linkage;
- complete audit-event assertions.

Exit criteria:

- a non-demo incident can progress from alert through review/diagnosis to recovery recommendation;
- policy edits never alter historical score interpretation.

### Milestone 5 — Authentication, tenancy, and security gate

**Goal:** make the service safe for a hosted demonstration.

Tasks:

1. Implement selected OIDC/session authentication and local-only demo identity mode.
2. Resolve tenant and role from trusted authentication context.
3. Apply tenant filters to every repository query and relationship access.
4. Enforce Viewer/Operator/Admin/Service permissions server-side.
5. Issue scoped ingestion credentials with rotation/revocation support.
6. Add trace-view access auditing and privacy-safe error/log handling.
7. Implement retention purge scheduling and evidence-preserving aggregate behavior.
8. Add input size/rate limits, secure CORS/origins, CSRF protection where relevant, and security headers.
9. Threat-model privileged recovery adapters and document prohibited production configurations.
10. Run dependency, secret, static, and container scans.

Tests:

- unauthenticated access rejection;
- role matrix for every state-changing route;
- cross-tenant ID enumeration and relationship traversal denial;
- service identity cannot read traces or approve recovery;
- expired/revoked credential rejection;
- retention purge boundaries;
- no sensitive text in logs/errors/audit payloads;
- abuse tests for invalid/oversized/replayed ingestion.

Exit criteria:

- security checklist passes;
- service may be hosted with simulation-only adapters;
- no public route other than health/readiness bypasses intended authentication.

### Milestone 6 — Platform, observability, and release readiness

**Goal:** create a repeatable, diagnosable build and demo deployment.

Tasks:

1. Provide local environment orchestration for frontend, backend, and PostgreSQL.
2. Add production-oriented containers with non-root users and health checks.
3. Add CI for formatting/lint, typing, unit/integration tests, migrations, frontend build, E2E, accessibility, and scans.
4. Add structured logs with request/correlation IDs and redaction.
5. Add metrics for ingestion, job lag, evaluator errors, API latency, incidents, forecasts, recovery, and verification.
6. Add readiness checks for database/migrations and optional worker dependencies.
7. Create backup/restore and migration runbooks for persistent environments.
8. Create demo startup self-check, fixture version display, reset instructions, and backup recording/screenshots.
9. Produce setup, architecture, operations, security-boundary, and demo documentation.
10. Generate a requirement-to-evidence release report.

Exit criteria:

- clean-machine setup is documented and rehearsed;
- CI passes from a clean clone;
- primary demo works without external services beyond local stack;
- rollback and recovery runbooks are reviewed;
- every Must requirement has linked evidence.

### Milestone 7 — Production adapter pilot (post-MVP)

**Goal:** validate one real integration without broad production risk.

Tasks:

1. Select one provider/gateway and one reversible, low-risk action.
2. Define adapter contract, credentials, allow-list, blast radius, canary, timeout, reconciliation, and rollback.
3. Build sandbox/staging integration with fault injection.
4. Require explicit human approval and current-state preconditions.
5. Verify action effect and no-regression criteria against staging traffic.
6. Complete threat model, operational ownership, and emergency disable control.

Exit criteria:

- staging-only pilot passes duplicate, timeout, partial failure, external-state drift, and rollback tests;
- production enablement receives separate approval.

## 7. Suggested issue breakdown

Issues should be independently testable and small enough for one focused change. Suggested first sequence:

1. `backend: add incident lifecycle service and endpoints`
2. `backend: persist forecast and actual outcome`
3. `backend: normalize recovery actions into authoritative records`
4. `backend: record action-level executions and partial failures`
5. `backend: persist verification criteria and no-regression checks`
6. `backend: add pagination, filtering, and trace/evidence endpoints`
7. `web: scaffold accessible application shell and typed API client`
8. `web: implement fleet and Pulse model detail`
9. `web: implement Diagnose incident detail and evidence drill-down`
10. `web: implement recovery approval, execution, and verification`
11. `e2e: automate ShopAssist golden path and failure states`
12. `evaluations: semantic stability engine and API`
13. `evaluations: temporal stability fingerprint comparison and API`
14. `web: evaluation detail and claim matrix`
15. `governance: authentication context and RBAC`
16. `governance: tenant-scoped repositories and isolation tests`
17. `platform: CI, containers, metrics, and release report`

Each issue must include requirement IDs, API/data changes, migration impact, test cases, documentation impact, and an explicit definition of done.

## 8. Data migration strategy

1. Treat Alembic history as immutable after sharing; add forward migrations.
2. Add nullable columns/tables first, deploy compatible code, backfill, then add constraints in a later migration when needed.
3. Preserve JSON compatibility fields while normalized action/evidence records become authoritative; remove only in a future breaking version.
4. Run schema parity, upgrade, downgrade, and PostgreSQL compilation tests for every migration.
5. Provide fixture migration/reset behavior separately from persistent data migrations.
6. Never run demo reset against a production-configured environment; add an environment guard.

## 9. API delivery strategy

- Design schema changes in OpenAPI before frontend implementation.
- Generate or validate the TypeScript client in CI.
- Add list endpoints with cursor pagination from the start.
- Use idempotency keys on create/execute operations.
- Return current entity version/state on transition conflicts.
- Use job resources for long-running evaluation and recovery operations.
- Preserve stable error codes across backend and UI.
- Add contract fixtures for healthy, warning, critical, insufficient, partial failure, and changed-input cases.

Likely additions:

```text
GET    /api/v1/incidents
GET    /api/v1/incidents/{id}
GET    /api/v1/models/{id}/traces
GET    /api/v1/diagnoses/{id}/evidence
POST   /api/v1/recovery/{id}/reject
GET    /api/v1/recovery/{id}/executions
POST   /api/v1/recovery/{id}/rollback
GET    /api/v1/recovery/{id}/verification
POST   /api/v1/evaluations/semantic
POST   /api/v1/evaluations/temporal
GET    /api/v1/evaluations/{id}
POST   /api/v1/evaluations/{id}/feedback
GET    /api/v1/alerts
GET    /api/v1/alerts/{id}
POST   /api/v1/alerts/{id}/acknowledge
POST   /api/v1/alerts/{id}/resolve
POST   /api/v1/models/{id}/alert-rules
GET    /api/v1/models/{id}/alert-rules
GET    /api/v1/alert-rules/{id}
PATCH  /api/v1/alert-rules/{id}
DELETE /api/v1/alert-rules/{id}
POST   /api/v1/models/{id}/alerts/evaluate
GET    /api/v1/review
PATCH  /api/v1/review/{id}
GET    /api/v1/policies/health
```

Exact shapes are finalized in Milestone 0.

## 10. Verification strategy

### 10.1 Test pyramid

- **Unit:** score normalization/gates, detection rules, forecast bounds, diagnosis rules, claim agreement, policy decisions, transition guards.
- **Persistence:** constraints, tenancy, cascades, mutable JSON, migrations, retention, lineage.
- **Service integration:** lifecycle transitions, idempotency, concurrency, partial failure, audit completeness.
- **API contract:** schemas, status/error codes, pagination, authentication/authorization.
- **Browser E2E:** golden path, insufficient data, failure/rollback, changed temporal inputs, permission denial.
- **Non-functional:** accessibility, performance smoke, security, dependency/secret scan, backup/restore rehearsal.

### 10.2 Golden-path assertions

The deterministic ShopAssist test must assert:

- scores equal `92.0, 87.0, 74.0, 61.0`;
- 30-minute prediction equals `48.0` with deteriorating direction;
- diagnosis is `knowledge_freshness_failure` with estimated confidence approximately `0.87`;
- evidence contains groundedness, semantic stability, drift support and stable safety/latency contradiction evidence;
- recovery is simulated, medium risk, and contains five expected actions;
- execution before approval returns a stable transition conflict;
- approval and execution actors are audited;
- exactly 50 verification requests are represented;
- post-recovery score is approximately `84.2`;
- diagnosis/incident resolves only after verification;
- all expected audit stages exist and link to the incident/plan.

### 10.3 Definition of done for every feature

- requirement acceptance criteria met;
- typed API and data contracts updated;
- migration included and verified when persistence changes;
- authorization and tenant scope reviewed;
- audit behavior specified for state changes;
- loading, empty, partial, failure, and permission states implemented;
- automated tests added at appropriate levels;
- documentation updated;
- no new lint, type, test, accessibility, or security failures;
- simulation/uncertainty labels verified.

## 11. Requirement-to-milestone traceability

| Requirement | Milestone | Primary evidence |
| --- | --- | --- |
| FLT-001, FLT-003 | 1, 2 | API/service tests; Fleet/Model E2E |
| FLT-002 | 2 | Fleet component and E2E tests |
| FLT-004 | 4, 6 | ingestion metrics/UI tests |
| PUL-001–PUL-003 | Existing, 1, 2 | scoring tests; score-details UI tests |
| PUL-004 | 1 | detection and incident-dedup integration tests |
| PUL-005 | Existing, 1, 2 | forecast unit/API/chart tests |
| PUL-006 | 1, 6 | persisted forecast calibration test/metric |
| PUL-007 | Existing partial, 1, 2 | evidence-to-trace API and browser test |
| DIA-001–DIA-004 | Existing partial, 1, 2 | diagnosis unit/integration and incident E2E |
| DIA-005 | 3, 4 | feedback API/UI tests |
| DIA-006 | 1 | incident/diagnosis transition tests |
| REC-001–REC-006 | Existing partial, 1, 2 | policy/transition/partial-failure/E2E tests |
| REC-007 | 1 model support; 7 adapter | rollback service and staging adapter tests |
| REC-008 | Existing partial, 2 | schema/UI simulation assertions |
| SEM-001–SEM-003 | 3 | semantic evaluator and claim-matrix tests |
| TMP-001–TMP-003 | 3 | fingerprint and temporal evaluation tests |
| ALT-001–ALT-002 | 4 | rule boundary/lifecycle tests |
| REV-001 | 4 | review queue API/RBAC/E2E tests |
| GOV-001–GOV-002 | 5 | auth, RBAC, cross-tenant security tests |
| GOV-003 | Existing partial, 5 | redaction and retention tests |
| GOV-004 | Existing partial, 1, 4, 5 | audit completeness tests |
| GOV-005 | 3, 4 | evaluator version/replay tests |

## 12. Critical dependency order

```text
PRD decisions
  ├── API/state contracts
  │     ├── backend lifecycle hardening
  │     │       └── frontend vertical slice
  │     └── evaluator contracts
  │             └── stability evaluations UI
  ├── auth choice ── tenancy/RBAC ── hosted demo
  └── job choice ── async evaluations ── scale/production adapters

vertical slice + auth/security + platform checks
  └── hosted simulation-only release
        └── separately approved production adapter pilot
```

Frontend components may be built against frozen fixtures while backend endpoints are completed, but the OpenAPI/state contract must be agreed first.

## 13. Risks to schedule

| Risk | Early signal | Response |
| --- | --- | --- |
| Building all schema surfaces at once | Many endpoints with no complete UI flow | Protect the ShopAssist vertical slice; defer breadth. |
| Authentication selected late | Tenant assumptions leak into services | Decide in Milestone 0; introduce trusted request context early. |
| LLM evaluator nondeterminism | Flaky tests/demo | Deterministic evaluator fixtures and pinned seeds/versions. |
| Frontend waits on backend | UI milestone stalls | Freeze schemas and use generated fixtures/mock server. |
| Recovery scope expands | Real provider edge cases dominate MVP | Keep simulator; move real adapter to Milestone 7. |
| Hidden policy duplication | Backend and UI disagree on thresholds | API supplies versioned definitions; UI renders rather than redefines. |
| SQLite-only assumptions | Hosted deployment failures | Keep PostgreSQL compilation tests and add real PostgreSQL integration CI. |

## 14. Recommended MVP cut line

For a time-constrained hackathon, the shippable core is Milestones 0–3 plus the hosted-demo subset of Milestones 5–6. Milestone 4 is Should scope. A real production adapter is explicitly post-MVP.

If schedule pressure appears, cut in this order:

1. external notifications;
2. editable policy UI (retain read-only definitions);
3. advanced review assignment features;
4. multiple providers/evaluators;
5. learned forecast or diagnosis components;
6. production adapter work.

Do not cut approval separation, evidence traceability, insufficient-data behavior, simulation labels, deterministic reset, or verification/no-regression checks; those are the credibility and safety core of DriftZero.

## 15. Immediate next action after approval

1. Record PRD approval and resolved decisions.
2. Run the existing backend verification suite to establish a baseline.
3. Create Milestone 1 issues with requirement IDs and definitions of done.
4. Freeze OpenAPI additions for incident, evidence, execution, and verification reads.
5. Implement incident lifecycle and action-level recovery records as the first code changes.
