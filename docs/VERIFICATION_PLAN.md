# Evidence-grounded claim verification — implementation plan

## Principle

The evaluator LLM may **extract** claims and **classify** them against supplied evidence.
It must never produce a groundedness, quality or health number. Every displayed metric is
calculated in backend Python from documented formulas over the verdicts. This is the failure
mode the design exists to prevent.

## What already exists and is reused, not replaced

| Existing | Reuse |
|---|---|
| `app/groq_evaluation.py` — `GroqClient` (urllib, credential-safe, 1 MiB cap, bounded timeout) | The provider transport for Groq. Add a Gemini sibling with the same shape. |
| `evaluate_completions` — deterministic scoring, no LLM | Left untouched; it already embodies the same principle. |
| `app/scoring.py` — `DIMENSION_WEIGHTS`, `calculate_health`, 80/65 thresholds | Health scoring stays. Verification feeds `groundedness`/`quality` into it. |
| `app/hallucination.py` — `score_groundedness` shape (`None`, never a flattering default) | The pattern every new scorer follows. |
| `KnowledgeSource` / `KnowledgeDocument` (`db/models.py:291,316`) | Existing corpus tables; the new verification corpus is versioned and approval-gated, and links to these for the ShopAssist demo. |
| `app/redaction.py` | Applied before any persistence, per existing convention. |
| `app/security.py` — auth, tenant principal, rate limit, body cap | New routes follow it. |
| `ControlPlaneHttpAdapter` (`recovery.py:214`) | The precedent for urllib + SSRF-ish URL validation. |

No new HTTP dependency: providers use `urllib`, matching `GroqClient`. Only `pypdf` is added.

## Status

**Delivered (steps 1, 2, 5, 7 and the explanation view):** six tenant-scoped tables +
migration `0013`; the deterministic metric formulas; deterministic claim comparison;
approval-gated evidence retrieval; the offline claim extractor; the evaluation pipeline;
the ShopAssist corpus; nine API endpoints; and the dashboard Verification page.

**Not yet built:** file/website import behind the new source model (the teammate's
`EvidencePage` covers PDF/CSV upload against *their* `EvidenceSource` tables), the Gemini and
Groq verifier wiring, health-snapshot integration, Docker/CI updates.

### Overlap to resolve with the team

A teammate shipped `EvidenceSource`/`EvidenceChunk` plus an import-and-review UI in
`0012_evidence_ingestion`. That covers ingestion; this work covers claim extraction,
verification and scoring. Two parallel source tables now exist. The obvious convergence is to
point `verification/retrieval.py` at their approved chunks -- it needs `structured_facts` on
those rows for deterministic comparison to fire, otherwise claims fall through to the LLM
verifier.

## Build order

**1. Foundation** — six tenant-scoped tables (`VerificationSource`, `CorpusVersion`,
`EvidenceChunk`, `EvaluationRun`, `ExtractedClaim`, `ClaimVerdict`), additive reversible
migration `0012`, Pydantic schemas and enums.

**2. Deterministic core** — the anti-arbitrary-scoring heart, fully testable with no provider:
- `verification/metrics.py` — weights central 3 / supporting 2 / minor 1; groundedness,
  confirmed-hallucination rate, evidence coverage; `None` when there are no factual claims;
  central contradiction caps groundedness at 40; correctness capped at 50 on central
  contradiction; `insufficient_evidence` never counted as hallucination.
- `verification/deterministic.py` — numbers, prices, percentages, dates, durations, booleans,
  IDs, enumerated policy values compared before any LLM is consulted.
- `verification/retrieval.py` — approved + active corpus versions of the same tenant only,
  max 3 chunks, structured-fact matches preferred, retired sources excluded.

**3. Provider abstraction** — `verification/providers.py`: protocol + Groq and Gemini
implementations, strict schema validation of extractor and verifier JSON, never executing
returned content, bounded retry with exponential backoff.

**4. Ingestion** — `verification/ingest.py`: PDF/JSON/CSV/TXT/MD parsing, plus website import
behind SSRF guards (scheme allow-list, private/loopback/link-local/reserved rejection,
per-redirect revalidation, timeouts, redirect and size caps, content-type allow-list, no
credential forwarding, HTML sanitisation).

**5. Service + API** — the eleven endpoints, tenant-scoped, each approval/rejection/retirement
/evaluation emitting an audit event via the existing `_audit` helper.

**6. Health integration** — verification results feed the existing snapshot path. Hard rules
added: critical safety violation forces `critical`; under 20 evaluated interactions gives
`insufficient_data`; evidence coverage under 60% makes groundedness unavailable; evaluator
failure never reuses an old score.

**7. ShopAssist corpus + the stale-policy scenario** — the vertical slice that proves it.

**8. Dashboard** — Verification Sources management and the metric explanation view.

**9. Tests, CI, Compose, docs** — all tests mock the providers; no test needs a real key.

## Scope note

This is a large brief. The order above is deliberately vertical: steps 1–2 make the
scoring provably non-arbitrary and are testable with no provider at all, so the guarantee that
matters most lands first and everything after builds on a verified base.
