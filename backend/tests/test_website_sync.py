from __future__ import annotations

import json
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.website_sync import FetchedPage, XaiWebsiteStructurer


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
