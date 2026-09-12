"""Trusted evidence is exact, review-gated, and traceable to its source."""

from __future__ import annotations

import base64
import io
import json
import urllib.error

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import MonitoredModel
from app.evidence import (
    EVIDENCE_STRUCTURING_BATCH_SIZE,
    EvidenceConflict,
    EvidenceError,
    EvidenceService,
    FetchedEvidence,
    OpenAICompatibleStructurer,
    RawSegment,
    StructuredFact,
    _validate_fact,
    _validate_public_url,
    parse_evidence_file,
)
from app.schemas import (
    EvidenceImportRequest,
    EvidenceRefreshRequest,
    EvidenceReviewRequest,
    EvidenceSearchRequest,
    EvidenceUrlImportRequest,
)


def encoded(value: bytes) -> str:
    return base64.b64encode(value).decode()


def groq_structurer(*, api_key: str = "test-secret") -> OpenAICompatibleStructurer:
    return OpenAICompatibleStructurer(
        provider="groq",
        model="openai/gpt-oss-20b",
        api_key=api_key,
        base_url="https://api.groq.com/openai/v1",
        timeout_seconds=5,
    )


def provider_http_error(status: int, body: bytes) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "https://api.groq.com/openai/v1/chat/completions",
        status,
        "provider error",
        hdrs=None,
        fp=io.BytesIO(body),
    )


def test_provider_http_error_exposes_only_bounded_safe_diagnostics(monkeypatch) -> None:
    secret = "test-secret"
    body = json.dumps(
        {
            "error": {
                "type": "invalid_request_error",
                "code": "json_validate_failed",
                "message": f"Schema rejected. Authorization: Bearer {secret}. " + "x" * 400,
            }
        }
    ).encode()

    def fail(*_args: object, **_kwargs: object) -> None:
        raise provider_http_error(400, body)

    monkeypatch.setattr("urllib.request.urlopen", fail)

    with pytest.raises(EvidenceError) as captured:
        groq_structurer(api_key=secret)._post({"model": "test"})

    message = str(captured.value)
    assert message.startswith(
        "groq evidence structuring returned HTTP 400 "
        "(type=invalid_request_error, code=json_validate_failed):"
    )
    assert secret not in message
    assert "Authorization: Bearer" not in message
    assert len(message) < 400


def test_provider_http_error_reports_only_failed_generation_metadata(monkeypatch) -> None:
    failed_generation = '{"facts": [{"segment_index": 0}]}'
    body = json.dumps(
        {
            "error": {
                "type": "invalid_request_error",
                "code": "json_validate_failed",
                "message": "Failed to validate JSON.",
                "failed_generation": failed_generation,
            }
        }
    ).encode()

    def fail(*_args: object, **_kwargs: object) -> None:
        raise provider_http_error(400, body)

    monkeypatch.setattr("urllib.request.urlopen", fail)

    with pytest.raises(EvidenceError) as captured:
        groq_structurer()._post({"model": "test"})

    message = str(captured.value)
    assert "failed_generation_present=true" in message
    assert f"failed_generation_length={len(failed_generation)}" in message
    assert "failed_generation_json_like=true" in message
    assert failed_generation not in message


def test_provider_http_error_does_not_expose_unstructured_body(monkeypatch) -> None:
    unsafe_body = b"upstream proxy body that must not be returned"

    def fail(*_args: object, **_kwargs: object) -> None:
        raise provider_http_error(503, unsafe_body)

    monkeypatch.setattr("urllib.request.urlopen", fail)

    with pytest.raises(
        EvidenceError,
        match=r"^groq evidence structuring returned HTTP 503\.$",
    ):
        groq_structurer()._post({"model": "test"})


def test_provider_network_error_remains_generic(monkeypatch) -> None:
    def fail(*_args: object, **_kwargs: object) -> None:
        raise urllib.error.URLError("private network detail")

    monkeypatch.setattr("urllib.request.urlopen", fail)

    with pytest.raises(
        EvidenceError,
        match=r"^groq evidence structuring failed\.$",
    ):
        groq_structurer()._post({"model": "test"})


def test_structurer_splits_multiple_segments_into_small_batches(monkeypatch) -> None:
    structurer = groq_structurer()
    batches: list[list[dict[str, object]]] = []

    def respond(payload: dict[str, object]) -> str:
        messages = payload["messages"]
        assert isinstance(messages, list)
        batch = json.loads(messages[1]["content"])
        batches.append(batch)
        return json.dumps(
            {
                "facts": [
                    {
                        "segment_index": item["segment_index"],
                        "statement": item["text"],
                        "evidence_quote": item["text"],
                    }
                    for item in batch
                ]
            }
        )

    monkeypatch.setattr(structurer, "_post", respond)
    segments = [
        RawSegment(f"Verified statement number {index}.", {"paragraph": index})
        for index in range(9)
    ]

    facts = structurer.structure(segments)

    assert EVIDENCE_STRUCTURING_BATCH_SIZE == 4
    assert [len(batch) for batch in batches] == [4, 4, 1]
    assert len(facts) == 9


def test_structurer_splits_multiline_webpage_segment_before_batching(monkeypatch) -> None:
    structurer = groq_structurer()
    batches: list[list[dict[str, object]]] = []

    def respond(payload: dict[str, object]) -> str:
        messages = payload["messages"]
        assert isinstance(messages, list)
        batch = json.loads(messages[1]["content"])
        batches.append(batch)
        return json.dumps(
            {
                "facts": [
                    {
                        "segment_index": item["segment_index"],
                        "statement": item["text"],
                        "evidence_quote": item["text"],
                    }
                    for item in batch
                ]
            }
        )

    monkeypatch.setattr(structurer, "_post", respond)
    lines = [f"Verified webpage line {index}." for index in range(6)]

    facts = structurer.structure(
        [RawSegment("\n".join(lines), {"paragraph": 1, "character_offset": 10})]
    )

    assert [len(batch) for batch in batches] == [4, 2]
    assert [item["text"] for batch in batches for item in batch] == lines
    assert [fact.evidence_quote for fact in facts] == lines
    assert facts[0].locator["character_offset"] == 10
    assert facts[1].locator["character_offset"] == 10 + len(lines[0]) + 1


def test_invalid_provider_json_in_later_batch_fails_all_structuring(monkeypatch) -> None:
    structurer = groq_structurer()
    calls = 0

    def respond(_payload: dict[str, object]) -> str:
        nonlocal calls
        calls += 1
        if calls == 2:
            return "not JSON"
        return json.dumps(
            {
                "facts": [
                    {
                        "segment_index": 0,
                        "statement": "Verified statement 0.",
                        "evidence_quote": "Verified statement 0.",
                    }
                ]
            }
        )

    monkeypatch.setattr(structurer, "_post", respond)
    segments = [
        RawSegment(f"Verified statement {index}.", {"paragraph": index})
        for index in range(5)
    ]

    with pytest.raises(EvidenceError, match="did not return valid JSON"):
        structurer.structure(segments)


def test_structurer_accepts_empty_facts_array(monkeypatch) -> None:
    structurer = groq_structurer()
    monkeypatch.setattr(structurer, "_post", lambda _payload: '{"facts": []}')

    assert structurer.structure([RawSegment("Navigation", {"paragraph": 1})]) == []


def test_structurer_rejects_invalid_segment_index_and_nonexistent_quote(monkeypatch) -> None:
    structurer = groq_structurer()
    monkeypatch.setattr(
        structurer,
        "_post",
        lambda _payload: json.dumps(
            {
                "facts": [
                    {
                        "segment_index": 9,
                        "statement": "The return period is 30 days.",
                        "evidence_quote": "Returns are accepted within 30 days.",
                    },
                    {
                        "segment_index": 0,
                        "statement": "The return period is 30 days.",
                        "evidence_quote": "Returns are accepted within 30 days.",
                    },
                ]
            }
        ),
    )

    assert structurer.structure(
        [RawSegment("Support is available every weekday.", {"paragraph": 1})]
    ) == []


def test_json_records_keep_exact_json_paths() -> None:
    _, segments = parse_evidence_file(
        "catalog.json",
        json.dumps({"products": [{"name": "AeroFit", "price": 3499, "colour": "Black"}]}).encode(),
    )

    assert len(segments) == 1
    assert segments[0].locator == {"json_path": "$.products[0]"}
    assert '"price": 3499' in segments[0].text


def test_pdf_text_keeps_page_number() -> None:
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 72 720 Td (Returns close after 30 days.) Tj ET")
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
    )
    page[NameObject("/Contents")] = writer._add_object(stream)
    output = io.BytesIO()
    writer.write(output)

    _, segments = parse_evidence_file("policy.pdf", output.getvalue())

    assert segments[0].locator == {"paragraph": 1, "page": 1}
    assert "Returns close after 30 days." in segments[0].text


def test_llm_fact_must_quote_source_and_copy_numbers() -> None:
    segments = [RawSegment("Returns are accepted within 30 days.", {"page": 2})]

    valid = _validate_fact(
        {
            "segment_index": 0,
            "statement": "The return window is 30 days.",
            "evidence_quote": "Returns are accepted within 30 days.",
        },
        segments,
    )
    invented = _validate_fact(
        {
            "segment_index": 0,
            "statement": "The return window is 90 days.",
            "evidence_quote": "Returns are accepted within 30 days.",
        },
        segments,
    )

    assert valid is not None
    assert valid.validation_status == "exact_match"
    assert invented is None


@pytest.mark.parametrize("url", ["file:///etc/passwd", "http://127.0.0.1/data.json"])
def test_url_import_blocks_non_public_targets(url: str) -> None:
    with pytest.raises(EvidenceError):
        _validate_public_url(url)


def test_source_must_be_approved_before_retrieval(session: Session, model: MonitoredModel) -> None:
    service = EvidenceService(Settings(evidence_max_file_bytes=1024 * 1024))
    imported = service.import_source(
        session,
        model.id,
        EvidenceImportRequest(
            filename="catalog.json",
            content_base64=encoded(b'{"name":"AeroFit","price":3499,"colour":"Black"}'),
            actor="tester",
        ),
    )

    assert imported.status == "awaiting_review"
    assert imported.chunks[0].locator == {"json_path": "$"}
    assert service.search(session, model.id, EvidenceSearchRequest(query="AeroFit price")) == []

    approved = service.review_source(
        session,
        imported.id,
        EvidenceReviewRequest(status="approved", actor="reviewer"),
    )
    hits = service.search(session, model.id, EvidenceSearchRequest(query="AeroFit price"))

    assert approved.approved_by == "reviewer"
    assert hits[0].evidence_quote == imported.chunks[0].evidence_quote
    assert hits[0].corpus_version.startswith("evidence-")


def test_duplicate_bytes_are_rejected(session: Session, model: MonitoredModel) -> None:
    service = EvidenceService(Settings())
    request = EvidenceImportRequest(
        filename="facts.txt",
        content_base64=encoded(b"The support line closes at 18:00."),
    )
    service.import_source(session, model.id, request)

    with pytest.raises(EvidenceConflict, match="already source"):
        service.import_source(session, model.id, request)


def test_llm_structuring_is_not_allowed_for_structured_files(
    session: Session, model: MonitoredModel
) -> None:
    class FakeStructurer:
        provider = "fake"
        model = "fake-v1"

        def structure(self, segments: list[RawSegment]) -> list[StructuredFact]:
            return []

    service = EvidenceService(Settings(), structurer=FakeStructurer())
    with pytest.raises(EvidenceError, match="only used for PDF"):
        service.import_source(
            session,
            model.id,
            EvidenceImportRequest(
                filename="facts.json",
                content_base64=encoded(b'{"answer":42}'),
                use_llm=True,
            ),
        )


def test_llm_facts_are_added_without_removing_raw_evidence(
    session: Session, model: MonitoredModel
) -> None:
    class FakeStructurer:
        provider = "fake"
        model = "fake-v1"

        def structure(self, segments: list[RawSegment]) -> list[StructuredFact]:
            return [
                StructuredFact(
                    text="The return window is 30 days.",
                    evidence_quote="Unused products may be returned within 30 days.",
                    locator=segments[0].locator,
                    validation_status="exact_match",
                )
            ]

    service = EvidenceService(Settings(), structurer=FakeStructurer())
    imported = service.import_source(
        session,
        model.id,
        EvidenceImportRequest(
            filename="returns.md",
            content_base64=encoded(b"Unused products may be returned within 30 days."),
            use_llm=True,
        ),
    )

    assert imported.extraction_method == "deterministic+llm"
    assert imported.chunk_count == 2
    assert {chunk.validation_status for chunk in imported.chunks} == {
        "deterministic",
        "exact_match",
    }


def test_exact_fact_outranks_large_deterministic_passage(
    session: Session, model: MonitoredModel
) -> None:
    exact_quote = "Nimbus Adapter $ 119 · 50 available"

    class FakeStructurer:
        provider = "fake"
        model = "fake-v1"

        def structure(self, segments: list[RawSegment]) -> list[StructuredFact]:
            return [
                StructuredFact(
                    text=exact_quote,
                    evidence_quote=exact_quote,
                    locator=segments[0].locator,
                    validation_status="exact_match",
                )
            ]

    broad_context = " ".join(["General catalog information"] * 35)
    service = EvidenceService(Settings(), structurer=FakeStructurer())
    imported = service.import_source(
        session,
        model.id,
        EvidenceImportRequest(
            filename="catalog.txt",
            content_base64=encoded(f"{broad_context} {exact_quote}".encode()),
            use_llm=True,
        ),
    )
    service.review_source(
        session,
        imported.id,
        EvidenceReviewRequest(status="approved", actor="reviewer"),
    )

    hits = service.search(
        session,
        model.id,
        EvidenceSearchRequest(query="The Nimbus Adapter costs $119", limit=3),
    )

    assert hits[0].validation_status == "exact_match"
    assert hits[0].evidence_quote == exact_quote
    assert hits[0].relevance > hits[1].relevance


def test_deterministic_passage_remains_available_as_search_fallback(
    session: Session, model: MonitoredModel
) -> None:
    service = EvidenceService(Settings())
    imported = service.import_source(
        session,
        model.id,
        EvidenceImportRequest(
            filename="catalog.txt",
            content_base64=encoded(b"Nimbus support is available every weekday."),
        ),
    )
    service.review_source(
        session,
        imported.id,
        EvidenceReviewRequest(status="approved", actor="reviewer"),
    )

    hits = service.search(
        session,
        model.id,
        EvidenceSearchRequest(query="Nimbus weekday support", limit=3),
    )

    assert len(hits) == 1
    assert hits[0].validation_status == "deterministic"


class FakeEvidenceFetcher:
    def __init__(self, responses: list[FetchedEvidence]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, str | None, str | None]] = []

    def fetch(
        self,
        source_url: str,
        *,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> FetchedEvidence:
        self.calls.append((source_url, etag, last_modified))
        return self.responses.pop(0)


def test_url_import_records_provenance_and_requires_review(
    session: Session, model: MonitoredModel
) -> None:
    fetcher = FakeEvidenceFetcher(
        [
            FetchedEvidence(
                content=b'{"station":"Alpha","temperature":21}',
                filename="weather.json",
                media_type="application/json",
                etag='"v1"',
                last_modified="Mon, 07 Sep 2026 12:00:00 GMT",
            )
        ]
    )
    service = EvidenceService(Settings(), fetcher=fetcher)

    imported = service.import_url(
        session,
        model.id,
        EvidenceUrlImportRequest(
            source_url="https://data.example.test/weather.geojson",
            auto_refresh=True,
            refresh_interval_minutes=15,
            actor="owner",
        ),
    )

    assert imported.status == "awaiting_review"
    assert imported.filename == "weather.json"
    assert imported.source_url == "https://data.example.test/weather.geojson"
    assert imported.etag == '"v1"'
    assert imported.auto_refresh is True
    assert imported.refresh_interval_minutes == 15


def test_url_refresh_creates_reviewable_version_and_retires_old_after_approval(
    session: Session, model: MonitoredModel
) -> None:
    fetcher = FakeEvidenceFetcher(
        [
            FetchedEvidence(
                content=b'{"policy":"14 days"}',
                filename="policy.json",
                media_type="application/json",
                etag='"v1"',
            ),
            FetchedEvidence(
                content=b'{"policy":"30 days"}',
                filename="policy.json",
                media_type="application/json",
                etag='"v2"',
            ),
        ]
    )
    service = EvidenceService(Settings(), fetcher=fetcher)
    first = service.import_url(
        session,
        model.id,
        EvidenceUrlImportRequest(
            source_url="https://data.example.test/policy.json",
            auto_refresh=True,
            actor="owner",
        ),
    )
    service.review_source(
        session,
        first.id,
        EvidenceReviewRequest(status="approved", actor="reviewer"),
    )

    replacement = service.refresh_source(
        session,
        first.id,
        EvidenceRefreshRequest(actor="sync-worker"),
    )

    assert replacement.id != first.id
    assert replacement.status == "awaiting_review"
    assert replacement.supersedes_source_id == first.id
    assert replacement.auto_refresh is True
    assert fetcher.calls[-1][1] == '"v1"'

    service.review_source(
        session,
        replacement.id,
        EvidenceReviewRequest(status="approved", actor="reviewer"),
    )
    assert service.get_source(session, first.id).status == "retired"
    assert service.get_source(session, replacement.id).status == "approved"


def test_unchanged_url_refresh_reuses_source(session: Session, model: MonitoredModel) -> None:
    fetcher = FakeEvidenceFetcher(
        [
            FetchedEvidence(
                content=b'{"answer":42}',
                filename="facts.json",
                media_type="application/json",
                etag='"v1"',
            ),
            FetchedEvidence(
                content=None,
                filename="facts.json",
                media_type="application/json",
                etag='"v1"',
                not_modified=True,
            ),
        ]
    )
    service = EvidenceService(Settings(), fetcher=fetcher)
    imported = service.import_url(
        session,
        model.id,
        EvidenceUrlImportRequest(source_url="https://data.example.test/facts.json"),
    )

    unchanged = service.refresh_source(
        session,
        imported.id,
        EvidenceRefreshRequest(actor="sync-worker"),
    )

    assert unchanged.id == imported.id
    assert unchanged.last_checked_at is not None
