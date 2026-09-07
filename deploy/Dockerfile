FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DRIFTZERO_DATABASE_URL=sqlite:////data/driftzero.db

WORKDIR /app

COPY backend/pyproject.toml backend/README.md ./
COPY backend/app ./app
RUN python -m pip install --no-cache-dir ".[postgres]"

COPY deploy/start.py ./deploy/start.py

RUN useradd --create-home driftzero \
    && mkdir /data \
    && chown driftzero:driftzero /data

USER driftzero
EXPOSE 10000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import os, urllib.request; urllib.request.urlopen(f\"http://127.0.0.1:{os.getenv('PORT', '10000')}/healthz\", timeout=2)"

ENTRYPOINT ["python", "/app/deploy/start.py"]
