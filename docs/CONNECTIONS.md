# Model connections

DriftZero attaches multiple evidence sources to one monitored AI system. A source may be a
GitHub repository, authenticated telemetry stream, website, or inference API.

## Security boundary

- Provider credentials are encrypted with `DRIFTZERO_CONNECTION_SECRET_KEY` and are never
  returned by read APIs or written to audit details.
- Telemetry connections issue a `dz_ing_...` key once. DriftZero stores only its SHA-256 hash.
- Production website and API checks require HTTPS and reject private, loopback, link-local,
  multicast, reserved, and unspecified network targets.
- GitHub checks use read-only REST requests. They fingerprint the complete repository tree but
  do not execute or persist repository source code.
- HTTP checks store status, latency, content type, size, and a response hash—not response bodies.

Generate the encryption key before accepting API or private-GitHub credentials:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Store the resulting value as the `DRIFTZERO_CONNECTION_SECRET_KEY` server secret.

## Connection lifecycle

1. Register a model with `POST /api/v1/models`.
2. Add one or more sources with `POST /api/v1/models/{model_id}/connections`.
3. Save a returned telemetry ingestion key immediately; it is shown only once.
4. Test GitHub, website, or API connectivity with
   `POST /api/v1/connections/{connection_id}/check`.
5. Inspect current status with `GET /api/v1/models/{model_id}/connections`.
6. Rotate an API credential or pause a connection with `PATCH /api/v1/connections/{id}`.

Telemetry clients authenticate using:

```http
X-DriftZero-Ingest-Key: dz_ing_REDACTED
```

GitHub discovery records the branch commit, tree SHA, complete tree-manifest hash, entry count,
and likely AI configuration files. This evidence can be compared across checks to distinguish a
code or prompt change from unexplained behavioral drift.
