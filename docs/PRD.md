# DriftZero Product Requirements Document

**Status:** Draft for approval  
**Version:** 1.0  
**Last updated:** 2026-09-06  
**Product:** DriftZero  
**Tagline:** Predict. Diagnose. Recover.

## 1. Executive summary

DriftZero is an early-warning reliability control plane for deployed AI systems. It helps AI platform and reliability teams recognize deteriorating model behavior before it becomes a customer-facing incident, identify the most likely cause using inspectable evidence, and carry out a policy-controlled recovery process.

The product is organized around one operational loop:

1. **Pulse** detects degradation, quantifies current model health, and projects its near-term trajectory.
2. **Diagnose** ranks probable causes and exposes supporting and contradicting evidence down to affected traces.
3. **Recover** proposes a reversible playbook, obtains the required approval, executes through an adapter, and verifies the result.

DriftZero does not claim that a health score is objective truth, that a forecast guarantees an incident, or that an automated diagnosis is infallible. Every important result must show its evaluation window, sample size, traffic coverage, source, policy or evaluator version, and uncertainty. Consequential recovery is human-approved by default.

The MVP is a polished, deterministic demonstration centered on **CampusGPT**, a university assistant whose retrieval layer serves stale examination-fee policy documents. The experience begins with healthy behavior, shows a credible decline, provides an evidence-backed knowledge-freshness diagnosis, guides an operator through a simulated recovery, and verifies improvement after 50 evaluation requests.

## 2. Current repository baseline

The repository is not a blank slate. As of this document, it contains a Python 3.12 FastAPI backend with:

- model registration and normalized telemetry ingestion;
- nine-dimensional, versioned health scoring;
- insufficient-data gates and transparent confidence calculation;
- a recent-slope 30-minute forecast with bounds;
- rule-based diagnosis with supporting and contradicting evidence;
- recovery recommendation, approval, simulated execution, verification, and auditing;
- deterministic CampusGPT reset and recovery behavior;
- redacted trace storage and trace-to-evidence links;
- a comprehensive relational schema for tenants, versions, sources, incidents, evaluations, alerts, review queues, and governance;
- SQLite for local use and portable PostgreSQL-compatible models and migrations;
- tests for the API lifecycle, scoring, redaction, evidence drill-down, schema, queries, migrations, and demo repeatability.

The following major product surfaces are not yet present or not yet exposed end to end:

- web interface;
- authentication, role-based authorization, and tenant enforcement;
- production telemetry adapters and background processing;
- full incident lifecycle APIs;
- semantic and temporal stability execution APIs and screens;
- alert rule management and notification delivery;
- human review workflow;
- real recovery integrations, action-level execution records, rollback controls, and policy administration;
- production observability, rate limiting, secrets management, and deployment automation.

This PRD treats existing backend behavior as a baseline to retain, not as proof that all corresponding product requirements are complete.

## 3. Problem statement

Teams operating AI applications often discover reliability problems through user complaints, support escalations, or coarse infrastructure alarms. Traditional monitoring can reveal latency, error rate, and cost, but it rarely answers the operational questions that matter for probabilistic AI behavior:

- Is answer quality or groundedness deteriorating even though the service is technically available?
- Is the change persistent, or merely normal sampling noise?
- Which model, prompt, tool, retriever, corpus, or policy change is the likely cause?
- Which requests support that conclusion, and which evidence contradicts it?
- What is the safest reversible mitigation?
- Did the mitigation actually improve behavior without creating a safety, latency, quality, or cost regression?

Without a unified workflow, teams manually combine observability dashboards, evaluation jobs, trace viewers, deployment systems, and incident notes. This increases mean time to detection and recovery and makes high-pressure decisions difficult to audit.

## 4. Product vision and positioning

### 4.1 Value proposition

For teams operating AI systems in production, DriftZero turns model telemetry and evaluations into an evidence-backed reliability lifecycle: early warning, probable-cause diagnosis, controlled mitigation, and verified recovery.

### 4.2 Differentiation

The differentiator is the cohesion of the workflow, not a single proprietary metric or the existence of auto-remediation. DriftZero should be memorable because every health change can be inspected, every diagnosis can be challenged, and every action is policy-controlled and verified.

### 4.3 Product principles

1. **Evidence over certainty.** Scores and diagnoses are estimates with visible inputs and limitations.
2. **Trajectory over snapshots.** Direction and persistence matter more than a single threshold crossing.
3. **Safe action over impressive automation.** Approval, reversibility, scope, and rollback are first-class.
4. **Traceability by default.** A user can move from a fleet signal to the requests and evidence behind it.
5. **Version everything that changes meaning.** Scores, evaluators, prompts, model configurations, tools, and corpora must be attributable.
6. **No hidden reasoning.** Show concise evidence, reason codes, and calculations; never expose chain-of-thought.
7. **Deterministic demo, production-shaped architecture.** The MVP must work reliably while preserving credible extension points.

## 5. Target users and jobs to be done

### 5.1 Primary persona: AI reliability engineer

Owns model health, observability, incident response, and reliability standards.

Jobs:

- detect behavior degradation before it becomes widespread;
- distinguish data, retrieval, prompt/model, safety, and infrastructure failures;
- inspect the evaluation and trace evidence behind an alert;
- select and safely apply a mitigation;
- verify recovery and provide an auditable incident record.

### 5.2 Secondary persona: ML/platform engineer

Owns model gateways, deployment configuration, retrievers, and provider integrations.

Jobs:

- onboard a model and send normalized telemetry and traces;
- compare health across releases and controlled-input versions;
- configure adapters, thresholds, policies, and retention;
- debug ingestion and evaluation coverage;
- implement and test recovery adapters.

### 5.3 Secondary persona: product or support operator

Needs to understand impact and inspect affected behavior but may not have permission to execute high-risk actions.

Jobs:

- see which user journeys and requests are affected;
- review evidence in plain language;
- send questionable responses for review;
- follow incident status without needing infrastructure access.

### 5.4 Governance persona: security or compliance reviewer

Jobs:

- confirm that sensitive content is redacted and retained appropriately;
- audit access, approvals, executions, and rollbacks;
- verify tenant isolation and least privilege;
- inspect policies without accessing unnecessary prompt content.

## 6. Personas and permissions

| Capability | Viewer | Operator | Admin | Service identity |
| --- | ---: | ---: | ---: | ---: |
| View fleet health and incidents | Yes | Yes | Yes | Scoped API |
| View redacted traces | Policy-dependent | Yes | Yes | No by default |
| Create feedback/review items | Yes | Yes | Yes | Scoped API |
| Approve low-risk recovery | No | Yes | Yes | Only if allow-listed |
| Approve medium/high-risk recovery | No | Policy-dependent | Yes | No by default |
| Execute approved recovery | No | Yes | Yes | Adapter-specific |
| Roll back recovery | No | Policy-dependent | Yes | Adapter-specific |
| Configure health/evaluator policy | No | No | Yes | No |
| Manage users, retention, adapters | No | No | Yes | No |
| Ingest telemetry | No | No | No | Yes |

The hackathon demo may use a clearly labeled local demo identity, but production mode must not be enabled until authentication and authorization are enforced server-side.

## 7. Scope

### 7.1 MVP must have

- fleet overview with health score, state, trend, forecast, coverage, and recent incident status;
- model detail with health timeline, dimension breakdown, score definition, sample size, missing-data state, and forecast interval;
- incident view with ranked diagnosis, estimated confidence, supporting and contradicting evidence, and trace drill-down;
- recovery plan view with risk, affected traffic, approval requirement, execution progress, verification criteria, audit trail, and rollback state;
- Semantic Stability Test based on agreement of material claims across meaning-preserving paraphrases;
- Temporal Stability Test that distinguishes uncontrolled input changes from unexplained behavior changes;
- deterministic CampusGPT scenario with one-action reset;
- accessible, responsive, desktop-first web experience;
- stable API contracts, background job boundaries, and tests for the primary lifecycle;
- explicit simulation labels anywhere data or actions are simulated.

### 7.2 MVP should have

- configurable score weights and thresholds;
- basic alert rules and in-product alert lifecycle;
- human review queue and evaluator feedback;
- provider-neutral ingestion and recovery interfaces;
- evaluator version display and replay;
- exportable incident summary;
- operational dashboard for ingestion and evaluator freshness.

### 7.3 Post-MVP

- multiple production provider integrations;
- SSO/SCIM and enterprise policy administration;
- learned forecasting and diagnosis calibrated on customer outcomes;
- multi-region processing and enterprise-scale tenancy;
- autonomous high-impact remediation;
- billing, compliance certification, and long-term analytics;
- mobile-first incident response.

### 7.4 Explicit non-goals

- guaranteeing that incidents will be predicted;
- replacing full observability, ticketing, or deployment platforms;
- displaying or storing chain-of-thought;
- training a proprietary foundation model in the MVP;
- treating evaluator-model output as ground truth;
- executing irreversible or high-impact production actions autonomously;
- storing unredacted prompt/response content by default;
- supporting every model provider during the hackathon.

## 8. Terminology

| Term | Definition |
| --- | --- |
| Monitored model | A deployed AI system or agent whose interactions are evaluated. |
| Trace | One request/response interaction plus operational and evaluation metadata; text is redacted before storage. |
| Health snapshot | A versioned aggregate of normalized dimensions over a defined window. |
| Coverage | Proportion of eligible traffic represented in a snapshot or evaluation. |
| Confidence | An estimate of evidence adequacy, never a probability that the score is objectively correct. |
| Incident | A tracked degradation episode connecting a signal, diagnosis, recovery, and verification. |
| Diagnosis | A ranked probable cause with estimated confidence and evidence. |
| Evidence item | A reason-coded observation that supports or contradicts a diagnosis and may link to traces. |
| Recovery plan | An ordered, risk-rated set of proposed actions tied to a diagnosis. |
| Verification run | A post-action evaluation against explicit recovery and no-regression criteria. |
| Controlled-input fingerprint | Hash of model, prompt, configuration, tools, corpus, and evaluation policy used to establish temporal comparability. |

## 9. End-to-end user journeys

### 9.1 Onboard and establish a baseline

1. An admin registers a monitored model and selects environment and retention policy.
2. A service identity receives a scoped ingestion credential.
3. The integration sends traces and/or normalized evaluation dimensions.
4. DriftZero shows ingestion status but withholds a health score until minimum evidence gates are met.
5. Once sufficient data exists, the product shows the first health snapshot with score policy, sample size, coverage, and source.
6. The operator marks or confirms a healthy comparison window.

### 9.2 Detect and investigate degradation

1. A model transitions from healthy to warning or critical, or its trajectory crosses an early-warning rule.
2. DriftZero opens or updates an incident and shows what changed, when, and for how much traffic.
3. The operator inspects component scores, forecast interval, version changes, and related traces.
4. Diagnose ranks causes with estimated confidence and both supporting and contradicting evidence.
5. The operator can agree, disagree, or mark the result uncertain; feedback is versioned and auditable.

### 9.3 Approve, execute, and verify recovery

1. DriftZero generates a playbook tied to the selected diagnosis.
2. The user reviews each action's risk, scope, reversibility, prerequisites, and rollback method.
3. Server-side policy determines the required approval level.
4. An authorized user approves or rejects the plan; approval does not itself execute it.
5. Execution records the actor, adapter, idempotency key, affected traffic, start/end time, result, and failure mode for each action.
6. DriftZero evaluates a defined post-action request window.
7. The plan is marked recovered only if the health target and no-regression checks pass; otherwise it becomes failed or remains under verification.
8. The operator can initiate a rollback when supported.

### 9.4 Run a Semantic Stability Test

1. The operator chooses a factual question, model version, evaluator version, and variant count.
2. DriftZero creates meaning-preserving paraphrases and records the seed and generator version.
3. The monitored system answers each variant under equivalent controlled inputs.
4. The evaluator extracts material claims, normalizes comparable values, and measures agreement.
5. The UI shows variants, claims, disagreements, stability score, evaluator confidence, coverage, and traces.
6. Low-confidence or high-impact disagreements can be sent to human review.

### 9.5 Run a Temporal Stability Test

1. The operator selects a controlled question and schedule or comparison window.
2. Each run records the controlled-input fingerprint.
3. If inputs are unchanged, material claim differences contribute to a temporal stability result.
4. If inputs changed, the test is annotated with the changed fields and must not label the result unexplained drift.
5. The user can compare answers, claims, input versions, evaluator versions, and traces over time.

## 10. Functional requirements

Acceptance criteria use **Given / When / Then** and are binding for the MVP unless marked Should.

### 10.1 Fleet and onboarding

**FLT-001 — Register and list monitored models (Must).**  
Given an authorized admin, when a valid model is registered, then it appears in the fleet with a stable ID, provider, environment, status, retention setting, and created time. Duplicate names within a tenant are rejected.

**FLT-002 — Fleet health overview (Must).**  
Given one or more models, when the fleet page loads, then each row/card shows current state, current score or `Insufficient data`, change over the selected period, forecast direction when available, coverage, freshness, and open incident severity.

**FLT-003 — Model version attribution (Must).**  
Given a monitored model, when a prompt, model identifier, configuration, tool set, corpus, or evaluation policy changes, then DriftZero records a new controlled-input fingerprint and displays the changed fields in relevant comparisons.

**FLT-004 — Ingestion health (Should).**  
Given configured ingestion, when events are delayed, invalid, duplicated, or rejected, then an admin can see counts, last successful event time, reason codes, and retry guidance without exposing secrets.

### 10.2 Pulse

**PUL-001 — Versioned health score (Must).**  
Given sufficient data, when a snapshot is calculated, then it stores and displays score, state, nine component values, normalized weights, available-weight renormalization, window, sample size, trace count, coverage, confidence, missing dimensions, signal source, and policy version.

**PUL-002 — Insufficient-data behavior (Must).**  
Given sample size below 20, traffic coverage below 0.30, or available configured weight below 0.50 under `health-v1`, when scoring runs, then no numeric overall score is returned and the reason is shown as `Insufficient data`.

**PUL-003 — Health states (Must).**  
Under `health-v1`, scores at or above 80 are healthy, scores from 65 through 79.9 are warning, and scores below 65 are critical. Thresholds must be visible and versioned rather than hard-coded only in the UI.

**PUL-004 — Trend and degradation detection (Must).**  
Given consecutive scored snapshots, when a sustained decline or threshold transition meets the configured rule, then DriftZero opens or updates one incident, records the triggering rule and baseline, and avoids duplicate incidents for the same episode.

**PUL-005 — Forecast with uncertainty (Must).**  
Given at least two valid snapshots, when a forecast is requested, then DriftZero shows horizon, predicted score, lower and upper bounds, direction, change per hour, method, training/evidence window, and generated time. The interface labels it as an estimate.

**PUL-006 — Forecast evaluation (Should).**  
Given a forecast whose horizon has elapsed, when an actual snapshot becomes available, then the actual is attached to the forecast and aggregate error/coverage can be measured by method version.

**PUL-007 — Trace drill-down (Must).**  
Given a scored metric or evidence item, when the user drills down, then only traces contributing to the relevant window/metric are shown, with redacted text, operational metadata, evaluation results, and version context.

### 10.3 Diagnose

**DIA-001 — Ranked causes (Must).**  
Given an active degradation with enough evidence, when diagnosis runs, then it returns at least one ranked probable cause from a versioned taxonomy and may return `insufficient_evidence` rather than forcing a confident answer.

**DIA-002 — Evidence model (Must).**  
Each diagnosis includes estimated confidence, reason codes, supporting evidence, contradicting evidence, relevant baseline/current values, and trace links where available.

**DIA-003 — Initial cause taxonomy (Must).**  
The MVP supports knowledge freshness failure, safety regression, operational reliability failure, model or prompt instability, and insufficient evidence. The architecture must permit adding causes without changing historical records.

**DIA-004 — Version and change correlation (Must).**  
When a degradation overlaps a model, prompt, configuration, tool, corpus, or evaluator change, that change is displayed as evidence or context; correlation is not labeled causation without supporting evidence.

**DIA-005 — Human feedback (Should).**  
An authorized user can agree, disagree, or mark uncertain on a diagnosis, add a concise note, and see which diagnosis/evaluator version received the feedback.

**DIA-006 — Diagnosis lifecycle (Must).**  
Diagnoses and incidents have explicit open, mitigating/verifying, resolved, and failed states. Resolution records the responsible recovery or operator decision.

### 10.4 Recover

**REC-001 — Cause-specific playbook (Must).**  
Given a diagnosis, when a playbook is generated, then it contains ordered actions with code, title, purpose, risk, prerequisites, affected scope, reversibility, timeout, verification contribution, and rollback method.

**REC-002 — Approval separation (Must).**  
Recommendation, approval, execution, verification, and rollback are distinct transitions. An unapproved plan cannot execute, and an approval records actor, role, time, plan version, and optional rationale.

**REC-003 — Risk policy (Must).**  
Low-risk, explicitly allow-listed actions may be configured for automatic approval in production; medium- and high-risk actions require a human by default. The demo uses human approval for the complete playbook.

**REC-004 — Idempotent action execution (Must).**  
Replayed requests do not execute a plan twice. Each action attempt has its own status, adapter, actor, reason, start/end time, timeout, affected traffic, result, error, and rollback fields.

**REC-005 — Partial failure (Must).**  
If one action fails or times out, successfully completed actions remain recorded, dependent actions are skipped or halted according to policy, and the UI presents recovery and rollback options.

**REC-006 — Verification (Must).**  
A plan is marked recovered only after the required request count and window are complete, the target health threshold is met, and no-regression checks for safety, latency, reliability, quality, and cost pass.

**REC-007 — Rollback (Must for real adapters).**  
Given a reversible executed action, when an authorized operator requests rollback, then DriftZero checks current state, requires the appropriate approval, executes idempotently, records the result, and re-verifies health.

**REC-008 — Simulation boundary (Must).**  
Simulated plans, actions, data, and results are visually and programmatically labeled. A simulated adapter cannot be mistaken for a production action.

### 10.5 Stability evaluations

**SEM-001 — Meaning-preserving variants (Must).**  
The Semantic Stability Test records the source question, deterministic seed, generator/version, variants, model fingerprint, evaluator version, and trace for each response.

**SEM-002 — Material claim agreement (Must).**  
Stability is based on extracted material claims and normalized values, not identical wording. The output identifies missing, conflicting, and unsupported claims per variant.

**SEM-003 — Transparent result (Must).**  
The result shows score, verdict, confidence, sample/variant count, claim coverage, disagreements, evaluator limitations, and links to variants and traces.

**TMP-001 — Controlled-input check (Must).**  
Every Temporal Stability run compares controlled-input fingerprints before evaluating drift.

**TMP-002 — Changed-input attribution (Must).**  
If inputs differ, the test records the changed fields and returns an attributed or inconclusive result rather than unexplained temporal drift.

**TMP-003 — Comparable-run result (Must).**  
For matching fingerprints, the test compares material claims over time and displays score, verdict, confidence, run times, evaluator version, and traces.

### 10.6 Alerts and review

**ALT-001 — Alert rules (Should).**  
Admins can create threshold, transition, trajectory, coverage, and evaluation-freshness rules scoped to a model/environment, with severity and cooldown.

**ALT-002 — Alert lifecycle (Should).**  
Alerts can be firing, acknowledged, or resolved; transitions are audited and linked to an incident.

**REV-001 — Human review queue (Should).**  
Users can send traces, disagreements, diagnoses, or recovery exceptions to a queue with priority, assignment, due time, status, and resolution.

### 10.7 Governance

**GOV-001 — Authentication and tenant isolation (Must before public deployment).**  
Every non-health endpoint requires authentication; all reads and writes are constrained to the caller's tenant and tested against cross-tenant access.

**GOV-002 — Least-privilege authorization (Must before public deployment).**  
Server-side permissions enforce the matrix in Section 6. UI hiding alone is not authorization.

**GOV-003 — Redaction and retention (Must).**  
Raw prompt and response text is redacted before persistence. Records retain hashes and redaction-policy version. Tenant/model retention policies purge expired traces while preserving aggregate and audit integrity.

**GOV-004 — Append-only audit trail (Must).**  
Policy changes, access to sensitive trace views, diagnoses, feedback, approvals, executions, failures, rollbacks, and demo resets produce timestamped audit events with actor type and target.

**GOV-005 — Evaluator governance (Must).**  
Evaluator provider/model, prompt/configuration hash, calibration status, and active dates are versioned. Historical results remain linked to the original evaluator version and are replayable.

## 11. Information architecture and screen specifications

### 11.1 Global shell

- left navigation: Fleet, Incidents, Evaluations, Review, Policies, Audit;
- environment and simulation indicators visible globally;
- top bar: time range, data freshness, tenant, user role;
- global states: loading, empty, stale data, partial data, forbidden, and service error;
- keyboard-accessible navigation and visible focus.

### 11.2 Fleet page

- summary cards: healthy/warning/critical/insufficient counts and open incidents;
- sortable model table with score, state, change, forecast, coverage, freshness, and incident;
- filters for environment, provider, state, and data source;
- CampusGPT demo reset control isolated from production controls.

### 11.3 Model detail / Pulse

- current health with score definition popover and simulation/source label;
- timeline with state thresholds and forecast interval;
- dimension contribution table showing value, weight, weighted contribution, missing state, and change;
- window, sample size, trace count, coverage, confidence, policy version, and data freshness;
- version-change markers and related incident panel;
- trace list with privacy-safe fields and filtering.

### 11.4 Incident / Diagnose

- incident state, severity, start time, affected model/version, and impact summary;
- ranked causes with estimated-confidence label;
- side-by-side supporting and contradicting evidence;
- metric changes and version/context changes;
- trace drill-down drawer;
- human feedback control and linked recovery plan.

### 11.5 Recovery

- ordered action list with risk, scope, reversibility, prerequisite, and rollback;
- policy decision and required approver;
- separate approve/reject and execute controls;
- action-level progress and partial-failure representation;
- verification criteria and progress toward required requests;
- before/after health and no-regression comparison;
- immutable audit timeline.

### 11.6 Evaluations

- tabs for semantic and temporal tests;
- run configuration and history;
- variant/run comparison grid;
- extracted claim matrix with conflicts emphasized;
- controlled-input and evaluator-version details;
- inconclusive/changed-input states that cannot be confused with failures.

### 11.7 Required visual states

Every principal screen must be verified in: loading, empty, healthy, warning, critical, insufficient/partial data, stale data, recovery recommended, awaiting approval, executing, verifying, recovered, failed, partially failed, rollback running, and forbidden states where applicable.

## 12. Health score specification

### 12.1 Dimensions and `health-v1` weights

| Dimension | Weight | Operational meaning |
| --- | ---: | --- |
| Quality | 0.18 | Task correctness or usefulness against configured evaluators. |
| Groundedness | 0.20 | Degree to which material claims are supported by approved evidence. |
| Semantic stability | 0.12 | Agreement of material facts across meaning-preserving variants. |
| Temporal stability | 0.08 | Agreement over comparable repeated runs. |
| Safety | 0.15 | Compliance with configured safety policy. |
| Drift | 0.10 | Health of input, data, and retrieval distributions; 100 is healthier. |
| Reliability | 0.08 | Successful, non-timeout operational completion. |
| Latency | 0.04 | Performance against configured latency objective; 100 is healthier. |
| Cost | 0.05 | Cost efficiency against configured budget/objective; 100 is healthier. |

All dimensions are normalized to 0–100 and oriented so higher is healthier. Raw metric definitions, normalization curves, evaluator versions, and objectives must be stored in or referenced by the health policy.

### 12.2 Formula

For available dimensions `A`:

```text
health = sum(score[d] * weight[d] for d in A)
         / sum(weight[d] for d in A)
```

Missing dimensions are not interpreted as zero. The score is withheld if the sample size is below 20, request coverage is below 0.30, or available dimension weight is below 0.50. Configurable future policies must be versioned.

For `health-v1`, confidence is an evidence-adequacy indicator:

```text
confidence = clamp(coverage, 0, 1)
             * min(1, sample_size / 100)
             * available_dimension_weight
```

This value must be labeled as coverage/confidence, not presented as a calibrated probability of correctness.

### 12.3 Incident penalties

The MVP does not apply hidden incident penalties. A future policy may apply explicit, versioned penalties only when the UI can display the reason, magnitude, duration, and source event.

## 13. Degradation detection and forecasting

### 13.1 Detection baseline

The first implementation should combine:

- state transition: healthy to warning/critical or warning to critical;
- absolute score drop over a configurable window;
- dimension-specific deterioration;
- persistence across a minimum number of snapshots;
- minimum sample/coverage gates;
- cooldown and incident deduplication.

Suggested demo rule: open a high-severity incident when score is critical and has declined by at least 15 points from the healthy baseline within 45 minutes, with at least two qualifying snapshots. This recommendation must be tested against the deterministic CampusGPT sequence.

### 13.2 Forecast baseline

The repository uses the latest observed slope, up to the six most recent snapshots, and a variability-based interval. This remains acceptable for the MVP because it is inspectable. The product must disclose `recent_slope_v1`, horizon, evidence window, generated time, and interval. Forecasts are suppressed when timestamps are invalid or fewer than two scored points exist.

Before a learned forecaster is introduced, the team must have retained actual outcomes, agreed evaluation targets, backtesting, calibration/coverage analysis, and a safe fallback when the model is stale.

## 14. Diagnosis taxonomy and evidence model

The initial taxonomy is:

| Cause | Typical supporting evidence | Typical contradicting evidence |
| --- | --- | --- |
| Knowledge freshness failure | groundedness decline, citation mismatch, stale/superseded documents, semantic disagreement, corpus lag | normal freshness, no stale documents, simultaneous infrastructure failure |
| Safety regression | safety score/flag increase after policy/model change | unchanged safety metrics and evaluator version |
| Operational reliability failure | errors, timeouts, latency/reliability deterioration, provider incident | stable operational metrics with behavioral-only decline |
| Model or prompt instability | semantic/temporal instability, prompt/model change correlation | stable outputs under controlled inputs |
| Insufficient evidence | weak, contradictory, missing, or low-coverage signals | a strong supported pattern crossing a versioned rule |

Each evidence item contains a stable reason code, human-readable summary, metric or entity, observed values/change, polarity, source, window, evaluator/policy version, and trace links. Confidence is explicitly labeled estimated. Diagnosis rules and learned models must have a version, and the UI must permit comparison against human feedback.

## 15. Recovery policy

### 15.1 Lifecycle

```text
recommended → approved/rejected → executing → verifying → recovered/failed
                                          ↘ rollback requested → rolled back → verifying
```

### 15.2 Approval levels

- **Low risk:** reversible, limited blast radius, no user-visible policy change beyond safe fallback; may be auto-approved only when explicitly allow-listed.
- **Medium risk:** changes routing, retrieval, or response behavior; human operator/admin approval by default.
- **High risk:** broad traffic impact, restrictive policy change, or uncertain reversibility; admin approval, explicit scope, and rollback readiness required.

The highest-risk action determines the minimum plan approval. Any plan mutation after approval invalidates the approval and creates a new version.

### 15.3 Execution safeguards

- stable idempotency key per plan version;
- precondition and current-state checks;
- adapter allow-list and scoped credentials;
- action timeout and retry policy;
- dependency ordering and halt/continue behavior;
- blast-radius limit and optional canary percentage;
- action-level audit and result records;
- no secrets in logs or response bodies.

### 15.4 Verification and rollback

CampusGPT verification requires 50 post-action requests, adequate coverage, health at or above the configured recovery target, and no material regression in safety, latency, reliability, quality, or cost. A failed verification must never be shown as recovered. Rollback eligibility, action, approval, and verification are recorded separately.

## 16. Data and API contract

### 16.1 Core entities

The existing schema is the target conceptual model: tenant, monitored model, model version, knowledge source/document, trace, health policy/snapshot/forecast, incident, diagnosis/evidence, recovery plan/action/execution, verification run, evaluator version, stability test/variant/claim, evaluation feedback, alert rule/alert, review item, and audit event.

### 16.2 Event envelope

All ingestible events should share:

```json
{
  "event_id": "provider-or-client-unique-id",
  "event_type": "trace.observed",
  "schema_version": "1",
  "tenant_id": "resolved-from-credential",
  "model_id": "stable-model-id",
  "occurred_at": "RFC3339 UTC timestamp",
  "received_at": "server-assigned RFC3339 UTC timestamp",
  "source": "observed",
  "payload": {},
  "metadata": {
    "model_version_id": "optional-version-id",
    "correlation_id": "optional-correlation-id"
  }
}
```

The server must derive tenant identity from authentication rather than trusting a client-supplied tenant ID. Event IDs provide deduplication. Unknown schema versions are rejected with a stable reason code.

### 16.3 API conventions

- versioned base path `/api/v1`;
- UTC RFC3339 timestamps;
- cursor pagination for potentially large lists;
- stable error envelope with machine-readable `error`, human-readable `detail`, and optional field/retry information;
- idempotency keys for ingestion batches, approvals, executions, and rollbacks;
- optimistic concurrency or version checks for mutable policies;
- OpenAPI contract tests;
- request IDs in response headers and logs;
- no raw sensitive text in errors.

Existing endpoints remain supported while APIs are expanded. Any breaking contract change requires versioning or migration notes.

## 17. Security, privacy, and tenancy

- redact before persistence using a versioned policy;
- encrypt data in transit and at rest in production;
- isolate tenants in every query and object relationship;
- short-lived, scoped service credentials with rotation;
- role-based permissions enforced in API services;
- secrets stored outside the database and logs;
- configurable retention and purge jobs;
- audit sensitive trace access;
- protect ingestion against replay, oversized payloads, invalid timestamps, and abusive rates;
- apply CSRF protection where cookie authentication is used;
- use secure headers and strict origin configuration;
- threat-model recovery adapters as privileged execution boundaries;
- prevent externally supplied text from becoming executable instructions;
- provide tenant export/deletion workflows after MVP without corrupting audit obligations.

The current service must remain local/private until authentication, authorization, tenant enforcement, and production adapter safeguards are complete.

## 18. Non-functional requirements

| Area | MVP requirement |
| --- | --- |
| Availability | Demo vertical slice works from a clean reset without external providers. Production target to be defined before launch. |
| Performance | Fleet/model reads p95 under 500 ms for demo dataset; ingestion acknowledgement p95 under 300 ms excluding async evaluation. |
| Scale | Architecture supports async batch evaluation and PostgreSQL; hackathon proof target is 10 models and 100k stored traces. |
| Freshness | UI displays last successful ingestion/evaluation time and flags stale data. |
| Accessibility | WCAG 2.2 AA target; keyboard operation, focus visibility, contrast, labels, reduced motion. |
| Reliability | Idempotent ingest/action operations; no duplicate plan execution; deterministic reset. |
| Observability | Structured logs, request/correlation IDs, metrics, health/readiness checks, job lag, evaluator failures. |
| Testability | Unit, integration, migration, contract, security, and browser-based end-to-end coverage for critical flows. |
| Portability | SQLite local demo; PostgreSQL production path; containerized backend and frontend. |
| Maintainability | Typed contracts, versioned policies, adapter interfaces, migrations, documented decision records. |

## 19. Evaluator quality and production monitoring

DriftZero monitors its own evaluators. Required signals include evaluation volume, failure/timeout rate, latency, cost, confidence distribution, disagreement with human feedback, drift by evaluator version, and replay differences. Low evaluator coverage or freshness must reduce confidence or yield an inconclusive state rather than silently reusing stale results.

Forecast monitoring includes absolute error, bias, interval coverage, and performance by health state. Diagnosis monitoring includes top-k agreement with reviewed incidents, calibration by confidence bucket, abstention rate, and time to confirmed cause. Recovery monitoring includes approval latency, action success/timeout/rollback rate, verification success, and no-regression failures.

## 20. Seeded CampusGPT demo

### 20.1 Data story

CampusGPT answers examination-fee questions using a retrieval corpus. A newer policy document changes the deadline, but the active index continues serving the superseded document. Seeded telemetry produces health scores `92 → 87 → 74 → 61`; the 30-minute forecast is `48`. Groundedness, drift health, and semantic stability fall while safety, latency, and reliability remain stable.

DriftZero diagnoses `knowledge_freshness_failure` at approximately 0.87 estimated confidence and recommends:

1. require citations;
2. suppress unsupported generation;
3. refresh the retrieval index;
4. route low-confidence requests to a fallback;
5. queue conflicting responses for human review.

The operator approves the simulated plan. The system executes it, evaluates 50 requests, and records a recovered score of approximately 84.2 with a complete audit trail.

### 20.2 Five-minute script

1. **Healthy:** show CampusGPT at 92 with strong evidence coverage.
2. **Early warning:** advance/reset the deterministic scenario; show decline and 48 forecast with bounds.
3. **Diagnosis:** open the incident, stale-document evidence, conflicting paraphrases, and stable safety/latency contradiction evidence.
4. **Recovery:** inspect risks and simulation labels, approve, then execute.
5. **Verification:** show 50-request evaluation, health improvement, no-regression checks, and audit events.

### 20.3 Demo resilience

- deterministic seed and one-action reset;
- no dependency on a live model provider;
- clearly labeled simulated data/actions;
- pre-rendered backup screenshots or recording;
- startup self-check and visible fixture version;
- never require manual database edits during the presentation.

## 21. Success metrics

### 21.1 Hackathon success

- 100% completion rate for the seeded end-to-end demo from a clean setup;
- an evaluator can trace every displayed key number to its definition and evidence;
- an evaluator can distinguish observed, inferred, and simulated results;
- unapproved recovery execution is demonstrably blocked;
- recovery verification and audit trail are visible;
- primary browser flow completes in under five minutes without console or server errors.

### 21.2 Product outcome metrics

- median time from qualifying degradation to incident creation;
- median time from incident to confirmed cause;
- median time from approved mitigation to verified recovery;
- proportion of incidents detected before external report;
- diagnosis top-k agreement and confidence calibration;
- forecast interval coverage and error;
- percentage of important results with complete evidence lineage;
- recovery verification success and rollback rate;
- evaluator/human disagreement rate;
- false/noisy alert rate and alert acknowledgement time.

## 22. Risks and mitigations

| Risk | Consequence | Mitigation |
| --- | --- | --- |
| False precision in score | Users over-trust a composite metric | Show components, gates, confidence, coverage, window, policy; allow insufficient data. |
| Evaluator bias/failure | Bad evaluations become bad incidents | Version, replay, monitor, calibrate, and collect human feedback. |
| Spurious diagnosis | Incorrect mitigation | Show contradictions, allow abstention, require approval and preconditions. |
| Unsafe automation | Production impact | Default human approval, allow-list, least privilege, canary, timeout, rollback. |
| Sensitive trace exposure | Privacy/security incident | Redact before storage, retention, access audit, tenant isolation. |
| Forecast overclaim | Misleading early-warning promise | Display method and interval; backtest; label estimate. |
| Demo fragility | Failed presentation | Deterministic fixtures, local adapters, reset, backup recording. |
| Schema ahead of behavior | UI suggests unsupported features | Label implemented/planned states and build vertical flows before breadth. |
| Alert fatigue | Operators ignore warnings | Persistence, cooldown, deduplication, coverage gates, feedback. |
| Adapter inconsistency | Duplicate or partial actions | Idempotency, state checks, action records, reconciliation, rollback. |

## 23. Assumptions

- The initial delivery is a single-tenant hackathon demo, but tenant IDs remain in the schema.
- The web product will be desktop-first and use a dark control-room visual language.
- The existing FastAPI/SQLAlchemy backend and contracts are retained unless a documented decision changes them.
- PostgreSQL is the production persistence target; SQLite remains the local demo default.
- Initial telemetry may contain already normalized dimension values while raw-to-normalized evaluators are added incrementally.
- Production actions remain behind adapters and disabled until governance requirements pass.

## 24. Open decisions requiring approval

1. **Frontend stack:** recommend Next.js, TypeScript, Tailwind, and an accessible component foundation; alternative is a lighter Vite SPA.
2. **Authentication for first hosted demo:** recommend managed OIDC with server-side sessions; a local demo identity remains available only in explicit demo mode.
3. **Async jobs:** recommend a PostgreSQL-backed job abstraction for MVP simplicity, with Redis/worker infrastructure introduced only if load requires it.
4. **Health policy editing:** recommend read-only policy inspection in the first vertical slice, then admin editing with version creation—not in-place mutation.
5. **Alert delivery:** recommend in-product alerts first; email/Slack integrations after lifecycle and deduplication are proven.
6. **Recovery target:** recommend configurable target with CampusGPT fixed at `>= 80`, 50 requests, `>= 0.90` coverage, and no material safety/reliability regression.
7. **Source-of-truth for normalized dimensions:** recommend storing both raw evaluator outputs and normalized values/version once evaluator pipelines are implemented.

## 25. Release gates

### PRD approval gate

- MVP boundary, scoring semantics, safety boundary, demo story, and open decisions approved.

### Vertical-slice gate

- seeded ingest → degradation → incident → diagnosis → approval → execution → verification works through the web UI and API;
- trace/evidence lineage is visible;
- automated critical-path tests pass.

### Hosted-demo gate

- authentication and server-side authorization enabled;
- tenant constraints verified;
- no real recovery adapters enabled;
- security/privacy review and dependency scan completed;
- operational runbook and reset procedure tested.

### Production-adapter gate

- adapter threat model and least-privilege credentials reviewed;
- idempotency, timeout, partial failure, rollback, reconciliation, and audit tested in a non-production environment;
- explicit approval policy and blast-radius controls enabled;
- on-call ownership and incident procedure defined.

## 26. Approval record

This document is a draft. Application implementation beyond documentation should begin only after the product owner approves the PRD and resolves or explicitly defers the blocking decisions in Section 24.
