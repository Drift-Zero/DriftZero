# DriftZero

DriftZero is a hackathon MVP for detecting AI reliability degradation, explaining the likely cause, and running an operator-approved simulated recovery.

## Run the complete demo

Requirements: Docker Engine with Docker Compose v2. Git is only needed for repository work, not for running the downloaded project.

```bash
cp .env.example .env
docker compose up --build
```

Open <http://localhost:3000>. API documentation is at <http://localhost:8000/docs>.

Verify the full seeded degradation and recovery flow:

```bash
python3 scripts/smoke_test.py
```

Stop the stack with `docker compose down`. Add `--volumes` only when you deliberately want to delete the local demo database.

The local stack contains:

- `dashboard`: static web UI and same-origin API proxy;
- `api`: FastAPI ingestion, scoring, diagnosis, recovery, and audit service;
- `alert-worker`: scheduled alert-rule evaluator;
- `recovery-worker`: durable executor for approved recovery commands;
- `retention-worker`: applies trace-retention windows;
- `driftzero-data`: persistent local SQLite volume.

See [docs/DEVOPS_RUNBOOK.md](docs/DEVOPS_RUNBOOK.md) for setup, service wiring, logs, CI, deployment, troubleshooting, and demo recovery. See [docs/HEALTH_EVENT_SCHEMA.md](docs/HEALTH_EVENT_SCHEMA.md) for the connector contract.

> **Demo boundary:** recovery is simulated. Recovery mutations have operator/admin API-key roles, but the project does not yet provide managed OIDC or complete tenant-scoped authorization. A real HTTPS control-plane adapter exists but is disabled unless server-side configuration is supplied. Do not attach consequential credentials to the public demo, and remove that deployment after judging.

## Project blueprint

## Product definition
**DriftZero** is an early-warning reliability control plane for deployed AI systems. It detects degrading behavior before it becomes a production incident, diagnoses the most likely cause, and recommends or safely executes a recovery playbook.

**Tagline:** Predict. Diagnose. Recover.

The product is organized into three layers:

1. **Pulse** — calculate model health, identify deterioration, and forecast its trajectory.
2. **Diagnose** — rank likely root causes and show the evidence behind them.
3. **Recover** — recommend a recovery playbook and execute approved actions with an audit trail.

The differentiator is not any single metric or automatic mitigation by itself. It is a simple, cohesive workflow that combines prediction, evidence-backed diagnosis, and controlled recovery.

---

## Master prompt: PRD first, implementation second

Copy the prompt below into your coding agent. Replace bracketed values if needed.

```text
You are a senior product manager, AI reliability engineer, data engineer, security architect, and full-stack product designer. Help me create a hackathon-ready but technically credible product named DriftZero.

PRODUCT IDEA

DriftZero is an early-warning reliability control plane for deployed AI systems. It continuously evaluates production model interactions, detects when reliability is deteriorating, predicts near-term health, diagnoses probable causes, and recommends or executes the safest recovery action.

Tagline: Predict. Diagnose. Recover.

Organize the product around exactly three layers:

1. Pulse — Detect degradation
- Produce a Model Health Score from 0–100.
- Health dimensions: quality, groundedness, semantic consistency, temporal consistency, safety, data/concept drift, operational reliability, latency, and cost.
- Show trends and trajectories, not only static values.
- Example: ShopAssist health 92 → 87 → 74 → 61; predicted health in 30 minutes: 48.
- Detect meaningful degradation while avoiding alerts caused by normal noise.

2. Diagnose — Find the likely cause
- Rank probable root causes.
- Show supporting and contradicting evidence for every diagnosis.
- Provide a root-cause confidence score that is calibrated and explicitly labeled as an estimate.
- Example diagnosis: knowledge freshness failure, supported by rising hallucinations and citation mismatches, stale retrieved documents, and falling paraphrase consistency while safety and latency remain normal.
- Preserve trace-level drill-down so users can inspect the requests behind every claim.

3. Recover — Take the safest action
- Generate a recovery playbook tied to the diagnosed cause.
- Possible actions: require citations, suppress unsupported answers, route low-confidence requests to a fallback, send conflicts to human review, roll back a prompt/model/configuration, refresh or disable stale retrieval sources, and re-evaluate after a defined number of requests.
- Separate recommendation, approval, execution, verification, and rollback.
- Default to human approval for consequential actions. Only low-risk, explicitly allow-listed actions may auto-execute.
- Record who or what initiated each action, its reason, affected traffic, result, and rollback status.

SIGNATURE EVALUATIONS

Semantic Stability Test:
- Generate meaning-preserving paraphrases of a factual question.
- Evaluate whether the material facts in the responses agree, rather than requiring identical wording.
- Display the variants, extracted claims, disagreements, stability score, evaluator confidence, and relevant traces.

Temporal Stability Test:
- Re-run a controlled question over time.
- Compare answers only when the model, prompt, configuration, tools, retrieval corpus/version, and evaluation policy are unchanged.
- If an input changed, attribute or annotate the change instead of claiming unexplained model drift.

IMPORTANT PRODUCT CONSTRAINTS

- Do not imply that the health score is objective truth. Make its weights, confidence, data coverage, sample size, and evaluation window visible.
- Do not claim that the product can guarantee or perfectly predict incidents.
- Do not market auto-remediation itself as unprecedented.
- Protect prompt/response data with redaction, tenant isolation, role-based access, configurable retention, and audit logs.
- Treat evaluator-model outputs as fallible. Allow human feedback, evaluator versioning, and replay.
- Never expose chain-of-thought. Store and display concise evidence and reason codes instead.
- Use deterministic seeded demo data so the main failure scenario works reliably during a presentation.

PRIMARY DEMO SCENARIO

Use an e-commerce support assistant called ShopAssist. It answers returns, refunds, and warranty questions using a retrieval knowledge base. A newly issued returns policy changes category-specific rules, but the retriever continues serving a retired document. Over a simulated stream of requests:

- health falls from 92 to 61;
- the 30-minute forecast falls to 48;
- hallucination/unsupported-claim rate increases;
- citation mismatch increases;
- semantic stability becomes critical;
- latency and safety remain normal;
- DriftZero diagnoses knowledge freshness failure;
- it recommends citation-required mode, suppressing unsupported responses, refreshing the corpus, routing low-confidence queries to a fallback, and human review;
- a user approves the playbook;
- the simulator executes it, evaluates the next 50 requests, and shows health recovering.

DEFAULT MVP ASSUMPTIONS

- This is a single-tenant hackathon demo with an architecture that can evolve to multi-tenant production.
- Use a modern web stack appropriate for a polished interactive dashboard. Prefer Next.js + TypeScript + Tailwind + shadcn/ui, PostgreSQL, and background jobs unless the existing repository dictates otherwise.
- Build provider adapters so monitored calls and recovery actions are not coupled to one model vendor.
- Begin with simulated telemetry and mock recovery adapters; clearly label simulations in the UI.
- Desktop-first, responsive, accessible, dark control-room visual style.

WORKING METHOD — MANDATORY PRD GATE

Phase 1 is product definition only. Before writing application code:

1. Inspect the repository and summarize relevant existing files, constraints, and reusable components.
2. Create docs/PRD.md containing:
   - executive summary and positioning;
   - problem statement and target users;
   - jobs to be done;
   - personas and permissions;
   - assumptions, non-goals, and terminology;
   - end-to-end user journeys;
   - prioritized functional requirements with IDs and acceptance criteria;
   - non-functional requirements;
   - information architecture and screen specifications;
   - health-score definition, normalization, weights, missing-data behavior, confidence, and versioning;
   - degradation detection and forecasting approach;
   - diagnosis taxonomy and evidence model;
   - recovery policy, approval levels, rollback, and verification;
   - semantic and temporal stability methodologies;
   - data model, event schema, and API contract proposal;
   - security, privacy, retention, tenancy, and audit requirements;
   - observability and evaluator-quality requirements;
   - seeded demo scenario and presentation script;
   - success metrics;
   - risks, mitigations, open questions, and post-MVP roadmap.
3. Create docs/DECISIONS.md containing unresolved decisions with your recommendation, alternatives, and trade-offs.
4. Create docs/IMPLEMENTATION_PLAN.md with milestones, dependencies, verification steps, and a requirement-to-test traceability table.
5. Critique the PRD for vague claims, unsafe automation, misleading metrics, missing states, and demo fragility. Revise it once.
6. Stop. Present a concise summary, the top decisions, and no more than five questions that genuinely block implementation. Explicitly ask for PRD approval.

Do not create application code, install dependencies, initialize services, modify infrastructure, or implement UI before I reply with “Approve PRD” (possibly with requested changes).

PHASE 2 — ONLY AFTER PRD APPROVAL

After I approve the PRD:

1. Convert the approved requirements into small implementation tasks.
2. Implement a vertical slice first: seeded ShopAssist telemetry → falling health trajectory → diagnosis → approved recovery → verification.
3. Then complete the remaining approved MVP requirements.
4. Keep mock and real integrations behind explicit adapters and label mock behavior.
5. Add tests for score calculation, degradation alerts, stability evaluation, recovery authorization, rollback, and the main user journey.
6. Run linting, type checks, unit/integration tests, and a browser-based end-to-end check.
7. Verify loading, empty, partial-data, healthy, warning, critical, recovery-in-progress, recovered, and failed-recovery states.
8. Update documentation when implementation differs from the PRD; never silently change product behavior.
9. Finish with a demo script, setup instructions, known limitations, and a requirement-to-evidence report.

QUALITY BAR

- The UI should tell one story: a system is healthy, begins to degrade, DriftZero explains why, an operator acts, and the system verifies recovery.
- Every important number must have a definition, time window, sample size/coverage, and drill-down evidence.
- Forecasts and diagnoses must show uncertainty.
- Recovery must be policy-controlled, reversible where possible, and auditable.
- Favor a convincing end-to-end vertical slice over many shallow integrations.

Start Phase 1 now. Do not implement the application yet.
```

---

## Recommended PRD-first workflow

### Stage 0 — Frame the product

**Inputs:** concept brief, hackathon constraints, target users, available data/integrations.

**Decisions:**

- Product name: DriftZero.
- Modules: Pulse, Diagnose, Recover.
- Primary persona: AI/ML platform or reliability engineer.
- Secondary persona: product/support operator who can inspect incidents but may not execute high-risk recovery.
- First scenario: ShopAssist knowledge-freshness failure.

**Exit gate:** one-sentence value proposition, target user, demo scenario, and explicit non-goals are agreed.

### Stage 1 — Produce the PRD

Run Phase 1 of the master prompt. Review the resulting PRD for:

- a precise MVP boundary;
- requirement IDs and testable acceptance criteria;
- definitions for every score and confidence value;
- failure, missing-data, and low-confidence states;
- permission and rollback rules for recovery actions;
- a deterministic demo plan;
- explicit assumptions and open questions.

**Exit gate:** reply `Approve PRD` only after the product behavior and safety boundaries are acceptable.

### Stage 2 — Technical design

Turn the approved PRD into:

- component architecture;
- event and relational schemas;
- API contracts;
- evaluator and scoring interfaces;
- recovery adapter interface;
- threat model;
- test plan and seeded data specification.

Recommended logical flow:

```text
Model/Agent traffic
        ↓
Telemetry ingestion → Redaction → Event store
        ↓                         ↓
Online signals               Evaluation jobs
        └──────────┬──────────────┘
                   ↓
          Health-score engine
                   ↓
     Trend + degradation detector
                   ↓
       Diagnosis/evidence engine
                   ↓
        Recovery policy engine
                   ↓
     Approval → Action adapter
                   ↓
       Verification + audit log
```

**Exit gate:** every MVP requirement maps to a component, data source, and verification method.

### Stage 3 — Build a vertical slice

Build only the ShopAssist story end to end:

1. Seed a healthy interval.
2. Introduce stale retrieval results.
3. Show health deterioration and a bounded forecast.
4. Surface the knowledge-freshness diagnosis with supporting evidence.
5. Approve a simulated recovery playbook.
6. Process 50 evaluation requests.
7. Show improved health and the audit trail.

**Exit gate:** the full story works from a clean setup without manual database repair or improvised demo actions.

### Stage 4 — Harden the MVP

Add:

- semantic and temporal stability pages;
- alert policies and notification states;
- recovery permissions, idempotency, timeouts, partial failure, and rollback;
- evaluator versioning and replay;
- privacy controls and data retention;
- loading, empty, partial-data, and error states;
- accessibility and responsive layout;
- automated unit, integration, and end-to-end tests.

**Exit gate:** test suite passes and each approved requirement has evidence.

### Stage 5 — Demo and ship

Prepare a five-minute narrative:

1. **Healthy:** ShopAssist is at 92.
2. **Early warning:** its trajectory declines and predicts 48 within 30 minutes.
3. **Diagnosis:** stale knowledge is identified with 87% estimated confidence and trace evidence.
4. **Recovery:** the operator reviews and approves a safe playbook.
5. **Verification:** health improves after the next 50 requests; actions are recorded.

Keep a deterministic reset control, preloaded seed data, and a fallback recording/screenshots in case a live model provider is unavailable.

---

## Repository documentation

- [`backend/README.md`](backend/README.md) — service setup, endpoints and verification.
- [`docs/DATA_MODEL.md`](docs/DATA_MODEL.md) — the data model, its enums, migrations and the session contract.

---

## MVP scope

### Must have

- Model fleet overview with health, trend, state, and recent incidents.
- Model detail with health history, component scores, coverage, sample size, and forecast uncertainty.
- Incident/diagnosis view with ranked causes, supporting/contradicting evidence, and trace drill-down.
- Recovery playbook with risk level, approval, simulated execution, verification, rollback state, and audit log.
- Semantic Stability Test.
- Temporal Stability Test with controlled-input/version checks.
- Seeded ShopAssist scenario and resettable demo.

### Should have

- Configurable score weights and thresholds.
- Alert rules.
- Human-review queue.
- Evaluator version and replay controls.
- Provider-neutral adapters and webhook/API ingestion contract.

### Later

- Real-time production integrations across several providers.
- Learned incident prediction trained on customer outcomes.
- Autonomous high-impact remediation.
- Enterprise SSO, complex tenant administration, billing, and broad compliance certification.

---

## Important scoring recommendation

Do not simply add raw metrics. Normalize them to a common 0–100 scale, version the policy, and expose the components.

```text
health = weighted mean of available component scores
         - explicit incident penalties
```

For each result, store and display:

- score and severity;
- evaluation window;
- request count and traffic coverage;
- component weights and policy version;
- confidence or uncertainty;
- missing components;
- evidence/traces;
- whether data is observed, inferred, or simulated.

If coverage is insufficient, return `Insufficient data` instead of a deceptively precise score. Forecasting should begin with a transparent trend model and prediction interval; advanced ML can come later after real incident labels exist.

---

## Key product decisions and rationale

- **One brand:** DriftZero is the product; Pulse is a module. This avoids confusing users with DriftZero and ModelPulse as parallel names.
- **Trajectory before complexity:** the near-term forecast makes the early-warning promise visible. Start with a transparent method because a sophisticated model without incident data would be hard to validate.
- **Evidence, not hidden reasoning:** diagnoses should expose metrics, traces, versions, and reason codes—not chain-of-thought.
- **Approval before consequential recovery:** the strongest demo still includes operator control, auditability, verification, and rollback.
- **Controlled temporal comparisons:** a changed answer is only meaningful if model, prompt, tools, corpus, and configuration are held constant or their changes are explicitly attributed.
- **Vertical slice first:** one reliable failure-and-recovery narrative is more persuasive than seven disconnected metric pages.

---

## Suggested first PRD approval checklist

Before approving the PRD, answer these questions:

1. Is the MVP a telemetry simulator, a proxy around real model calls, or both?
2. Which actions are simulations, and which can touch a real deployment?
3. Who is allowed to approve low-, medium-, and high-risk recovery actions?
4. What exact evidence makes “knowledge freshness failure” the leading diagnosis?
5. What constitutes successful recovery: threshold, evaluation window, request count, and no-regression checks?

Locate and inspect the DriftZero repository
- Confirm its path, branch, stack, existing files, and contribution instructions.
- Check README, AGENTS.md, package manifests, current changes, and remote configuration.
- Preserve any existing work.

Resolve product identity
- Product: DriftZero
- Modules: Pulse, Diagnose, Recover
- Tagline: Predict. Diagnose. Recover.
- Treat “ModelPulse” as either an internal engine name or remove it to prevent brand confusion.

Define the first credible MVP
- Use the ShopAssist knowledge-freshness incident as the primary vertical slice.
- Begin with seeded, deterministic telemetry.
- Simulate recovery actions behind provider-neutral adapters.
- Avoid attempting multiple shallow production integrations initially.

Write the PRD before application code
- docs/PRD.md
- docs/DECISIONS.md
- docs/IMPLEMENTATION_PLAN.md
- Include requirement IDs, acceptance criteria, permissions, data states, failure states, scoring definitions, security, demo flow, and non-goals.

Design the Health Score carefully
- Normalize component metrics to 0–100.
- Make weights, sample size, coverage, time window, missing data, confidence, and policy version visible.
- Return “Insufficient data” when the evidence cannot support a score.
- Use a transparent forecasting method for the MVP.

Specify diagnosis as evidence-backed inference
- Rank possible causes.
- Show supporting and contradicting evidence.
- Link diagnoses to trace-level observations.
- Display confidence as an estimate—not certainty or hidden AI reasoning.

Make recovery controlled and testable
- Separate recommendation, approval, execution, verification, and rollback.
- Require human approval for consequential actions.
- Record every action in an audit log.
- Define exactly what counts as successful recovery.

Critique and revise the PRD
- Look for misleading metrics, unsafe automation, vague requirements, missing edge states, and demo fragility.
- Revise once before presenting it for approval.

Stop at the PRD gate
- I’ll show you the important decisions and unresolved questions.
- I will not begin product implementation until you approve the PRD.

After approval
- Build the ShopAssist flow end to end.
- Test it.
- Commit logically grouped changes.
- Push only when the repository and branch expectations are confirmed and pushing is part of your instruction.
