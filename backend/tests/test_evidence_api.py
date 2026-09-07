from __future__ import annotations

import base64

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_evidence_import_review_and_search_api() -> None:
    app = create_app(Settings(database_url="sqlite://", environment="test"))
    with TestClient(app) as client:
        model = client.post(
            "/api/v1/models",
            json={"name": "ShopAssist", "provider": "gemini", "actor": "test"},
        ).json()
        imported = client.post(
            f"/api/v1/models/{model['id']}/evidence-sources/import",
            json={
                "filename": "catalog.csv",
                "content_base64": base64.b64encode(
                    b"name,price,colour\nAeroFit,3499,Black\n"
                ).decode(),
                "actor": "catalog-owner",
            },
        )

        assert imported.status_code == 201
        source = imported.json()
        assert source["status"] == "awaiting_review"
        assert source["chunks"][0]["locator"] == {"row": 2}

        hidden = client.post(
            f"/api/v1/models/{model['id']}/evidence/search",
            json={"query": "AeroFit price"},
        )
        assert hidden.json() == []

        approved = client.post(
            f"/api/v1/evidence-sources/{source['id']}/review",
            json={"status": "approved", "actor": "catalog-owner"},
        )
        assert approved.status_code == 200
        assert approved.json()["approved_by"] == "catalog-owner"

        search = client.post(
            f"/api/v1/models/{model['id']}/evidence/search",
            json={"query": "AeroFit price"},
        )
        assert search.status_code == 200
        assert search.json()[0]["filename"] == "catalog.csv"
        assert search.json()[0]["locator"] == {"row": 2}


def test_bad_file_type_has_a_clear_error() -> None:
    app = create_app(Settings(database_url="sqlite://", environment="test"))
    with TestClient(app) as client:
        model_id = client.post(
            "/api/v1/models", json={"name": "Bot", "actor": "test"}
        ).json()["id"]
        response = client.post(
            f"/api/v1/models/{model_id}/evidence-sources/import",
            json={
                "filename": "archive.zip",
                "content_base64": base64.b64encode(b"not a source").decode(),
            },
        )

    assert response.status_code == 422
    assert "Unsupported file type" in response.json()["detail"]
