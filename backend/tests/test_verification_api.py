"""The operator flow over HTTP: import, review, approve, evaluate, explain."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

QUESTION = "Can I return headphones after 20 days?"
STALE_ANSWER = "Yes. Headphones can be returned within 30 days."
RECOVERED_ANSWER = "Headphones can be returned within 14 days with a receipt."


@pytest.fixture
def client(tmp_path, monkeypatch) -> Iterator[TestClient]:
    monkeypatch.setenv("DRIFTZERO_DATABASE_URL", f"sqlite:///{tmp_path / 'verify.db'}")
    monkeypatch.setenv("DRIFTZERO_ENVIRONMENT", "test")
    with TestClient(create_app()) as client:
        yield client


@pytest.fixture
def model_id(client: TestClient) -> str:
    response = client.post(
        "/api/v1/models",
        json={"name": "ShopAssist", "provider": "demo-adapter", "environment": "simulation"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def load_demo(client: TestClient) -> dict:
    response = client.post("/api/v1/verification-sources/demo")
    assert response.status_code == 201, response.text
    return response.json()[0]


def test_a_loaded_source_starts_awaiting_review(client: TestClient) -> None:
    source = load_demo(client)

    assert source["status"] == "awaiting_review"
    assert source["versions"][0]["approved_at"] is None
    # The operator has content to review before deciding.
    assert source["versions"][0]["chunk_count"] > 0
    assert source["versions"][0]["fact_count"] > 0
    assert source["versions"][0]["content_hash"]


def test_evidence_is_reviewable_before_approval(client: TestClient) -> None:
    source = load_demo(client)

    response = client.get(f"/api/v1/verification-sources/{source['id']}/evidence")

    assert response.status_code == 200
    chunks = response.json()
    assert any("14 days" in chunk["text"] for chunk in chunks)


def test_an_unapproved_source_verifies_nothing(client: TestClient, model_id: str) -> None:
    load_demo(client)

    response = client.post(
        f"/api/v1/models/{model_id}/evaluate",
        json={"question": QUESTION, "answer": STALE_ANSWER},
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["claims"]
    assert all(claim["verdict"] == "insufficient_evidence" for claim in body["claims"])
    assert body["groundedness"]["confirmed_hallucination_rate"] == 0.0


def test_the_full_operator_flow(client: TestClient, model_id: str) -> None:
    """Import, approve, then catch the stale answer with a cited contradiction."""

    source = load_demo(client)

    approved = client.post(
        f"/api/v1/verification-sources/{source['id']}/approve",
        json={"actor": "priya", "reason": "Checked against the store handbook."},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"
    assert approved.json()["versions"][0]["approved_by"] == "priya"

    response = client.post(
        f"/api/v1/models/{model_id}/evaluate",
        json={"question": QUESTION, "answer": STALE_ANSWER},
    )
    assert response.status_code == 201, response.text
    body = response.json()

    contradicted = [c for c in body["claims"] if c["verdict"] == "contradicted"]
    assert contradicted, body["claims"]
    claim = contradicted[0]
    assert claim["method"] == "deterministic"
    assert "14 days" in claim["explanation"]
    assert claim["evidence"], "the operator must be shown the passage"

    assert body["groundedness"]["groundedness"] == 0.0
    assert body["groundedness"]["confirmed_hallucination_rate"] == 100.0
    assert "100 x 0 /" in body["groundedness"]["formula"]


def test_a_stored_evaluation_can_be_explained_later(client: TestClient, model_id: str) -> None:
    source = load_demo(client)
    client.post(
        f"/api/v1/verification-sources/{source['id']}/approve", json={"actor": "priya"}
    )
    created = client.post(
        f"/api/v1/models/{model_id}/evaluate",
        json={"question": QUESTION, "answer": STALE_ANSWER},
    ).json()

    response = client.get(f"/api/v1/evaluations/{created['id']}")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["claims"]
    assert body["groundedness"]["formula"]
    assert body["extractor_version"]
    assert body["verifier_version"]


def test_recovery_shows_up_in_the_metrics(client: TestClient, model_id: str) -> None:
    source = load_demo(client)
    client.post(
        f"/api/v1/verification-sources/{source['id']}/approve", json={"actor": "priya"}
    )

    before = client.post(
        f"/api/v1/models/{model_id}/evaluate",
        json={"question": QUESTION, "answer": STALE_ANSWER},
    ).json()
    after = client.post(
        f"/api/v1/models/{model_id}/evaluate",
        json={"question": QUESTION, "answer": RECOVERED_ANSWER},
    ).json()

    assert after["groundedness"]["groundedness"] > before["groundedness"]["groundedness"]
    assert after["groundedness"]["confirmed_hallucination_rate"] == 0.0


def test_the_summary_refuses_to_imply_health_below_the_window(
    client: TestClient, model_id: str
) -> None:
    source = load_demo(client)
    client.post(
        f"/api/v1/verification-sources/{source['id']}/approve", json={"actor": "priya"}
    )
    client.post(
        f"/api/v1/models/{model_id}/evaluate",
        json={"question": QUESTION, "answer": STALE_ANSWER},
    )

    body = client.get(f"/api/v1/models/{model_id}/evaluation-summary").json()

    assert body["evaluated_interactions"] == 1
    assert body["minimum_window"] == 20
    assert body["meets_minimum"] is False
    assert body["contradicted_claims"] >= 1


def test_retiring_a_source_stops_it_being_truth(client: TestClient, model_id: str) -> None:
    source = load_demo(client)
    client.post(
        f"/api/v1/verification-sources/{source['id']}/approve", json={"actor": "priya"}
    )
    client.post(
        f"/api/v1/verification-sources/{source['id']}/retire", json={"actor": "priya"}
    )

    body = client.post(
        f"/api/v1/models/{model_id}/evaluate",
        json={"question": QUESTION, "answer": STALE_ANSWER},
    ).json()

    assert all(claim["verdict"] == "insufficient_evidence" for claim in body["claims"])


def test_decisions_are_audited(client: TestClient, model_id: str) -> None:
    source = load_demo(client)
    client.post(
        f"/api/v1/verification-sources/{source['id']}/approve", json={"actor": "priya"}
    )
    client.post(
        f"/api/v1/models/{model_id}/evaluate",
        json={"question": QUESTION, "answer": STALE_ANSWER},
    )

    events = client.get(f"/api/v1/models/{model_id}/audit").json()

    assert any(event["event_type"] == "verification.evaluated" for event in events)
