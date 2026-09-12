from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.evidence import EvidenceError, EvidenceService, OpenAICompatibleStructurer, RawSegment
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


def test_groq_structurer_uses_strict_json_and_keeps_only_exact_quotes(monkeypatch) -> None:
    structurer = OpenAICompatibleStructurer(
        provider="groq",
        model="openai/gpt-oss-20b",
        api_key="test-key",
        base_url="https://api.groq.com/openai/v1",
        timeout_seconds=5,
    )
    requests: list[dict[str, object]] = []

    def response(payload: dict[str, object]) -> str:
        requests.append(payload)
        return json.dumps(
            {
                "facts": [
                    {
                        "segment_index": 0,
                        "statement": "The return window is 30 days.",
                        "evidence_quote": "Returns are accepted for 30 days.",
                    },
                    {
                        "segment_index": 0,
                        "statement": "A $50 fee applies.",
                        "evidence_quote": "A fee applies.",
                    },
                ]
            }
        )

    monkeypatch.setattr(structurer, "_post", response)

    facts = structurer.structure(
        [RawSegment("Returns are accepted for 30 days.", {"paragraph": 1})]
    )

    assert [fact.text for fact in facts] == ["The return window is 30 days."]
    assert facts[0].evidence_quote == "Returns are accepted for 30 days."
    response_format = requests[0]["response_format"]
    assert isinstance(response_format, dict)
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["strict"] is True


def test_groq_structurer_rejects_invalid_json(monkeypatch) -> None:
    structurer = OpenAICompatibleStructurer(
        provider="groq",
        model="openai/gpt-oss-20b",
        api_key="test-key",
        base_url="https://api.groq.com/openai/v1",
        timeout_seconds=5,
    )
    monkeypatch.setattr(structurer, "_post", lambda _payload: "not JSON")

    with pytest.raises(EvidenceError, match="did not return valid JSON"):
        structurer.structure([RawSegment("Returns take 30 days.", {"paragraph": 1})])


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
        raise AssertionError("Structured JSON must not be sent to an LLM")

    monkeypatch.setattr("app.website_sync.XaiWebsiteStructurer.structure", fail_if_called)
    monkeypatch.setattr("app.website_sync.build_groq_evidence_structurer", fail_if_called)
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
                "config": {
                    "refresh_interval_minutes": 10,
                    "use_groq": True,
                    "use_xai": True,
                },
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


def test_html_website_uses_groq_and_records_grounded_provenance(monkeypatch) -> None:
    text = "Returns are accepted for 30 days.\nSupport is available every weekday."
    page = FetchedPage(
        url="https://example.com/policy",
        title="Policy",
        text=text,
        links=[],
        status_code=200,
        latency_ms=12,
        content_hash=hashlib.sha256(text.encode()).hexdigest(),
    )
    monkeypatch.setattr("app.website_sync.fetch_website", lambda *_args, **_kwargs: page)
    monkeypatch.setattr(
        OpenAICompatibleStructurer,
        "_post",
        lambda _self, _payload: json.dumps(
            {
                "facts": [
                    {
                        "segment_index": 0,
                        "statement": "The return window is 30 days.",
                        "evidence_quote": "Returns are accepted for 30 days.",
                    }
                ]
            }
        ),
    )
    app = create_app(
        Settings(
            database_url="sqlite://",
            environment="test",
            groq_api_key="test-key",
            evidence_llm_model="openai/gpt-oss-20b",
        )
    )

    with TestClient(app) as client:
        model = client.post(
            "/api/v1/models", json={"name": "Groq website model", "provider": "custom"}
        ).json()
        connection = client.post(
            f"/api/v1/models/{model['id']}/connections",
            json={
                "kind": "website",
                "name": "Policy page",
                "url": page.url,
                "config": {
                    "refresh_interval_minutes": 10,
                    "use_groq": True,
                    "auto_approve": False,
                },
            },
        ).json()
        response = client.post(
            f"/api/v1/connections/{connection['id']}/website-refresh",
            json={"actor": "test"},
        )
        sources = client.get(f"/api/v1/models/{model['id']}/evidence-sources").json()

    assert response.status_code == 200
    assert response.json()["fact_count"] == 1
    assert len(sources) == 1
    source = sources[0]
    assert source["status"] == "awaiting_review"
    assert source["source_url"] == page.url
    assert source["fetched_at"] is not None
    assert source["last_checked_at"] is not None
    assert source["refresh_interval_minutes"] == 10
    assert source["content_hash"] == page.content_hash
    assert source["extraction_method"] == "deterministic+llm"
    assert source["llm_provider"] == "groq"
    assert source["llm_model"] == "openai/gpt-oss-20b"
    exact = [chunk for chunk in source["chunks"] if chunk["validation_status"] == "exact_match"]
    assert len(exact) == 1
    assert exact[0]["text"] == "The return window is 30 days."
    assert exact[0]["evidence_quote"] == "Returns are accepted for 30 days."
    assert exact[0]["locator"] == {"paragraph": 1}


def test_website_groq_rejects_unverifiable_facts_without_creating_source(monkeypatch) -> None:
    text = "Returns are accepted for 30 days."
    page = FetchedPage(
        url="https://example.com/policy",
        title="Policy",
        text=text,
        links=[],
        status_code=200,
        latency_ms=12,
        content_hash=hashlib.sha256(text.encode()).hexdigest(),
    )
    monkeypatch.setattr("app.website_sync.fetch_website", lambda *_args, **_kwargs: page)
    monkeypatch.setattr(
        OpenAICompatibleStructurer,
        "_post",
        lambda _self, _payload: json.dumps(
            {
                "facts": [
                    {
                        "segment_index": 0,
                        "statement": "A $50 fee applies.",
                        "evidence_quote": "A fee applies.",
                    }
                ]
            }
        ),
    )
    app = create_app(
        Settings(database_url="sqlite://", environment="test", groq_api_key="test-key")
    )

    with TestClient(app) as client:
        model = client.post(
            "/api/v1/models", json={"name": "Unverified facts", "provider": "custom"}
        ).json()
        connection = client.post(
            f"/api/v1/models/{model['id']}/connections",
            json={
                "kind": "website",
                "name": "Policy page",
                "url": page.url,
                "config": {"use_groq": True},
            },
        ).json()
        response = client.post(
            f"/api/v1/connections/{connection['id']}/website-refresh", json={}
        )
        sources = client.get(f"/api/v1/models/{model['id']}/evidence-sources").json()
        saved = client.get(f"/api/v1/models/{model['id']}/connections").json()[0]

    assert response.status_code == 422
    assert response.json()["detail"] == "groq returned no source-verifiable facts."
    assert sources == []
    assert "content_hash" not in saved["discovered_metadata"]
    assert saved["discovered_metadata"]["last_attempted_content_hash"] == page.content_hash


def test_failed_groq_refresh_preserves_evidence_and_retries_same_content(monkeypatch) -> None:
    first_text = "Returns are accepted for 30 days."
    changed_text = "Returns are accepted for 45 days."
    first_page = FetchedPage(
        url="https://example.com/policy",
        title="Policy",
        text=first_text,
        links=[],
        status_code=200,
        latency_ms=12,
        content_hash=hashlib.sha256(first_text.encode()).hexdigest(),
    )
    changed_page = FetchedPage(
        url="https://example.com/policy",
        title="Policy",
        text=changed_text,
        links=[],
        status_code=200,
        latency_ms=18,
        content_hash=hashlib.sha256(changed_text.encode()).hexdigest(),
    )
    pages = iter([first_page, changed_page, changed_page])
    monkeypatch.setattr("app.website_sync.fetch_website", lambda *_args, **_kwargs: next(pages))
    calls = 0

    def structure(_self: object, _payload: dict[str, object]) -> str:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise EvidenceError("groq evidence structuring failed.")
        days = 30 if calls == 1 else 45
        return json.dumps(
            {
                "facts": [
                    {
                        "segment_index": 0,
                        "statement": f"The return window is {days} days.",
                        "evidence_quote": f"Returns are accepted for {days} days.",
                    }
                ]
            }
        )

    monkeypatch.setattr(OpenAICompatibleStructurer, "_post", structure)
    app = create_app(
        Settings(database_url="sqlite://", environment="test", groq_api_key="test-key")
    )

    with TestClient(app) as client:
        model = client.post(
            "/api/v1/models", json={"name": "Versioned website", "provider": "custom"}
        ).json()
        connection = client.post(
            f"/api/v1/models/{model['id']}/connections",
            json={
                "kind": "website",
                "name": "Policy page",
                "url": first_page.url,
                "config": {"use_groq": True, "auto_approve": True},
            },
        ).json()
        first = client.post(f"/api/v1/connections/{connection['id']}/website-refresh", json={})
        failed = client.post(f"/api/v1/connections/{connection['id']}/website-refresh", json={})
        after_failure = client.get(
            f"/api/v1/models/{model['id']}/connections"
        ).json()[0]
        sources_after_failure = client.get(
            f"/api/v1/models/{model['id']}/evidence-sources"
        ).json()
        retried = client.post(f"/api/v1/connections/{connection['id']}/website-refresh", json={})
        final_sources = client.get(
            f"/api/v1/models/{model['id']}/evidence-sources"
        ).json()

    assert first.status_code == 200
    assert failed.status_code == 422
    assert failed.json()["detail"] == "groq evidence structuring failed."
    assert len(sources_after_failure) == 1
    assert sources_after_failure[0]["status"] == "approved"
    assert after_failure["discovered_metadata"]["content_hash"] == first_page.content_hash
    assert (
        after_failure["discovered_metadata"]["last_attempted_content_hash"]
        == changed_page.content_hash
    )
    assert retried.status_code == 200
    assert retried.json()["status"] == "updated"
    assert len(final_sources) == 2
    replacement = next(source for source in final_sources if source["status"] == "approved")
    prior = next(source for source in final_sources if source["status"] == "retired")
    assert replacement["supersedes_source_id"] == prior["id"]
    assert replacement["source_url"] == prior["source_url"] == first_page.url


def test_post_import_failure_rolls_back_source_and_does_not_poison_hash(monkeypatch) -> None:
    text = "Returns are accepted for 30 days."
    page = FetchedPage(
        url="https://example.com/policy",
        title="Policy",
        text=text,
        links=[],
        status_code=200,
        latency_ms=12,
        content_hash=hashlib.sha256(text.encode()).hexdigest(),
    )
    monkeypatch.setattr("app.website_sync.fetch_website", lambda *_args, **_kwargs: page)
    original_import = EvidenceService.import_source
    calls = 0

    def fail_after_import(self: EvidenceService, *args: object, **kwargs: object):
        nonlocal calls
        calls += 1
        result = original_import(self, *args, **kwargs)
        if calls == 1:
            raise RuntimeError("failure after evidence rows were prepared")
        return result

    monkeypatch.setattr(EvidenceService, "import_source", fail_after_import)
    app = create_app(Settings(database_url="sqlite://", environment="test"))

    with TestClient(app) as client:
        model = client.post(
            "/api/v1/models", json={"name": "Atomic website", "provider": "custom"}
        ).json()
        connection = client.post(
            f"/api/v1/models/{model['id']}/connections",
            json={
                "kind": "website",
                "name": "Policy page",
                "url": page.url,
                "config": {"use_groq": False},
            },
        ).json()
        failed = client.post(f"/api/v1/connections/{connection['id']}/website-refresh", json={})
        sources_after_failure = client.get(
            f"/api/v1/models/{model['id']}/evidence-sources"
        ).json()
        saved = client.get(f"/api/v1/models/{model['id']}/connections").json()[0]
        retried = client.post(f"/api/v1/connections/{connection['id']}/website-refresh", json={})

    assert failed.status_code == 422
    assert failed.json()["detail"] == "Website refresh failed unexpectedly."
    assert sources_after_failure == []
    assert "content_hash" not in saved["discovered_metadata"]
    assert saved["discovered_metadata"]["last_attempted_content_hash"] == page.content_hash
    assert retried.status_code == 200
    assert retried.json()["status"] == "updated"


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
