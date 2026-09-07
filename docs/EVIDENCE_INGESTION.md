# Trusted evidence ingestion

DriftZero converts application-owner files into a reviewable verification
corpus. The pipeline does not treat an LLM as a source of truth.

## Supported inputs

The hackathon MVP accepts text-based PDF, JSON, CSV, TXT, and Markdown files up
to 5 MiB. Scanned PDFs need OCR before upload. JSON and CSV are always parsed by
deterministic code so prices, dates, identifiers, and other exact values cannot
be silently rewritten by a model.

## Trust boundary

1. A deterministic parser extracts source segments and records their PDF page,
   CSV row, JSON path, or text paragraph.
2. For PDF, TXT, and Markdown, the uploader may ask Gemini or Groq to rewrite a
   segment as atomic facts.
3. Every AI-generated fact must contain an exact quote found in the parser
   output. Every number in the fact must also occur in the quote. Invalid facts
   are discarded, and every deterministic source passage is retained alongside
   any AI-structured facts.
4. A new source starts as `awaiting_review` and cannot be retrieved by an
   evaluator until a human approves it.
5. The source SHA-256 hash and immutable `evidence-<hash>` corpus version make
   results reproducible. Original files and API keys are not stored.

## Local setup

The default is deterministic extraction and requires no model key:

```bash
DRIFTZERO_EVIDENCE_LLM_PROVIDER=disabled
```

To enable optional Gemini structuring on the API server:

```bash
DRIFTZERO_EVIDENCE_LLM_PROVIDER=gemini
DRIFTZERO_EVIDENCE_LLM_MODEL=gemini-3.8-flash
GEMINI_API_KEY=replace-me
```

For Groq:

```bash
DRIFTZERO_EVIDENCE_LLM_PROVIDER=groq
DRIFTZERO_EVIDENCE_LLM_MODEL=openai/gpt-oss-20b
DRIFTZERO_GROQ_API_KEY=replace-me
```

Never use `VITE_` or `NEXT_PUBLIC_` for these keys. Those prefixes expose values
to browsers.

## API integration

The dashboard's **Evidence** page calls these endpoints:

- `POST /api/v1/models/{model_id}/evidence-sources/import`
- `GET /api/v1/models/{model_id}/evidence-sources`
- `GET /api/v1/evidence-sources/{source_id}`
- `POST /api/v1/evidence-sources/{source_id}/review`
- `POST /api/v1/models/{model_id}/evidence/search`

Uploads use base64 JSON so the integration does not depend on multipart form
handling. Search returns only approved sources and includes the exact evidence
quote, source filename, corpus version, relevance, and location. A later claim
verifier can call the search endpoint directly without knowing how each file
format was parsed.

## Demo path

1. Register or seed ShopAssist.
2. Open **Evidence**, select ShopAssist, and upload
   `examples/evidence/shopassist-catalog.json` or
   `examples/evidence/shopassist-policies.md`.
3. Inspect the extracted JSON paths, then approve the source.
4. Search for `AeroFit price`; the result shows the exact catalogue record and
   corpus version.
5. Feed those hits to the claim-verification stage. Do not calculate a
   groundedness score when no approved evidence is returned.
