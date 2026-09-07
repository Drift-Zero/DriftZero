#!/usr/bin/env python3
"""Verify ShopAssist server-side telemetry against a running DriftZero stack."""

from __future__ import annotations

import argparse
import json
import urllib.request


def json_request(url: str, *, body: dict | None = None) -> dict | list:
    payload = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"} if payload else {}
    request = urllib.request.Request(
        url,
        data=payload,
        headers=headers,
        method="POST" if payload else "GET",
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.load(response)


def run(shop_url: str, api_url: str) -> None:
    reply: dict | list = {}
    for _ in range(40):
        reply = json_request(
            f"{shop_url.rstrip('/')}/api/chat",
            body={
                "message": "Can I return headphones after 20 days?",
                "history": [],
                "scenario": "stale_returns",
            },
        )
        assert isinstance(reply, dict), reply
        if reply.get("telemetry") == "sent":
            break
    else:
        raise RuntimeError("ShopAssist did not flush a 20-interaction telemetry window.")

    models = json_request(f"{api_url.rstrip('/')}/api/v1/models")
    assert isinstance(models, list), models
    model = next((item for item in models if item.get("name") == "ShopAssist"), None)
    assert model is not None, models
    health = json_request(f"{api_url.rstrip('/')}/api/v1/models/{model['id']}/health?limit=20")
    assert isinstance(health, dict), health
    snapshot = next(
        (
            item
            for item in reversed(health["snapshots"])
            if item["source"] == "observed" and item["sample_size"] == 20
        ),
        None,
    )
    assert snapshot is not None, health
    assert snapshot["dimensions"]["groundedness"] < 80, snapshot
    print("ShopAssist smoke test passed: 20 observed interactions reached DriftZero.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--shop-url", default="http://localhost:3100")
    parser.add_argument("--api-url", default="http://localhost:8000")
    args = parser.parse_args()
    run(args.shop_url, args.api_url)
