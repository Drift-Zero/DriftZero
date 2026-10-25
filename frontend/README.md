# DriftZero frontend

React, Vite, and TypeScript dashboard for DriftZero's model reliability lifecycle.

## Start locally

From the repository root, enter the dashboard directory:

```bash
cd frontend
npm install
npm run dev
```

Vite is configured to start on port `5173`; open the local URL printed in
the terminal, normally <http://localhost:5173>. This starts the dashboard
development server. Live API mode also requires the
[backend](../backend/README.md#run-locally) to be running.

While in `frontend/`, copy `.env.example` to `.env.local` when you want to change
the defaults. The [root quick start](../README.md#quick-start) runs the complete
system with Docker Compose instead.

## Check and preview a build

Run these checks from `frontend/`:

```bash
npm run lint
npm run build
```

`lint` runs ESLint. `build` runs the TypeScript project build before
creating the Vite production bundle. After a successful build, inspect it
locally with:

```bash
npm run preview
```

Open the preview URL printed by Vite. Preview serves the built dashboard;
it does not start the backend or the background workers.

## Modes

- Demo mode: `VITE_DEMO_MODE=true`
- Live API mode: `VITE_DEMO_MODE=false`
- Backend origin: `VITE_API_BASE_URL=http://127.0.0.1:8000`

Environment values are read when Vite starts, and act as the defaults a fresh browser begins
with. Restart the development server after changing them.

### When an environment change seems ignored

Saved browser settings take precedence over the environment defaults.
If a restarted build still uses an old API URL or Demo mode, open
**Settings → Connection** and inspect the active mode and base URL.
**Settings → Advanced → Diagnostics** shows both the active API base URL
and the build-time API base for comparison.

Update only the connection fields when that is all you need to change.
**Restore defaults** also resets workspace, appearance, and notification
preferences to this build's defaults; it does not delete API models or
alert rules. Export your settings first if you want to keep those choices.

## Move settings between browsers

Open **Settings → Advanced → Export and import** and choose **Download JSON**
or **Copy to clipboard**. The downloaded file is `driftzero-settings.json`.
In the destination browser, paste the JSON into the import field and choose
**Import settings**.

Import replaces the settings object; it does not merge selected fields.
Missing or unsupported values return to this build's defaults, and malformed
JSON is rejected. Export the destination settings first if you need to keep
them. The file contains dashboard preferences, not backend models, alert
rules, evidence, telemetry, or the session-held recovery API key.

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
