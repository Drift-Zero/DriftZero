# DriftZero frontend

React, Vite, and TypeScript dashboard for DriftZero's model reliability lifecycle.

## Start locally

```bash
npm install
npm run dev
```

Copy `.env.example` to `.env.local` when you want to change the defaults.

## Modes

- Demo mode: `VITE_DEMO_MODE=true`
- Live API mode: `VITE_DEMO_MODE=false`
- Backend origin: `VITE_API_BASE_URL=http://127.0.0.1:8000`

Environment values are read when Vite starts, and act as the defaults a fresh browser begins
with. Restart the development server after changing them.

## Settings

The Settings screen (`/settings`) overrides those defaults at runtime and stores the result in
the browser, so a built dashboard can be repointed without a rebuild:

- **Workspace** — dashboard name, environment label, and the actor and role recorded in the
  audit trail for recovery approvals, alert-rule edits, and model changes.
- **Appearance** — density, reduced motion, demo-control visibility, relative or absolute
  timestamps, local or UTC times, and health-score precision.
- **Alerts** — desktop notification preferences, and full create, edit, enable, and delete for
  the API's alert rules.
- **Models** — lifecycle state and trace retention for each registered model.
- **Connection** — demo or live data, API base URL with a connection test, background refresh
  interval, and a recovery API key held in session storage only.
- **Advanced** — export, import, and reset the configuration, plus build diagnostics.

Alert rules and model changes are written to the API and need it reachable; everything else is
local to the browser. `Restore defaults` returns every setting to the compiled-in values.
