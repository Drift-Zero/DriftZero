import sqlalchemy as sa
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import KnowledgeDocument, KnowledgeSource, ModelVersion
from app.main import create_app
from app.recovery_worker import process_recovery_commands

RECOVERY_HEADERS = {
    "X-DriftZero-Actor": "demo-operator",
    "X-DriftZero-Role": "operator",
}


def make_client() -> TestClient:
    return TestClient(
        create_app(
            Settings(
                database_url="sqlite://",
                environment="test",
                recovery_allow_local_identity=True,
            )
        )
    )


def test_shopassist_demo_runs_from_warning_to_verified_recovery() -> None:
    with make_client() as client:
        healthcheck = client.get("/healthz")
        assert healthcheck.status_code == 200
        assert healthcheck.json() == {"status": "ok", "environment": "test"}

        reset = client.post("/api/v1/demo/reset")
        assert reset.status_code == 200
        demo = reset.json()

        model_id = demo["model"]["id"]
        plan_id = demo["recovery"]["id"]
        assert demo["model"]["name"] == "ShopAssist"
        assert [snapshot["score"] for snapshot in demo["health"]["snapshots"]] == [
            91.9,
            87.2,
            74.8,
            62.5,
        ]
        assert demo["health"]["forecast"]["predicted_score"] == 50.2
        assert demo["health"]["forecast"]["direction"] == "deteriorating"
        assert demo["diagnosis"]["probable_cause"] == "knowledge_freshness_failure"
        assert demo["diagnosis"]["confidence"] == 0.87
        assert demo["diagnosis"]["confidence_label"] == "estimated"
        assert "RETIRED_RETURN_POLICY_RETRIEVED" in {
            item["reason_code"] for item in demo["diagnosis"]["evidence"]
        }
        assert demo["recovery"]["state"] == "recommended"
        assert demo["recovery"]["simulation"] is True
        assert len(demo["recovery"]["actions"]) == 5

        ingested = client.post(
            "/api/v1/shopassist/telemetry",
            json={
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
        )
        assert ingested.status_code == 201
        assert ingested.json()["state"] == "critical"
        assert ingested.json()["sample_size"] == 20

        blocked = client.post(
            f"/api/v1/recovery/{plan_id}/execute",
            json={
                "actor": "demo-operator",
                "idempotency_key": "demo-run-blocked",
            },
            headers=RECOVERY_HEADERS,
        )
        assert blocked.status_code == 409
        assert blocked.json()["error"] == "invalid_transition"

        approval = client.post(
            f"/api/v1/recovery/{plan_id}/approve",
            json={"actor": "demo-operator"},
            headers=RECOVERY_HEADERS,
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
            headers=RECOVERY_HEADERS,
        )
        assert execution.status_code == 202
        assert execution.json()["state"] == "pending"

        summary = process_recovery_commands(
            client.app.state.database,
            client.app.state.service,
            limit=1,
        )
        assert summary.succeeded == 1
        command = client.get(f"/api/v1/recovery-commands/{execution.json()['id']}")
        assert command.json()["state"] == "succeeded"
        recovery = client.get(f"/api/v1/recovery/{plan_id}")
        assert recovery.json()["state"] == "recovered"
        assert recovery.json()["verified_at"] is not None
        assert recovery.json()["verification"]["observed_requests"] == 50
        assert recovery.json()["verification"]["observed_requests"] >= 20
        assert recovery.json()["verification"]["passed"] is True

        timeline = client.get(f"/api/v1/models/{model_id}/health")
        assert timeline.status_code == 200
        assert timeline.json()["snapshots"][-1]["score"] == 84.7
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
        assert [model["name"] for model in models.json()] == ["ShopAssist"]
        assert first.json()["model"]["id"] != second.json()["model"]["id"]

        model_id = second.json()["model"]["id"]
        versions = client.get(f"/api/v1/models/{model_id}/versions")
        assert versions.status_code == 200
        assert versions.json()[0]["label"] == "shopassist-demo-v1"
        assert versions.json()[0]["evaluation_policy_version"] == "shopassist-returns-v1"

        with client.app.state.database.session_factory() as session:
            sources = session.scalars(
                sa.select(KnowledgeSource).where(KnowledgeSource.model_id == model_id)
            ).all()
            documents = session.scalars(
                sa.select(KnowledgeDocument)
                .join(KnowledgeSource)
                .where(KnowledgeSource.model_id == model_id)
            ).all()
            version = session.scalar(
                sa.select(ModelVersion).where(ModelVersion.model_id == model_id)
            )
        assert {source.status for source in sources} == {"fresh", "stale"}
        assert {document.is_stale for document in documents} == {False, True}
        assert version is not None


def test_shopassist_server_side_telemetry_enforces_twenty_sample_window() -> None:
    with make_client() as client:
        client.post("/api/v1/demo/reset")
        dimensions = {
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

        rejected = client.post(
            "/api/v1/shopassist/telemetry",
            json={"dimensions": dimensions, "sample_size": 19, "coverage": 0.95},
        )
        assert rejected.status_code == 422
        assert rejected.json() == {
            "error": "telemetry_ingestion_failed",
            "detail": "ShopAssist telemetry window requires at least 20 samples; received 19.",
        }

        accepted = client.post(
            "/api/v1/shopassist/telemetry",
            json={"dimensions": dimensions, "sample_size": 20, "coverage": 0.95},
        )
        assert accepted.status_code == 201
        assert accepted.json()["sample_size"] == 20
        assert accepted.json()["score"] is not None


def test_demo_reset_is_forbidden_in_production() -> None:
    app = create_app(Settings(database_url="sqlite://", environment="production"))
    with TestClient(app) as client:
        response = client.post("/api/v1/demo/reset")

    assert response.status_code == 403
    assert response.json() == {
        "error": "forbidden",
        "detail": "Demo reset is disabled in production environments.",
    }


def test_unknown_resources_return_stable_error_contract() -> None:
    with make_client() as client:
        response = client.get("/api/v1/models/does-not-exist/health")

        assert response.status_code == 404
        assert response.json() == {
            "error": "not_found",
            "detail": "Monitored model not found.",
        }
