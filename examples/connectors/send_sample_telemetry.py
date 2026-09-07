#!/usr/bin/env python3
"""Minimal provider-agnostic connector for sending health telemetry."""

from __future__ import annotations

import argparse
import json
import urllib.request
from datetime import UTC, datetime


def post(base_url: str, path: str, body: dict):
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.load(response)


def main(base_url: str) -> None:
    model = post(
        base_url,
        "/api/v1/models",
        {
            "name": "ConnectorDemo",
            "provider": "openai-compatible",
            "environment": "simulation",
            "description": "Sample connector using normalized, synthetic health signals.",
            "initial_version": {
                "label": "demo-v1",
                "model_identifier": "sample-model",
                "prompt_version": "prompt-v1",
                "configuration": {"temperature": 0},
                "tools": [],
                "corpus_version": "corpus-v1",
                "evaluation_policy_version": "health-v1",
                "actor": "sample-connector",
            },
            "actor": "sample-connector",
        },
    )
    snapshot = post(
        base_url,
        f"/api/v1/models/{model['id']}/telemetry",
        {
            "observed_at": datetime.now(UTC).isoformat(),
            "dimensions": {
                "quality": 88,
                "groundedness": 91,
                "semantic_stability": 86,
                "temporal_stability": 89,
                "safety": 96,
                "drift": 90,
                "reliability": 93,
                "latency": 85,
                "cost": 82,
            },
            "sample_size": 100,
            "coverage": 0.95,
            "source": "simulated",
            "traces": [],
        },
    )
    print(f"Created {model['name']} ({model['id']}); health={snapshot['score']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    args = parser.parse_args()
    main(args.base_url)
