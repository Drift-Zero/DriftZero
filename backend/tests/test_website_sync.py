from __future__ import annotations

import json
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.website_sync import FetchedPage, WebsiteSyncError, XaiWebsiteStructurer


class _JsonResponse:
    status = 200

    def __init__(self, payload: object) -> None:
        self.payload = payload

    def __enter__(self) -> _JsonResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, _limit: int | None = None) -> bytes:
        return json.dumps(self.payload).encode()


def test_xai_structurer_keeps_only_source_verifiable_facts(monkeypatch) -> None:
    content = json.dumps(
        {
            "summary": "Returns policy",
            "facts": [
                {
                    "name": "Return period",
                    "value": "30 days",
                    "evidence_quote": "Returns are accepted for 30 days.",
                },
                {
                    "name": "Invented fee",
                    "value": "$50",
                    "evidence_quote": "A fee applies.",
                },
            ],
        }
    )
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *_args, **_kwargs: _JsonResponse(
            {"choices": [{"message": {"content": content}}]}
        ),
    )
    page = FetchedPage(
        url="https://example.com/policy",
        title="Policy",
        text="Returns are accepted for 30 days.",
        links=[],
        status_code=200,
        latency_ms=10,
        content_hash="abc",
    )

    result = XaiWebsiteStructurer(Settings(xai_api_key="test-key")).structure(page)

    assert result["facts"] == [
        {
            "name": "Return period",
            "value": "30 days",
            "evidence_quote": "Returns are accepted for 30 days.",
        }
    ]


def test_website_refresh_creates_approved_json_and_detects_no_change(monkeypatch) -> None:
    app = create_app(Settings(database_url="sqlite://", environment="test"))
    page = FetchedPage(
        url="https://example.com/policy",
        title="Policy",
        text="Returns are accepted for 30 days.\nSupport is available every weekday.",
        links=[],
        status_code=200,
        latency_ms=12,
        content_hash="stable-hash",
    )
    monkeypatch.setattr("app.website_sync.fetch_website", lambda *_args, **_kwargs: page)
    with TestClient(app) as client:
        model = client.post(
            "/api/v1/models",
            json={"name": "Website model", "provider": "custom"},
        ).json()
        connection = client.post(
            f"/api/v1/models/{model['id']}/connections",
            json={
                "kind": "website",
                "name": "Policy page",
                "url": page.url,
                "config": {
                    "refresh_interval_minutes": 10,
                    "use_xai": False,
                    "auto_approve": True,
                },
            },
        ).json()

        first = client.post(
            f"/api/v1/connections/{connection['id']}/website-refresh",
            json={"actor": "test"},
        )
        second = client.post(
            f"/api/v1/connections/{connection['id']}/website-refresh",
            json={"actor": "test"},
        )
        sources = client.get(
            f"/api/v1/models/{model['id']}/evidence-sources"
        ).json()

    assert first.status_code == 200
    assert first.json()["status"] == "updated"
    assert first.json()["fact_count"] == 2
    assert second.json()["status"] == "unchanged"
    assert len(sources) == 1
    assert sources[0]["status"] == "approved"
    assert sources[0]["filename"] == "website-example.com.json"


def test_website_refresh_imports_structured_json_without_xai(monkeypatch) -> None:
    app = create_app(Settings(database_url="sqlite://", environment="test"))
    page = FetchedPage(
        url="https://example.com/catalog.json",
        title="catalog.json",
        text='{"price": 149, "stock": 18}',
        links=[],
        status_code=200,
        latency_ms=12,
        content_hash="json-hash",
        structured_data={"product": "Nova ANC Headphones", "price": 149, "stock": 18},
    )
    monkeypatch.setattr("app.website_sync.fetch_website", lambda *_args, **_kwargs: page)

    def fail_if_called(*_args, **_kwargs) -> None:
        raise AssertionError("Structured JSON must not be sent to xAI")

    monkeypatch.setattr("app.website_sync.XaiWebsiteStructurer.structure", fail_if_called)
    with TestClient(app) as client:
        model = client.post(
            "/api/v1/models", json={"name": "JSON feed model", "provider": "custom"}
        ).json()
        connection = client.post(
            f"/api/v1/models/{model['id']}/connections",
            json={
                "kind": "website",
                "name": "Catalog feed",
                "url": page.url,
                "config": {"refresh_interval_minutes": 10, "use_xai": True},
            },
        ).json()

        response = client.post(
            f"/api/v1/connections/{connection['id']}/website-refresh",
            json={"actor": "test"},
        )
        sources = client.get(f"/api/v1/models/{model['id']}/evidence-sources").json()

    assert response.status_code == 200
    assert response.json()["status"] == "updated"
    assert response.json()["fact_count"] == 1
    assert len(sources) == 1
    assert sources[0]["chunk_count"] == 1
    assert "Nova ANC Headphones" in sources[0]["chunks"][0]["text"]


def test_connection_due_uses_configured_interval() -> None:
    from app.db import ModelConnection
    from app.website_sync import connection_is_due

    now = datetime.now(UTC)
    connection = ModelConnection(
        model_id="model",
        kind="website",
        name="Site",
        url="https://example.com",
        config={"refresh_interval_minutes": 10},
        discovered_metadata={"last_synced_at": now.isoformat()},
    )

    assert not connection_is_due(connection, now)


def test_failed_refresh_records_visible_status_and_check_time(monkeypatch) -> None:
    app = create_app(Settings(database_url="sqlite://", environment="test"))

    def fail_fetch(*_args, **_kwargs) -> None:
        raise WebsiteSyncError("The website could not be fetched.")

    monkeypatch.setattr("app.website_sync.fetch_website", fail_fetch)
    with TestClient(app) as client:
        model = client.post(
            "/api/v1/models",
            json={"name": "Website model", "provider": "custom"},
        ).json()
        connection = client.post(
            f"/api/v1/models/{model['id']}/connections",
            json={
                "kind": "website",
                "name": "Unavailable policy page",
                "url": "https://example.com/policy",
                "config": {"refresh_interval_minutes": 10, "use_xai": False},
            },
        ).json()

        response = client.post(
            f"/api/v1/connections/{connection['id']}/website-refresh",
            json={"actor": "test"},
        )
        saved = client.get(f"/api/v1/models/{model['id']}/connections").json()[0]

    assert response.status_code == 422
    assert response.json()["detail"] == "The website could not be fetched."
    assert saved["status"] == "error"
    assert saved["last_error"] == "The website could not be fetched."
    assert saved["last_checked_at"] is not None


def test_unexpected_refresh_failure_is_recorded_safely(monkeypatch) -> None:
    app = create_app(Settings(database_url="sqlite://", environment="test"))

    def fail_fetch(*_args, **_kwargs) -> None:
        raise RuntimeError("sensitive provider detail")

    monkeypatch.setattr("app.website_sync.fetch_website", fail_fetch)
    with TestClient(app) as client:
        model = client.post(
            "/api/v1/models",
            json={"name": "Website model", "provider": "custom"},
        ).json()
        connection = client.post(
            f"/api/v1/models/{model['id']}/connections",
            json={
                "kind": "website",
                "name": "Broken policy page",
                "url": "https://example.com/policy",
                "config": {"refresh_interval_minutes": 10, "use_xai": False},
            },
        ).json()

        response = client.post(
            f"/api/v1/connections/{connection['id']}/website-refresh",
            json={"actor": "test"},
        )
        saved = client.get(f"/api/v1/models/{model['id']}/connections").json()[0]

    assert response.status_code == 422
    assert response.json()["detail"] == "Website refresh failed unexpectedly."
    assert saved["status"] == "error"
    assert saved["last_error"] == "Website refresh failed unexpectedly."
    assert saved["last_checked_at"] is not None
