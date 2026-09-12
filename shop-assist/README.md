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

ShopAssist buffers 20 raw interactions and sends them to
`POST /api/v1/models/{model_id}/interactions/evaluate`. DriftZero—not
ShopAssist—searches approved evidence, verifies claims, derives metrics, stores
traces, and calculates Health-v2. Copy `.env.example` to `.env.local` and set
`DRIFTZERO_API_URL`. `DRIFTZERO_MODEL_ID` is optional; without it the server
resolves the unique model named `ShopAssist`. If delivery is unavailable, the
batch remains buffered and the customer still receives the provider answer.

Healthy Groq requests are recorded as observed traffic. Controlled failure
scenarios and the local fallback are explicitly marked as simulated; neither
modifies an external commerce system.

For the complete local stack, run Docker Compose from the repository root. The
container receives `DRIFTZERO_API_URL`, optional `DRIFTZERO_MODEL_ID`,
`GROQ_API_KEY`, and the reserved `GEMINI_API_KEY` only at runtime; none is copied
into browser variables. Set
`SHOPASSIST_PUBLIC_URL` to the deployed origin so social preview links are valid.

## AI providers

ShopAssist uses Groq's `openai/gpt-oss-120b` as its primary conversational model.
Set `GROQ_API_KEY` in `.env.local`; never expose it with a `NEXT_PUBLIC_` prefix.
The Gemini adapter remains available for a later automatic-failover phase.
