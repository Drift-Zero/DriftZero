"""Owner connectors turn real interactions into auditable health telemetry."""

from __future__ import annotations

import base64

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_interaction_batch_generates_claim_results_and_health_snapshot() -> None:
    app = create_app(Settings(database_url="sqlite://", environment="test"))
    with TestClient(app) as client:
        model = client.post(
            "/api/v1/models",
            json={"name": "PolicyBot", "provider": "local", "actor": "owner"},
        ).json()
        imported = client.post(
            f"/api/v1/models/{model['id']}/evidence-sources/import",
            json={
                "filename": "policies.json",
                "content_base64": base64.b64encode(
                    b'{"returns":"Electronics can be returned within 14 days."}'
                ).decode(),
                "actor": "owner",
            },
        ).json()
        client.post(
            f"/api/v1/evidence-sources/{imported['id']}/review",
            json={"status": "approved", "actor": "owner"},
        )
        preview = client.post(
            f"/api/v1/models/{model['id']}/claims/verify",
            json={"answer": "Electronics can be returned within 30 days."},
        )
        assert preview.status_code == 200
        assert preview.json()["claims"][0]["verdict"] == "contradicted"
        interactions = [
            {
                "request_id": f"request-{index}",
                "question": "What is the return window for electronics?",
                "answer": (
                    "Electronics can be returned within 14 days."
                    if index < 15
                    else "Electronics can be returned within 30 days."
                ),
                "provider": "local-llama",
                "latency_ms": 500,
            }
            for index in range(20)
        ]

        response = client.post(
            f"/api/v1/models/{model['id']}/interactions/evaluate",
            json={"event_id": "window:test-001", "interactions": interactions},
        )

        assert response.status_code == 201
        body = response.json()
        assert body["formula"] == "claim-verification-v1"
        assert body["supported_claims"] == 15
        assert body["contradicted_claims"] == 5
        assert body["unverified_claims"] == 0
        assert body["evidence_coverage"] == 1
        assert body["groundedness_score"] == 75
        assert body["health_snapshot"]["sample_size"] == 20
        assert body["health_snapshot"]["dimensions"]["quality"] == 75
        assert body["health_snapshot"]["score"] is not None
        assert body["interactions"][0]["claims"][0]["evidence"]["source_id"] == imported["id"]

        timeline = client.get(f"/api/v1/models/{model['id']}/health").json()
        assert timeline["snapshots"][-1]["event_id"] == "window:test-001"


def test_unverifiable_batch_does_not_manufacture_a_health_score() -> None:
    app = create_app(Settings(database_url="sqlite://", environment="test"))
    with TestClient(app) as client:
        model_id = client.post(
            "/api/v1/models", json={"name": "UnknownBot", "actor": "owner"}
        ).json()["id"]

        response = client.post(
            f"/api/v1/models/{model_id}/interactions/evaluate",
            json={
                "interactions": [
                    {
                        "question": "What happened?",
                        "answer": "A claim with no approved source exists.",
                    }
                ]
                * 20
            },
        )

        assert response.status_code == 201
        body = response.json()
        assert body["unverified_claims"] == 20
        assert body["evidence_coverage"] == 0
        assert body["health_snapshot"]["score"] is None
        assert body["health_snapshot"]["state"] == "insufficient_data"
