#!/bin/sh
set -eu

python -m app.migrations

exec uvicorn app.main:app \
  --host 0.0.0.0 \
  --port "${PORT:-8000}" \
  --no-access-log
