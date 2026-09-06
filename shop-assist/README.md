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

Every answered question produces a payload compatible with
`POST /api/v1/models/{model_id}/telemetry`. Copy `.env.example` to `.env.local`
and set the API URL and registered DriftZero model ID to deliver traces directly.
If either value is absent, the latest 100 payloads are buffered in browser
`sessionStorage` under `shopassist.telemetry.v1`.

The demo is explicitly simulated. It does not call a production model or modify
an external commerce system.
