"""The recovery API must not trust actor or role supplied in JSON."""

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_recovery_mutation_requires_a_configured_identity() -> None:
    app = create_app(Settings(database_url="sqlite://", environment="test"))
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/recovery/not-a-plan/approve",
            json={"actor": "forged-admin", "role": "admin"},
        )

    assert response.status_code == 401
    assert response.json()["detail"] == "A valid recovery credential is required."


def test_operator_identity_comes_from_credential_not_json() -> None:
    app = create_app(
        Settings(
            database_url="sqlite://",
            environment="test",
            recovery_operator_api_key="operator-secret",
        )
    )
    with TestClient(app) as client:
        demo = client.post("/api/v1/demo/reset").json()
        plan_id = demo["recovery"]["id"]
        rejected = client.post(
            f"/api/v1/recovery/{plan_id}/approve",
            json={"actor": "forged-admin", "role": "admin"},
            headers={"Authorization": "Bearer wrong-secret"},
        )
        approved = client.post(
            f"/api/v1/recovery/{plan_id}/approve",
            json={"actor": "forged-admin", "role": "admin"},
            headers={
                "Authorization": "Bearer operator-secret",
                "X-DriftZero-Actor": "alice@example.com",
            },
        )

    assert rejected.status_code == 401
    assert approved.status_code == 200
    assert approved.json()["approved_by"] == "alice@example.com"
    assert approved.json()["approved_role"] == "operator"


def test_local_identity_is_forbidden_in_production_even_if_flagged() -> None:
    app = create_app(
        Settings(
            database_url="sqlite://",
            environment="production",
            recovery_allow_local_identity=True,
        )
    )
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/recovery/not-a-plan/approve",
            json={"actor": "local", "role": "admin"},
            headers={"X-DriftZero-Actor": "local", "X-DriftZero-Role": "admin"},
        )

    assert response.status_code == 401
