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
    RawSegment,
    StructuredFact,
    _validate_fact,
    parse_evidence_file,
)
from app.schemas import EvidenceImportRequest, EvidenceReviewRequest, EvidenceSearchRequest


def encoded(value: bytes) -> str:
    return base64.b64encode(value).decode()


def test_json_records_keep_exact_json_paths() -> None:
    _, segments = parse_evidence_file(
        "catalog.json",
        json.dumps(
            {"products": [{"name": "AeroFit", "price": 3499, "colour": "Black"}]}
        ).encode(),
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


def test_source_must_be_approved_before_retrieval(
    session: Session, model: MonitoredModel
) -> None:
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
    assert service.search(
        session, model.id, EvidenceSearchRequest(query="AeroFit price")
    ) == []

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
