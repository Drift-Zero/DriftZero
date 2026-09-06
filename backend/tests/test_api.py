from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def make_client() -> TestClient:
    return TestClient(
        create_app(
            Settings(
                database_url="sqlite://",
                environment="test",
            )
        )
    )


def test_campus_demo_runs_from_warning_to_verified_recovery() -> None:
    with make_client() as client:
        healthcheck = client.get("/healthz")
        assert healthcheck.status_code == 200
        assert healthcheck.json() == {"status": "ok", "environment": "test"}

        reset = client.post("/api/v1/demo/reset")
        assert reset.status_code == 200
        demo = reset.json()

        model_id = demo["model"]["id"]
        plan_id = demo["recovery"]["id"]
        assert [snapshot["score"] for snapshot in demo["health"]["snapshots"]] == [
            92.0,
            87.0,
            74.0,
            61.0,
        ]
        assert demo["health"]["forecast"]["predicted_score"] == 48.0
        assert demo["health"]["forecast"]["direction"] == "deteriorating"
        assert demo["diagnosis"]["probable_cause"] == "knowledge_freshness_failure"
        assert demo["diagnosis"]["confidence"] == 0.87
        assert demo["diagnosis"]["confidence_label"] == "estimated"
        assert demo["recovery"]["state"] == "recommended"
        assert demo["recovery"]["simulation"] is True
        assert len(demo["recovery"]["actions"]) == 5

        blocked = client.post(
            f"/api/v1/recovery/{plan_id}/execute",
            json={
                "actor": "demo-operator",
                "idempotency_key": "demo-run-blocked",
            },
        )
        assert blocked.status_code == 409
        assert blocked.json()["error"] == "invalid_transition"

        approval = client.post(
            f"/api/v1/recovery/{plan_id}/approve",
            json={"actor": "demo-operator"},
        )
        assert approval.status_code == 200
        assert approval.json()["state"] == "approved"
        assert approval.json()["approved_by"] == "demo-operator"

        execution = client.post(
            f"/api/v1/recovery/{plan_id}/execute",
            json={
                "actor": "demo-operator",
                "idempotency_key": "demo-run-success",
            },
        )
        assert execution.status_code == 200
        assert execution.json()["state"] == "recovered"
        assert execution.json()["verified_at"] is not None

        timeline = client.get(f"/api/v1/models/{model_id}/health")
        assert timeline.status_code == 200
        assert timeline.json()["snapshots"][-1]["score"] == 84.2
        assert timeline.json()["snapshots"][-1]["source"] == "simulated"

        diagnosis = client.get(f"/api/v1/models/{model_id}/diagnoses/latest")
        assert diagnosis.status_code == 200
        assert diagnosis.json()["status"] == "resolved"

        audit = client.get(f"/api/v1/models/{model_id}/audit")
        event_types = {event["event_type"] for event in audit.json()}
        assert {
            "demo.reset",
            "diagnosis.created",
            "recovery.approved",
            "recovery.execution_started",
            "recovery.verified",
        } <= event_types


def test_demo_reset_is_repeatable_and_replaces_previous_scenario() -> None:
    with make_client() as client:
        first = client.post("/api/v1/demo/reset")
        second = client.post("/api/v1/demo/reset")

        assert first.status_code == 200
        assert second.status_code == 200
        models = client.get("/api/v1/models")
        assert models.status_code == 200
        assert [model["name"] for model in models.json()] == ["CampusGPT"]
        assert first.json()["model"]["id"] != second.json()["model"]["id"]


def test_unknown_resources_return_stable_error_contract() -> None:
    with make_client() as client:
        response = client.get("/api/v1/models/does-not-exist/health")

        assert response.status_code == 404
        assert response.json() == {
            "error": "not_found",
            "detail": "Monitored model not found.",
        }
