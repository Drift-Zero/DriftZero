# Website-to-JSON evidence refresh

DriftZero can monitor a public website as a changing reference-data source. A website
connection records the URL, refresh interval, xAI usage, and approval policy. The website
worker checks due connections without blocking API requests.

## Safety and trust boundary

The fetcher accepts bounded HTTP(S) text/HTML responses and applies the same target URL policy
as other DriftZero connections. Script, style, SVG, template, and `noscript` content is removed.
The response size, fetch timeout, and LLM input length are bounded.

Grok structures readable text with xAI strict JSON Schema output. DriftZero then independently
rejects every fact whose `evidence_quote` is not an exact substring of the fetched page or whose
`value` is not present in that quote. Grok output is therefore a convenience extraction layer,
not an unverified source of truth.

New content creates a JSON evidence source. By default it waits for human approval. An operator
may explicitly enable automatic approval for a trusted source. Unchanged content creates no
duplicate evidence version.

## Configuration

Set server-side values only; never use a `VITE_` variable for the xAI key.

```env
XAI_API_KEY=replace-at-runtime
DRIFTZERO_XAI_MODEL=grok-4.6
DRIFTZERO_XAI_BASE_URL=https://api.x.ai/v1
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

## API

- Create a normal `website` model connection at
  `POST /api/v1/models/{model_id}/connections` with configuration fields
  `refresh_interval_minutes`, `use_xai`, and `auto_approve`.
- Trigger an immediate refresh at
  `POST /api/v1/connections/{connection_id}/website-refresh`.
- Review a generated source through the existing evidence review endpoint when auto-approval is
  disabled.

Every fetch updates connection status, latency, content hash, last-check time, and the most
recent source ID. Import and review actions also appear in DriftZero's audit history.
