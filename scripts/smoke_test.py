#!/usr/bin/env python3
"""Verify the deployed DriftZero demo through its public HTTP contract."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request


def request(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    body: dict | None = None,
    api_key: str | None = None,
):
    payload = json.dumps(body).encode() if body is not None else None
    headers = (
        {"Authorization": f"Bearer {api_key}"}
        if api_key
        else {
            "X-DriftZero-Actor": "smoke-test",
            "X-DriftZero-Role": "operator",
        }
    )
    if payload:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        data=payload,
        headers=headers,
        method=method,
    )
    with urllib.request.urlopen(req, timeout=10) as response:
        return json.load(response)


def wait_until_ready(base_url: str, timeout: int, api_key: str | None = None) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            health = request(base_url, "/healthz", api_key=api_key)
            if health.get("status") == "ok":
                return
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            last_error = exc
        time.sleep(2)
    raise RuntimeError(f"API did not become ready within {timeout}s: {last_error}")


def run(base_url: str, timeout: int, api_key: str | None = None) -> None:
    wait_until_ready(base_url, timeout, api_key)
    demo = request(base_url, "/api/v1/demo/reset", method="POST", api_key=api_key)
    model_id = demo["model"]["id"]
    plan_id = demo["recovery"]["id"]
    scores = [item["score"] for item in demo["health"]["snapshots"]]
    assert scores == [91.9, 87.2, 74.8, 62.5], scores
    assert demo["model"]["name"] == "ShopAssist"
    assert demo["diagnosis"]["probable_cause"] == "knowledge_freshness_failure"

    telemetry = request(
        base_url,
        "/api/v1/shopassist/telemetry",
        method="POST",
        body={
            "dimensions": {
                "quality": 61,
                "groundedness": 30,
                "semantic_stability": 35,
                "temporal_stability": 61,
                "safety": 94,
                "drift": 58,
                "reliability": 88,
                "latency": 94,
                "cost": 85,
            },
            "sample_size": 20,
            "coverage": 0.95,
            "source": "observed",
        },
        api_key=api_key,
    )
    assert telemetry["state"] == "critical", telemetry
    assert telemetry["sample_size"] >= 20, telemetry

    approved = request(
        base_url,
        f"/api/v1/recovery/{plan_id}/approve",
        method="POST",
        body={"actor": "smoke-test"},
        api_key=api_key,
    )
    assert approved["state"] == "approved", approved["state"]

    command = request(
        base_url,
        f"/api/v1/recovery/{plan_id}/execute",
        method="POST",
        body={
            "actor": "smoke-test",
            "idempotency_key": f"smoke-{plan_id}",
        },
        api_key=api_key,
    )
    assert command["state"] == "pending", command["state"]
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        command = request(
            base_url,
            f"/api/v1/recovery-commands/{command['id']}",
            api_key=api_key,
        )
        if command["state"] == "succeeded":
            break
        if command["state"] == "failed":
            raise RuntimeError(f"Recovery worker failed: {command.get('error')}")
        time.sleep(0.5)
    else:
        raise RuntimeError(f"Recovery command did not finish within {timeout}s")

    recovered = request(base_url, f"/api/v1/recovery/{plan_id}", api_key=api_key)
    assert recovered["state"] == "recovered", recovered["state"]
    timeline = request(base_url, f"/api/v1/models/{model_id}/health", api_key=api_key)
    final_score = timeline["snapshots"][-1]["score"]
    assert final_score == 84.7, final_score
    print("ShopAssist smoke test passed: 92 → 61 → 84.7, recovery verified.")


if __name__ == "__main__":
    # A Windows console defaults to cp1252, which cannot encode the arrows in the summary.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:3000")
    parser.add_argument("--timeout", type=int, default=90)
    parser.add_argument(
        "--api-key",
        default=os.getenv("DRIFTZERO_RECOVERY_API_KEY"),
        help="API key; prefer the DRIFTZERO_RECOVERY_API_KEY environment variable.",
    )
    args = parser.parse_args()
    run(args.base_url, args.timeout, args.api_key)
