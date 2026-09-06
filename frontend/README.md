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

Environment values are read when Vite starts. Restart the development server after changing them.
