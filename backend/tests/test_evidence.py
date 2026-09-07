"""Trusted evidence is exact, review-gated, and traceable to its source."""

from __future__ import annotations

import base64
import io
import json

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import MonitoredModel
from app.evidence import (
    EvidenceConflict,
    EvidenceError,
    EvidenceService,
    FetchedEvidence,
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
