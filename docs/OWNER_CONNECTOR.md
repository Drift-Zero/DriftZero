# Monitor any owner-controlled LLM application

The connector boundary is the only reliable provider-independent integration. A public website URL
does not expose its private prompts, responses, latency, retrieval context, or errors. Put the connector
in the server route that already calls the hosted or local model.

## End-to-end setup

1. Register the application as a model in DriftZero.
2. Add a telemetry connection from the model's Connections screen and copy its one-time ingestion key.
3. In **Trusted Evidence**, select **Live URL**, paste a direct public JSON, CSV, PDF, TXT, or Markdown
   URL, and fetch it. Normal HTML pages are deliberately rejected.
4. Inspect the extracted rows, paths, or pages and approve the source. Unapproved evidence never enters
   verification.
5. Copy either `examples/connectors/driftzero_connector.py` or
   `examples/connectors/driftzero-connector.mjs` into the owner's backend.
6. Configure the connector from server-only environment variables and call `observe` immediately after
   the model returns.
7. After 20 interactions, the connector sends a window to
   `POST /api/v1/models/{model_id}/interactions/evaluate`. DriftZero stores redacted traces and a health
   snapshot. The existing model detail page displays it in the health graph.

## Server-only variables

```dotenv
DRIFTZERO_API_URL=http://127.0.0.1:8000
DRIFTZERO_MODEL_ID=replace-with-model-id
DRIFTZERO_INGEST_KEY=dz_ing_replace-with-one-time-key
```

Never prefix the ingestion key with `VITE_` or `NEXT_PUBLIC_`; either prefix would expose it to browser
JavaScript. Model-provider keys also remain in the owner's backend and are not sent to DriftZero.

## Python example

```python
import os
import time

from driftzero_connector import DriftZeroConnector

connector = DriftZeroConnector(
    api_url=os.environ["DRIFTZERO_API_URL"],
    model_id=os.environ["DRIFTZERO_MODEL_ID"],
    ingestion_key=os.environ.get("DRIFTZERO_INGEST_KEY"),
)

started = time.perf_counter()
answer = call_your_model(question)  # Gemini, Groq, OpenAI, Ollama, vLLM, or custom
connector.observe(
    question=question,
    answer=answer,
    provider="ollama",
    latency_ms=round((time.perf_counter() - started) * 1000),
)
```

## Node.js example

```js
import { DriftZeroConnector } from './driftzero-connector.mjs'

const connector = new DriftZeroConnector({
  apiUrl: process.env.DRIFTZERO_API_URL,
  modelId: process.env.DRIFTZERO_MODEL_ID,
  ingestionKey: process.env.DRIFTZERO_INGEST_KEY,
})

const started = performance.now()
const answer = await callYourModel(question)
await connector.observe({
  question,
  answer,
  provider: 'local-llama',
  latency_ms: Math.round(performance.now() - started),
})
```

## What the scores mean

The evaluator uses no judge model and does not manufacture an answer when evidence is missing.

- `supported`: material claim terms and values occur in approved evidence.
- `contradicted`: relevant evidence was found, but a numeric value or negation conflicts.
- `unverified`: deterministic rules cannot prove either support or contradiction.
- Evidence coverage = `(supported + contradicted) / all claims`.
- Groundedness = `supported / (supported + contradicted) × 100`.
- Quality = `supported / all claims × 100`.
- Reliability = successful interactions / all interactions × 100.
- Latency health = `min(100, latency target / average latency × 100)`.
- Cost health is optional and uses `min(100, cost target / average cost × 100)` when the owner
  supplies both per-interaction costs and a target.
- Safety = interactions without owner-supplied safety flags / all interactions × 100.

The normal `health-v1` weighted policy combines available dimensions. Fewer than 20 interactions,
under 30% evidence coverage, or too few dimensions produces `insufficient_data` instead of a score.

## URL synchronization and trust

The evidence sync worker uses ETag and Last-Modified when the source supports them. A changed document
becomes a new `awaiting_review` version. The old approved version stays active until a human approves
the replacement, after which the old version is retired. URLs are restricted to public HTTP(S)
destinations to prevent access to loopback, private network, cloud metadata, and other internal targets.

This MVP accepts public direct URLs only. Authenticated evidence APIs, webhooks, semantic/NLI models,
and domain-specific graders require separate policies and are not implied by this connector.
