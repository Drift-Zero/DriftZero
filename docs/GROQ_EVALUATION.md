# Groq import and deterministic evaluation

DriftZero uses Groq only to obtain the monitored model's response. It does not
send that response to a second evaluator model. Correctness, evidence matching,
format adherence, safety rules, response stability, provider reliability,
latency, estimated cost, confidence, and the risk-sensitive health score are
calculated by local Python code.

```text
Browser → DriftZero backend → Groq model
              ↓                 ↓
         declared rubric ← response + API telemetry
              ↓
       deterministic calculations
              ↓
       redacted trace + snapshot + audit event
```

## Configure the key

Create a Groq API key and set it only in the backend environment:

```bash
DRIFTZERO_GROQ_API_KEY=gsk_your_key
DRIFTZERO_GROQ_TIMEOUT_SECONDS=15
```

For Docker Compose, put these values in the repository `.env` file. Never put
the key in frontend source, commit it to Git, or send it in model-registration
JSON. The dashboard calls DriftZero; only DriftZero calls Groq.

## API flow

Discover models available to the configured account:

```http
GET /api/v1/integrations/groq/models
```

Import one model into the registry:

```http
POST /api/v1/integrations/groq/models
Content-Type: application/json

{
  "name": "Groq Shop Assistant",
  "model_identifier": "MODEL_ID_FROM_DISCOVERY",
  "environment": "development",
  "prompt_version": "prompt-v1",
  "actor": "operator@example.com"
}
```

Run the imported model and evaluate its responses locally:

```http
POST /api/v1/models/MODEL_ID/evaluations/groq
Content-Type: application/json

{
  "prompt": "What storage does the Premium plan include?",
  "repeat": 3,
  "temperature": 0,
  "profile": {
    "expected_terms": ["500 GB"],
    "trusted_facts": ["Premium plan includes 500 GB"],
    "forbidden_terms": ["unlimited storage"],
    "expected_json": false,
    "latency_target_ms": 2000,
    "input_cost_per_million": 0,
    "output_cost_per_million": 0
  },
  "actor": "operator@example.com"
}
```

`repeat` controls how many real provider responses are compared and is capped
at 20. Each provider call consumes Groq quota. Local calculation consumes no
additional provider tokens.

## Interpretation limits

Exact term and trusted-fact matching is intentionally deterministic and
auditable, but it is not a universal proof that an answer is factually correct.
If no trusted facts are declared, groundedness is returned as missing rather
than inventing a score. Semantic stability uses pairwise normalized-token
overlap; it measures response consistency, not factual correctness.

The endpoint returns an immediate local health result for the run. Persisted
fleet health still applies DriftZero's sample-size gate—20 interactions by
default—so small runs remain `insufficient_data` in the main health timeline.
This keeps a one-response experiment from being presented as production health.

The audit trail records the formula, dimensions, declared evidence results,
attempt count, and success count. Stored traces pass through DriftZero's
redaction layer; the live response is returned to the authenticated caller but
is never written to operational logs.
