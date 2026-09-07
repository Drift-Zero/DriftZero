"""Security boundary and replay-protection regression tests."""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

DIMENSIONS = {
    "quality": 90,
    "groundedness": 90,
    "semantic_stability": 90,
    "temporal_stability": 90,
    "safety": 95,
    "drift": 90,
    "reliability": 95,
    "latency": 90,
    "cost": 90,
}


def test_production_management_api_fails_closed_without_keys() -> None:
    app = create_app(Settings(database_url="sqlite://", environment="production"))

    with TestClient(app) as client:
        health = client.get("/healthz")
        denied = client.get("/api/v1/models")
        docs = client.get("/docs")

    assert health.status_code == 200
    assert health.headers["strict-transport-security"].startswith("max-age=")
    assert denied.status_code == 503
    assert denied.json()["error"] == "security_misconfigured"
    assert docs.status_code == 404


def test_management_keys_enforce_read_write_and_delete_roles() -> None:
    app = create_app(
        Settings(
            database_url="sqlite://",
            environment="test",
            api_require_auth=True,
            api_viewer_key="viewer-secret",
            api_operator_key="operator-secret",
            api_admin_key="admin-secret",
        )
    )

    with TestClient(app) as client:
        unauthorized = client.get("/api/v1/models")
        readable = client.get(
            "/api/v1/models", headers={"Authorization": "Bearer viewer-secret"}
        )
        viewer_write = client.post(
            "/api/v1/models",
            json={"name": "Forbidden"},
            headers={"Authorization": "Bearer viewer-secret"},
        )
        created = client.post(
            "/api/v1/models",
            json={"name": "Secured AI"},
            headers={"Authorization": "Bearer operator-secret"},
        )
        operator_delete = client.delete(
            "/api/v1/connections/not-a-connection",
            headers={"Authorization": "Bearer operator-secret"},
        )
        admin_delete = client.delete(
            "/api/v1/connections/not-a-connection",
            headers={"Authorization": "Bearer admin-secret"},
        )

    assert unauthorized.status_code == 401
    assert readable.status_code == 200
    assert viewer_write.status_code == 403
    assert created.status_code == 201
    assert operator_delete.status_code == 403
    assert admin_delete.status_code == 404


def test_request_size_rate_limit_and_security_headers() -> None:
    app = create_app(
        Settings(
            database_url="sqlite://",
            environment="test",
            api_max_request_bytes=64,
            api_rate_limit_per_minute=2,
        )
    )

    with TestClient(app) as client:
        too_large = client.post("/api/v1/models", json={"name": "x" * 100})
        first = client.get("/api/v1/models")
        second = client.get("/api/v1/models")
        limited = client.get("/api/v1/models")

    assert too_large.status_code == 413
    assert first.status_code == 200
    assert second.status_code == 200
    assert limited.status_code == 429
    assert first.headers["x-content-type-options"] == "nosniff"
    assert first.headers["x-frame-options"] == "DENY"
    assert first.headers["cache-control"] == "no-store"


def test_untrusted_host_is_rejected() -> None:
    app = create_app(
        Settings(
            database_url="sqlite://",
            environment="test",
            trusted_hosts=("api.driftzero.example",),
        )
    )

    with TestClient(app) as client:
        rejected = client.get("/healthz", headers={"Host": "evil.example"})
        accepted = client.get(
            "/healthz", headers={"Host": "api.driftzero.example"}
        )

    assert rejected.status_code == 400
    assert accepted.status_code == 200


def test_telemetry_event_id_makes_retries_idempotent() -> None:
    app = create_app(Settings(database_url="sqlite://", environment="test"))

    with TestClient(app) as client:
        model = client.post("/api/v1/models", json={"name": "Retry-safe AI"}).json()
        payload = {
            "event_id": "evt-00000001",
            "schema_version": "1.0",
            "dimensions": DIMENSIONS,
            "sample_size": 20,
            "coverage": 0.95,
        }
        first = client.post(f"/api/v1/models/{model['id']}/telemetry", json=payload)
        replay = client.post(f"/api/v1/models/{model['id']}/telemetry", json=payload)
        timeline = client.get(f"/api/v1/models/{model['id']}/health")

    assert first.status_code == 201
    assert replay.status_code == 201
    assert replay.json()["id"] == first.json()["id"]
    assert replay.json()["event_id"] == "evt-00000001"
    assert len(timeline.json()["snapshots"]) == 1


def test_future_telemetry_and_unconfigured_production_ingest_are_rejected() -> None:
    future_app = create_app(
        Settings(
            database_url="sqlite://",
            environment="test",
            telemetry_max_future_skew_seconds=30,
        )
    )
    with TestClient(future_app) as client:
        model = client.post("/api/v1/models", json={"name": "Clock AI"}).json()
        response = client.post(
            f"/api/v1/models/{model['id']}/telemetry",
            json={
                "observed_at": (datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
                "dimensions": DIMENSIONS,
                "sample_size": 20,
                "coverage": 0.95,
            },
        )
    assert response.status_code == 422
    assert "producer clock" in response.json()["detail"]

    production_app = create_app(
        Settings(
            database_url="sqlite://",
            environment="production",
            api_admin_key="admin-secret",
        )
    )
    with TestClient(production_app) as client:
        model = client.post(
            "/api/v1/models",
            json={"name": "Production AI"},
            headers={"Authorization": "Bearer admin-secret"},
        ).json()
        response = client.post(
            f"/api/v1/models/{model['id']}/telemetry",
            json={
                "dimensions": DIMENSIONS,
                "sample_size": 20,
                "coverage": 0.95,
            },
        )

    assert response.status_code == 403
    assert "telemetry connection" in response.json()["detail"]
