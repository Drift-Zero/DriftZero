from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_connection_onboarding_supports_the_three_sources_without_storing_api_keys() -> None:
    with TestClient(
        create_app(Settings(database_url="sqlite://", environment="test"))
    ) as client:
        model = client.post("/api/v1/models", json={"name": "Support AI"}).json()
        model_id = model["id"]

        github = client.post(
            f"/api/v1/models/{model_id}/connections",
            json={
                "kind": "github",
                "name": "Support service source",
                "repository": "acme/support-service",
                "branch": "main",
            },
        )
        assert github.status_code == 201
        assert github.json()["status"] == "needs_setup"

        telemetry = client.post(
            f"/api/v1/models/{model_id}/connections",
            json={
                "kind": "telemetry",
                "name": "Production events",
                "url": "https://dz.example/ingest",
            },
        )
        assert telemetry.status_code == 201
        assert telemetry.json()["status"] == "configured"

        api = client.post(
            f"/api/v1/models/{model_id}/connections",
            json={
                "kind": "api",
                "name": "Inference endpoint",
                "api_endpoint": "https://api.example.com/v1/chat",
                "auth_scheme": "bearer",
                "api_key": "secret-that-must-not-be-returned",
            },
        )
        assert api.status_code == 201
        body = api.json()
        assert body["credential_configured"] is True
        assert "api_key" not in body
        assert "secret-that-must-not-be-returned" not in api.text

        listed = client.get(f"/api/v1/models/{model_id}/connections")
        assert listed.status_code == 200
        assert {item["kind"] for item in listed.json()} == {"github", "telemetry", "api"}


def test_connection_validation_requires_a_target() -> None:
    with TestClient(
        create_app(Settings(database_url="sqlite://", environment="test"))
    ) as client:
        model = client.post("/api/v1/models", json={"name": "Validation AI"}).json()
        response = client.post(
            f"/api/v1/models/{model['id']}/connections",
            json={"kind": "api", "name": "Missing endpoint"},
        )
        assert response.status_code == 422
