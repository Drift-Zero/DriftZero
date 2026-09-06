# Backend requirements for the DriftZero dashboard

The frontend is based on the FastAPI contracts currently exposed under `/api/v1` and does not invent live API data. The existing model, health, incident, diagnosis, recovery, verification, alert, forecast, and model audit APIs cover the core lifecycle.

## BACKEND CHANGE REQUIRED — CORS

The backend does not currently install or configure FastAPI `CORSMiddleware`. A browser served from Vite (for example, `http://127.0.0.1:5173`) cannot call `http://127.0.0.1:8000` unless the backend explicitly permits the frontend origin.

Suggested configuration:

- Allow the exact deployed frontend origin(s).
- For local development, allow `http://127.0.0.1:5173` and/or `http://localhost:5173`.
- Allow `GET`, `POST`, `PATCH`, and `DELETE` methods used by the existing API.
- Do not use a wildcard production origin when credentials are enabled.

## Missing cross-model incident feed

**Suggested endpoint:** `GET /api/v1/incidents?state=open&limit=100`

**Purpose:** Return a tenant-wide incident feed without requiring the frontend to request incidents separately for every model.

**Suggested request:** Query parameters `state` (optional), `severity` (optional), `model_id` (optional), and `limit`.

**Suggested response:**

```json
{
  "items": [
    {
      "id": "incident-id",
      "model_id": "model-id",
      "title": "Knowledge grounding collapse",
      "state": "open",
      "severity": "critical",
      "opened_at": "2026-09-06T12:00:00Z",
      "closed_at": null,
      "baseline_score": 95,
      "trough_score": 58,
      "summary": "Evidence-backed safe summary"
    }
  ],
  "total": 1
}
```

The current frontend safely falls back to `GET /api/v1/models` followed by `GET /api/v1/models/{id}/incidents` for each model.

## Missing cross-model event feed

**Suggested endpoint:** `GET /api/v1/events?limit=100`

**Purpose:** Provide a chronological, tenant-wide event timeline with server-side filtering and pagination.

**Suggested request:** Query parameters `model_id`, `event_type`, `status`, `before`, and `limit` (all optional).

**Suggested response:**

```json
{
  "items": [
    {
      "id": "event-id",
      "model_id": "model-id",
      "event_type": "recovery.verified",
      "actor": "system",
      "reason": null,
      "details": {},
      "created_at": "2026-09-06T12:00:00Z"
    }
  ],
  "next_cursor": null
}
```

The current frontend combines the existing per-model `GET /api/v1/models/{id}/audit` responses.

## Missing evaluation result feed

**Suggested endpoint:** `GET /api/v1/models/{model_id}/evaluations?limit=50`

**Purpose:** Supply the latest evaluator results directly, including a safe request identifier, result, latency, and supported metric values. Health snapshots expose normalized dimensions and sample counts but not a browsable evaluation-result record.

**Suggested request:** Query parameters `status`, `before`, and `limit` (optional).

**Suggested response:**

```json
{
  "items": [
    {
      "id": "evaluation-id",
      "model_id": "model-id",
      "request_id": "safe-request-id",
      "evaluated_at": "2026-09-06T12:00:00Z",
      "result": "passed",
      "latency_ms": 428,
      "dimensions": {
        "quality": 93,
        "groundedness": 94,
        "safety": 99
      }
    }
  ],
  "next_cursor": null
}
```

Raw prompts and responses should not be included. The current frontend shows health snapshot metadata in live mode and only displays a request identifier when the data source intentionally provides one.

## Optional aggregate overview

**Suggested endpoint:** `GET /api/v1/overview`

**Purpose:** Efficiently populate overall health, active models, active incidents, and evaluations-today at larger model counts.

**Suggested response:**

```json
{
  "overall_health": 94.2,
  "active_models": 2,
  "active_incidents": 0,
  "evaluations_today": 1284,
  "calculated_at": "2026-09-06T12:00:00Z"
}
```

The current frontend derives available summary values from existing model health and incident responses.
