"""Dependency-free connector for any hosted or local model backend.

Keep this module beside the server code that already receives model responses.
It buffers observations and sends one evidence-evaluated window to DriftZero.
"""

from __future__ import annotations

import json
import threading
import urllib.request
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4


class DriftZeroConnector:
    def __init__(
        self,
        *,
        api_url: str,
        model_id: str,
        ingestion_key: str | None = None,
        batch_size: int = 20,
        latency_target_ms: int = 2000,
        cost_target_usd_per_interaction: float | None = None,
        timeout_seconds: float = 10,
    ) -> None:
        if batch_size < 1 or batch_size > 100:
            raise ValueError("batch_size must be between 1 and 100")
        self.endpoint = (
            f"{api_url.rstrip('/')}/api/v1/models/{model_id}/interactions/evaluate"
        )
        self.ingestion_key = ingestion_key
        self.batch_size = batch_size
        self.latency_target_ms = latency_target_ms
        self.cost_target_usd_per_interaction = cost_target_usd_per_interaction
        self.timeout_seconds = timeout_seconds
        self._buffer: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def observe(
        self,
        *,
        question: str,
        answer: str,
        request_id: str | None = None,
        provider: str | None = None,
        latency_ms: int | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        cost_usd: float | None = None,
        status: str = "ok",
        error_code: str | None = None,
        safety_flags: list[str] | None = None,
    ) -> dict[str, Any] | None:
        """Record one completed interaction and flush when the window is full."""

        interaction = {
            "request_id": request_id,
            "occurred_at": datetime.now(UTC).isoformat(),
            "question": question,
            "answer": answer,
            "provider": provider,
            "status": status,
            "error_code": error_code,
            "latency_ms": latency_ms,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": cost_usd,
            "safety_flags": safety_flags or [],
        }
        with self._lock:
            self._buffer.append(interaction)
            ready = len(self._buffer) >= self.batch_size
        return self.flush() if ready else None

    def flush(self) -> dict[str, Any] | None:
        """Send the current window; retain it when delivery fails so it can be retried."""

        with self._lock:
            if not self._buffer:
                return None
            interactions = self._buffer[: self.batch_size]
        payload = json.dumps(
            {
                "event_id": f"connector:{uuid4()}",
                "interactions": interactions,
                "latency_target_ms": self.latency_target_ms,
                "cost_target_usd_per_interaction": self.cost_target_usd_per_interaction,
                "source": "observed",
                "actor": "owner-connector",
            }
        ).encode()
        headers = {"Content-Type": "application/json"}
        if self.ingestion_key:
            headers["X-DriftZero-Ingest-Key"] = self.ingestion_key
        request = urllib.request.Request(
            self.endpoint,
            data=payload,
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            result = json.loads(response.read())
        with self._lock:
            del self._buffer[: len(interactions)]
        return result


if __name__ == "__main__":
    # Replace these values, then call observe immediately after your own model returns.
    connector = DriftZeroConnector(
        api_url="http://127.0.0.1:8000",
        model_id="replace-with-model-id",
        ingestion_key=None,
    )
    print(
        connector.observe(
            question="What is the electronics return window?",
            answer="Electronics can be returned within 14 days.",
            provider="local-model",
            latency_ms=420,
        )
        or "Buffered. A health window is sent after 20 interactions."
    )
