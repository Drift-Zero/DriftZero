FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DRIFTZERO_DATABASE_URL=sqlite:////data/driftzero.db

WORKDIR /app

COPY pyproject.toml README.md ./
COPY app ./app
COPY entrypoint.sh /usr/local/bin/driftzero-entrypoint

RUN python -m pip install --no-cache-dir .

RUN useradd --create-home driftzero \
    && mkdir /data \
    && chown driftzero:driftzero /data \
    && chmod 755 /usr/local/bin/driftzero-entrypoint

USER driftzero

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f\"http://127.0.0.1:{os.getenv('PORT', '8000')}/healthz\", timeout=2)"

ENTRYPOINT ["driftzero-entrypoint"]
