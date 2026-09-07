# Health event schema

Connectors normalize provider-specific observations into one health event and send it to `POST /api/v1/models/{model_id}/telemetry`.

```json
{
  "event_id": "window-prod-20260906T120000Z",
  "schema_version": "1.0",
  "observed_at": "2026-09-06T12:00:00Z",
  "dimensions": {
    "quality": 88,
    "groundedness": 91,
    "semantic_stability": 86,
    "temporal_stability": 89,
    "safety": 96,
    "drift": 90,
    "reliability": 93,
    "latency": 85,
    "cost": 82
  },
  "sample_size": 100,
  "coverage": 0.95,
  "source": "observed",
  "traces": []
}
```

## Contract

| Field | Type | Rule |
|---|---|---|
| `event_id` | string | Recommended stable producer ID, 8–128 safe characters; unique per model and idempotent on retry |
| `schema_version` | string | Currently `1.0`; unsupported versions are rejected |
| `observed_at` | ISO-8601 timestamp | UTC is recommended; defaults to ingestion time |
| `dimensions` | object | Each supplied score is from 0–100, where higher is healthier |
| `sample_size` | integer | At least 1; number of requests represented by this window |
| `coverage` | number | 0–1; fraction of eligible traffic evaluated |
| `source` | enum | `observed`, `inferred`, or `simulated` |
| `traces` | array | Optional request-level evidence; raw text is redacted before storage |

Missing dimensions are allowed, but they reduce confidence. The default MVP requires at least 20 samples and 30% coverage for a fully usable score. A connector must calculate or obtain normalized dimension scores; the API does not pretend raw latency or token counts are already health scores.

## Connector flow

1. Register the monitored model with `POST /api/v1/models`, including an initial version.
2. Aggregate a short observation window in the model-serving application.
3. Redact sensitive content before transmission. Server-side redaction is a second safety layer, not permission to transmit secrets.
4. Convert the window into normalized 0–100 dimension scores.
5. Create a telemetry model connection once and retain its one-time ingestion key securely.
6. Send the key as `X-DriftZero-Ingest-Key`, then retain the returned health snapshot ID.
7. Retry transient failures with the same `event_id`; DriftZero returns the original snapshot
   instead of recording a duplicate. Do not retry validation errors blindly.

In `production`, ingestion is denied until a telemetry connection exists. Observed timestamps
more than `DRIFTZERO_TELEMETRY_MAX_FUTURE_SKEW_SECONDS` ahead of the server clock are rejected.

Run the dependency-free example after the local stack starts:

```bash
python3 examples/connectors/send_sample_telemetry.py
```

This example sends synthetic data. It does not call OpenAI or another provider, so it requires no API key.

## ShopAssist adapter

ShopAssist evaluates answers inside its `/api/chat` server route and keeps a
server-side buffer. Every complete 20-interaction batch is normalized into this
contract and sent to `POST /api/v1/shopassist/telemetry` using the server-only
`DRIFTZERO_API_URL`. Browser JavaScript never reads provider keys or the API URL.

The window uses `source: "observed"` because its scores are derived from the 20
actual ShopAssist responses. Individual traces retain `is_simulated: true` for
controlled failure scenarios and `false` for healthy or recovered scenarios.
