# Website evidence refresh

DriftZero can monitor a public website as a changing reference-data source. A website
connection records the URL, refresh interval, extraction mode, and approval policy. The website
worker checks due connections without blocking API requests.

## Safety and trust boundary

The fetcher accepts bounded HTTP(S) text/HTML responses and applies the same target URL policy
as other DriftZero connections. Script, style, SVG, template, and `noscript` content is removed.
The response size, fetch timeout, and LLM input length are bounded.

Groq structures readable text with strict JSON Schema output. DriftZero then independently
rejects every fact whose `evidence_quote` is not an exact substring of its fetched source segment,
and rejects facts containing numbers absent from that quote. The original deterministic passages
are retained alongside the extracted facts, so Groq is a convenience extraction layer rather than
an unverified source of truth. Existing connections may still select the optional xAI path.

New content creates a versioned evidence source. By default it waits for human approval. An operator
may explicitly enable automatic approval for a trusted source. Unchanged content creates no
duplicate evidence version.

## Configuration

Set server-side values only; never use a `VITE_` variable for a provider key.

```env
DRIFTZERO_GROQ_API_KEY=replace-at-runtime
DRIFTZERO_EVIDENCE_LLM_MODEL=openai/gpt-oss-20b
DRIFTZERO_WEBSITE_REFRESH_INTERVAL_SECONDS=30
DRIFTZERO_WEBSITE_FETCH_TIMEOUT_SECONDS=15
DRIFTZERO_WEBSITE_LLM_TIMEOUT_SECONDS=45
DRIFTZERO_WEBSITE_MAX_RESPONSE_BYTES=1048576
DRIFTZERO_WEBSITE_LLM_TEXT_CHARS=40000
```

`DRIFTZERO_WEBSITE_REFRESH_INTERVAL_SECONDS` controls how often the worker looks for due
connections. Each connection separately controls its website refresh interval, with 10 minutes
as the UI default.

Run one scheduling pass manually:

```powershell
cd backend
.\.venv\Scripts\python.exe -m app.website_worker --once
```

The full local runner and Docker Compose start the website worker automatically.
The Render hackathon deployment runs it in the same supervised web container as
the API because every process must share the same database. `deploy/start.py`
must include `python -m app.website_worker`; `app.evidence_sync_worker` handles
owner-provided JSON URLs and does not process `website` model connections.

For the Render service, configure these values:

```env
DRIFTZERO_GROQ_API_KEY=replace-at-runtime
DRIFTZERO_EVIDENCE_LLM_MODEL=openai/gpt-oss-20b
DRIFTZERO_WEBSITE_REFRESH_INTERVAL_SECONDS=30
DRIFTZERO_WEBSITE_FETCH_TIMEOUT_SECONDS=15
DRIFTZERO_WEBSITE_LLM_TIMEOUT_SECONDS=45
DRIFTZERO_WEBSITE_MAX_RESPONSE_BYTES=1048576
DRIFTZERO_WEBSITE_LLM_TEXT_CHARS=40000
```

`DRIFTZERO_GROQ_API_KEY` is a secret entered in the Render dashboard. Do not put its value
in `render.yaml`. A connection's own `refresh_interval_minutes` remains the
source-specific schedule; the worker interval only determines how soon a due
connection is noticed.

## API

- Create a normal `website` model connection at
  `POST /api/v1/models/{model_id}/connections` with configuration fields
  `refresh_interval_minutes`, `use_groq`, and `auto_approve`. Legacy connections may continue
  to use `use_xai` with the existing xAI settings.
- Trigger an immediate refresh at
  `POST /api/v1/connections/{connection_id}/website-refresh`.
- Review a generated source through the existing evidence review endpoint when auto-approval is
  disabled.

Every successful fetch and import updates connection status, latency, content hash, last-check
time, and the most recent source ID. A failed post-fetch extraction stores a separate attempted
hash for diagnostics but does not replace the last successful hash, so the same content can be
retried. Import and review actions also appear in DriftZero's audit history.
