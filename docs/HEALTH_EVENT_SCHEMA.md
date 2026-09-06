# Health event schema

Connectors normalize provider-specific observations into one health event and send it to `POST /api/v1/models/{model_id}/telemetry`.

```json
{
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
| `observed_at` | ISO-8601 timestamp | UTC is recommended; defaults to ingestion time |
| `dimensions` | object | Each supplied score is from 0–100, where higher is healthier |
| `sample_size` | integer | At least 1; number of requests represented by this window |
| `coverage` | number | 0–1; fraction of eligible traffic evaluated |
| `source` | enum | `observed`, `evaluated`, or `simulated` |
| `traces` | array | Optional request-level evidence; raw text is redacted before storage |

Missing dimensions are allowed, but they reduce confidence. The default MVP requires at least 20 samples and 30% coverage for a fully usable score. A connector must calculate or obtain normalized dimension scores; the API does not pretend raw latency or token counts are already health scores.

## Connector flow

1. Register the monitored model with `POST /api/v1/models`, including an initial version.
2. Aggregate a short observation window in the model-serving application.
3. Redact sensitive content before transmission. Server-side redaction is a second safety layer, not permission to transmit secrets.
4. Convert the window into normalized 0–100 dimension scores.
5. Send the event and retain the returned health snapshot ID for correlation.
6. Retry transient network failures with exponential backoff; do not retry validation errors blindly.

Run the dependency-free example after the local stack starts:

```bash
python3 examples/connectors/send_sample_telemetry.py
```

This example sends synthetic data. It does not call OpenAI or another provider, so it requires no API key.
