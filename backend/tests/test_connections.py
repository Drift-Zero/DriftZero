import socket
from datetime import UTC, datetime

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.config import Settings
from app.connections import CheckResult, ConnectionCheckError, validate_target_url
from app.main import create_app

SECRET_KEY = Fernet.generate_key().decode()


def make_client() -> TestClient:
    return TestClient(
        create_app(
            Settings(
                database_url="sqlite://",
                environment="test",
                connection_secret_key=SECRET_KEY,
            )
        )
    )


def telemetry_payload() -> dict[str, object]:
    return {
        "observed_at": datetime.now(UTC).isoformat(),
        "dimensions": {"quality": 90, "reliability": 95, "safety": 98},
        "sample_size": 50,
        "coverage": 1,
        "source": "observed",
    }


def test_connection_onboarding_supports_all_sources_and_write_only_secrets() -> None:
    with make_client() as client:
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
        assert github.json()["status"] == "configured"

        telemetry = client.post(
            f"/api/v1/models/{model_id}/connections",
            json={"kind": "telemetry", "name": "Production events"},
        )
        assert telemetry.status_code == 201
        ingestion_key = telemetry.json()["ingestion_key"]
        assert ingestion_key.startswith("dz_ing_")
        assert telemetry.json()["url"] == f"/api/v1/models/{model_id}/telemetry"

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
        assert api.json()["credential_configured"] is True
        assert "api_key" not in api.json()
        assert "secret-that-must-not-be-returned" not in api.text

        listed = client.get(f"/api/v1/models/{model_id}/connections")
        assert listed.status_code == 200
        assert {item["kind"] for item in listed.json()} == {"github", "telemetry", "api"}
        assert all("ingestion_key" not in item for item in listed.json())


def test_telemetry_connection_enforces_its_one_time_ingestion_key() -> None:
    with make_client() as client:
        model = client.post("/api/v1/models", json={"name": "Protected AI"}).json()
        connection = client.post(
            f"/api/v1/models/{model['id']}/connections",
            json={"kind": "telemetry", "name": "SDK"},
        ).json()

        missing = client.post(
            f"/api/v1/models/{model['id']}/telemetry", json=telemetry_payload()
        )
        assert missing.status_code == 403

        accepted = client.post(
            f"/api/v1/models/{model['id']}/telemetry",
            json=telemetry_payload(),
            headers={"X-DriftZero-Ingest-Key": connection["ingestion_key"]},
        )
        assert accepted.status_code == 201


def test_connection_check_persists_discovery_evidence_and_audit_event() -> None:
    class Inspector:
        def check(self, connection: object, credential: str | None) -> CheckResult:
            assert credential is None
            return CheckResult(
                status_code=200,
                latency_ms=42,
                metadata={"commit_sha": "abc123", "tree_entries": 87},
            )

    with make_client() as client:
        model = client.post("/api/v1/models", json={"name": "Repository AI"}).json()
        connection = client.post(
            f"/api/v1/models/{model['id']}/connections",
            json={"kind": "github", "name": "Source", "repository": "acme/ai"},
        ).json()
        client.app.state.service.connection_inspector = Inspector()

        checked = client.post(
            f"/api/v1/connections/{connection['id']}/check",
            json={"actor": "owner@example.com"},
        )
        assert checked.status_code == 200
        assert checked.json()["healthy"] is True
        saved = checked.json()["connection"]
        assert saved["status"] == "connected"
        assert saved["last_latency_ms"] == 42
        assert saved["discovered_metadata"]["commit_sha"] == "abc123"

        audit = client.get(f"/api/v1/models/{model['id']}/audit").json()
        assert "model.connection_checked" in {event["event_type"] for event in audit}


def test_connection_validation_and_vault_configuration_errors_are_clear() -> None:
    with make_client() as client:
        model = client.post("/api/v1/models", json={"name": "Validation AI"}).json()
        response = client.post(
            f"/api/v1/models/{model['id']}/connections",
            json={"kind": "api", "name": "Missing endpoint"},
        )
        assert response.status_code == 422

    app = create_app(Settings(database_url="sqlite://", environment="test"))
    with TestClient(app) as client:
        model = client.post("/api/v1/models", json={"name": "No Vault AI"}).json()
        response = client.post(
            f"/api/v1/models/{model['id']}/connections",
            json={
                "kind": "api",
                "name": "Protected endpoint",
                "api_endpoint": "https://api.example.com/chat",
                "api_key": "cannot-store-without-vault",
            },
        )
        assert response.status_code == 422
        assert response.json()["error"] == "connection_configuration_failed"


def test_production_connection_check_blocks_private_network_targets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def private_address(*args: object, **kwargs: object) -> list[tuple[object, ...]]:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 8000))]

    monkeypatch.setattr(socket, "getaddrinfo", private_address)
    settings = Settings(environment="production")

    with pytest.raises(ConnectionCheckError, match="Private or reserved"):
        validate_target_url("https://internal.example.com/api", settings)
