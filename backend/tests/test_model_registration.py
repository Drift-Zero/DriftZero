from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def make_client() -> TestClient:
    return TestClient(create_app(Settings(database_url="sqlite://", environment="test")))


def registration_payload() -> dict[str, object]:
    return {
        "name": "SupportCopilot",
        "provider": "openai",
        "environment": "staging",
        "description": "Answers support questions from the approved knowledge base.",
        "retention_days": 45,
        "actor": "owner@example.com",
        "initial_version": {
            "label": "release-1",
            "model_identifier": "gpt-production",
            "prompt_version": "support-prompt-v1",
            "configuration": {"temperature": 0.1, "max_tokens": 500},
            "tools": ["knowledge_search", "ticket_lookup", "knowledge_search"],
            "corpus_version": "support-2026-09",
            "evaluation_policy_version": "health-v1",
        },
    }


def test_complete_model_registration_and_lifecycle() -> None:
    with make_client() as client:
        created = client.post("/api/v1/models", json=registration_payload())
        assert created.status_code == 201
        model = created.json()
        model_id = model["id"]
        assert model == {
            **{
                key: value
                for key, value in model.items()
                if key in {"id", "created_at", "updated_at"}
            },
            "name": "SupportCopilot",
            "provider": "openai",
            "environment": "staging",
            "description": "Answers support questions from the approved knowledge base.",
            "status": "active",
            "retention_days": 45,
        }

        readiness = client.get(f"/api/v1/models/{model_id}/registration-status")
        assert readiness.status_code == 200
        assert readiness.json()["ready_for_telemetry"] is True
        assert readiness.json()["monitoring_state"] == "awaiting_telemetry"
        assert readiness.json()["active_version_id"] is not None

        versions = client.get(f"/api/v1/models/{model_id}/versions")
        assert versions.status_code == 200
        assert len(versions.json()) == 1
        first_version = versions.json()[0]
        assert first_version["label"] == "release-1"
        assert first_version["active_to"] is None
        assert len(first_version["config_hash"]) == 64
        assert len(first_version["tool_set_hash"]) == 64
        assert len(first_version["fingerprint"]) == 64

        updated = client.patch(
            f"/api/v1/models/{model_id}",
            json={
                "description": "Production support assistant.",
                "environment": "production",
                "retention_days": 60,
                "actor": "owner@example.com",
            },
        )
        assert updated.status_code == 200
        assert updated.json()["description"] == "Production support assistant."
        assert updated.json()["environment"] == "production"
        assert updated.json()["retention_days"] == 60

        second = client.post(
            f"/api/v1/models/{model_id}/versions",
            json={
                "label": "release-2",
                "model_identifier": "gpt-production",
                "prompt_version": "support-prompt-v2",
                "configuration": {"max_tokens": 500, "temperature": 0.1},
                "tools": ["ticket_lookup", "knowledge_search"],
                "corpus_version": "support-2026-09",
                "evaluation_policy_version": "health-v1",
                "actor": "release-bot",
            },
        )
        assert second.status_code == 201
        assert second.json()["active_to"] is None

        versions = client.get(f"/api/v1/models/{model_id}/versions").json()
        version_by_id = {version["id"]: version for version in versions}
        assert version_by_id[first_version["id"]]["active_to"] is not None
        assert version_by_id[second.json()["id"]]["active_to"] is None

        reactivated = client.post(
            f"/api/v1/models/{model_id}/versions/{first_version['id']}/activate",
            json={"actor": "release-manager"},
        )
        assert reactivated.status_code == 200
        assert reactivated.json()["active_to"] is None

        paused = client.post(
            f"/api/v1/models/{model_id}/lifecycle",
            json={"status": "paused", "actor": "owner@example.com"},
        )
        assert paused.status_code == 200
        assert paused.json()["status"] == "paused"
        readiness = client.get(f"/api/v1/models/{model_id}/registration-status").json()
        assert readiness["ready_for_telemetry"] is False
        assert readiness["monitoring_state"] == "paused"

        retired = client.post(
            f"/api/v1/models/{model_id}/lifecycle",
            json={"status": "retired", "actor": "owner@example.com"},
        )
        assert retired.status_code == 200
        cannot_reactivate = client.post(
            f"/api/v1/models/{model_id}/lifecycle",
            json={"status": "active", "actor": "owner@example.com"},
        )
        assert cannot_reactivate.status_code == 409

        audit = client.get(f"/api/v1/models/{model_id}/audit")
        assert audit.status_code == 200
        events = {event["event_type"] for event in audit.json()}
        assert {
            "model.created",
            "model.updated",
            "model.version_created",
            "model.version_activated",
            "model.lifecycle_changed",
        } <= events


def test_registration_rejects_duplicate_identity_and_configuration() -> None:
    with make_client() as client:
        first = client.post("/api/v1/models", json=registration_payload())
        assert first.status_code == 201
        model_id = first.json()["id"]

        duplicate_model = client.post("/api/v1/models", json=registration_payload())
        assert duplicate_model.status_code == 409

        same_version = {
            **registration_payload()["initial_version"],
            "actor": "owner@example.com",
        }
        duplicate_version = client.post(
            f"/api/v1/models/{model_id}/versions",
            json=same_version,
        )
        assert duplicate_version.status_code == 409


def test_registration_without_version_is_not_ready() -> None:
    with make_client() as client:
        created = client.post(
            "/api/v1/models",
            json={"name": "UnconfiguredModel", "actor": "owner@example.com"},
        )
        assert created.status_code == 201

        readiness = client.get(
            f"/api/v1/models/{created.json()['id']}/registration-status"
        )
        assert readiness.status_code == 200
        assert readiness.json()["ready_for_telemetry"] is False
        checks = {check["code"]: check for check in readiness.json()["checks"]}
        assert checks["active_version_fingerprinted"]["passed"] is False


def test_empty_model_patch_is_rejected() -> None:
    with make_client() as client:
        created = client.post("/api/v1/models", json=registration_payload())
        response = client.patch(
            f"/api/v1/models/{created.json()['id']}",
            json={"actor": "owner@example.com"},
        )

        assert response.status_code == 422
