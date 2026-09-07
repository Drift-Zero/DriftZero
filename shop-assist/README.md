# ShopAssist

ShopAssist is the deterministic e-commerce support assistant used to demonstrate
DriftZero's reliability monitoring. The customer experience supports product discovery,
stock checks, demo-order tracking, shipping, returns, refunds, warranties, and promotions.

The presenter console at `/demo` supports these controlled scenarios:

- stale returns policy;
- inventory mismatch;
- expired promotion;
- outdated warranty;
- conflicting shipping guides;
- recovered and healthy baseline states.

## Run locally

```powershell
npm install
npm run dev
```

Open `http://localhost:3000` for the customer experience or
`http://localhost:3000/demo` for presenter controls. Demo orders are `DZ-1042`,
`DZ-2088`, and `DZ-3190`.

## DriftZero telemetry

ShopAssist evaluates each observed answer against the current catalog and policy
facts, buffers 20 real interactions, and then sends one evaluation window with
20 request-level traces to `POST /api/v1/shopassist/telemetry`. Copy
`.env.example` to `.env.local` and set `DRIFTZERO_API_URL` to point at the
DriftZero API. If delivery is unavailable, the current batch stays buffered in
the server process and is retried when the next interaction completes the window.

The demo is explicitly simulated. It does not call a production model or modify
an external commerce system.

For the complete local stack, run Docker Compose from the repository root. The
container receives `DRIFTZERO_API_URL`, `GROQ_API_KEY`, and the reserved
`GEMINI_API_KEY` only at runtime; none is copied into browser variables. Set
`SHOPASSIST_PUBLIC_URL` to the deployed origin so social preview links are valid.

## AI providers

ShopAssist uses Groq's `openai/gpt-oss-120b` as its primary conversational model.
Set `GROQ_API_KEY` in `.env.local`; never expose it with a `NEXT_PUBLIC_` prefix.
The Gemini adapter remains available for a later automatic-failover phase.
