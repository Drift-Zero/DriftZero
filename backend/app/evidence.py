"""Trusted-file ingestion and retrieval for evidence-grounded evaluation.

Extraction is intentionally hybrid: deterministic parsers preserve exact file
content and locations, while an optional LLM may turn unstructured passages
into atomic facts. LLM output is accepted only when its evidence quote occurs
in the parser output and every number in the fact occurs in that quote.
"""

from __future__ import annotations

import base64
import binascii
import csv
import hashlib
import io
import json
import mimetypes
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import PurePath
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import Settings
from app.db import (
    DEFAULT_TENANT_ID,
    ActorType,
    AuditEvent,
    EvidenceChunk,
    EvidenceSource,
    MonitoredModel,
    utc_now,
)
from app.schemas import (
    EvidenceImportRequest,
    EvidenceReviewRequest,
    EvidenceSearchHit,
    EvidenceSearchRequest,
    EvidenceSourceResponse,
)

SUPPORTED_SUFFIXES = frozenset({".pdf", ".json", ".csv", ".txt", ".md"})
UNSTRUCTURED_SUFFIXES = frozenset({".pdf", ".txt", ".md"})
TOKEN_RE = re.compile(r"[\w₹$€£.%+-]+", re.UNICODE)
NUMBER_RE = re.compile(r"(?<!\w)[+-]?(?:\d[\d,]*(?:\.\d+)?%?)(?!\w)")


class EvidenceError(ValueError):
    """A safe, user-facing ingestion error."""


class EvidenceNotFound(LookupError):
    """A model or source does not exist in the current tenant."""


class EvidenceConflict(ValueError):
    """The exact source bytes were already imported for this model."""


@dataclass(frozen=True, slots=True)
class RawSegment:
    text: str
    locator: dict[str, object]


@dataclass(frozen=True, slots=True)
class StructuredFact:
    text: str
    evidence_quote: str
    locator: dict[str, object]
    validation_status: str


class EvidenceStructurer(Protocol):
    provider: str
    model: str

    def structure(self, segments: list[RawSegment]) -> list[StructuredFact]: ...


def _clean_text(value: str) -> str:
    return re.sub(r"[ \t]+", " ", value.replace("\x00", "")).strip()


def _text_segments(text: str, *, page: int | None = None) -> list[RawSegment]:
    paragraphs = [
        _clean_text(part)
        for part in re.split(r"\n\s*\n", text.replace("\r\n", "\n"))
        if _clean_text(part)
    ]
    segments: list[RawSegment] = []
    for paragraph_index, paragraph in enumerate(paragraphs, start=1):
        # Bound the evidence sent to an LLM and returned through the API without
        # destroying the exact source excerpt.
        for offset in range(0, len(paragraph), 1200):
            chunk = paragraph[offset : offset + 1200].strip()
            if not chunk:
                continue
            locator: dict[str, object] = {"paragraph": paragraph_index}
            if page is not None:
                locator["page"] = page
            if offset:
                locator["character_offset"] = offset
            segments.append(RawSegment(text=chunk, locator=locator))
    return segments


def _json_segments(value: object, path: str = "$") -> list[RawSegment]:
    if isinstance(value, list):
        return [
            segment
            for index, item in enumerate(value)
            for segment in _json_segments(item, f"{path}[{index}]")
        ]
    if isinstance(value, dict):
        scalar = {
            str(key): item
            for key, item in value.items()
            if not isinstance(item, (dict, list))
        }
        segments = []
        if scalar:
            segments.append(
                RawSegment(
                    text=json.dumps(scalar, ensure_ascii=False, sort_keys=True),
                    locator={"json_path": path},
                )
            )
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                segments.extend(_json_segments(item, f"{path}.{key}"))
        return segments
    return [
        RawSegment(
            text=json.dumps(value, ensure_ascii=False),
            locator={"json_path": path},
        )
    ]


def parse_evidence_file(filename: str, content: bytes) -> tuple[str, list[RawSegment]]:
    """Parse supported bytes without asking an LLM to read exact values."""

    suffix = PurePath(filename).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        supported = ", ".join(sorted(SUPPORTED_SUFFIXES))
        raise EvidenceError(f"Unsupported file type {suffix or '(none)'}. Use {supported}.")
    if not content:
        raise EvidenceError("The uploaded file is empty.")

    try:
        if suffix == ".pdf":
            try:
                from pypdf import PdfReader
            except ImportError as exc:  # pragma: no cover - packaging catches this
                raise EvidenceError("PDF support is not installed on the API server.") from exc
            try:
                reader = PdfReader(io.BytesIO(content))
                segments = [
                    segment
                    for page_number, page in enumerate(reader.pages, start=1)
                    for segment in _text_segments(page.extract_text() or "", page=page_number)
                ]
            except Exception as exc:
                raise EvidenceError("The PDF could not be read or is encrypted.") from exc
        elif suffix == ".json":
            parsed = json.loads(content.decode("utf-8-sig"))
            segments = _json_segments(parsed)
        elif suffix == ".csv":
            text = content.decode("utf-8-sig")
            rows = csv.DictReader(io.StringIO(text))
            if not rows.fieldnames:
                raise EvidenceError("The CSV must include a header row.")
            segments = [
                RawSegment(
                    text=json.dumps(row, ensure_ascii=False, sort_keys=True),
                    locator={"row": row_number},
                )
                for row_number, row in enumerate(rows, start=2)
            ]
        else:
            segments = _text_segments(content.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError, csv.Error) as exc:
        raise EvidenceError(f"{suffix[1:].upper()} parsing failed: {exc}") from exc

    segments = [segment for segment in segments if segment.text.strip()]
    if not segments:
        if suffix == ".pdf":
            raise EvidenceError("No text was found. Scanned PDFs require OCR before upload.")
        raise EvidenceError("The file contained no usable evidence.")
    if len(segments) > 5000:
        raise EvidenceError("The file produced more than 5,000 evidence chunks.")
    return suffix, segments


class OpenAICompatibleStructurer:
    """Small HTTP client shared by Gemini and Groq's compatible endpoints."""

    def __init__(
        self,
        *,
        provider: str,
        model: str,
        api_key: str,
        base_url: str,
        timeout_seconds: float,
    ) -> None:
        self.provider = provider
        self.model = model
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def structure(self, segments: list[RawSegment]) -> list[StructuredFact]:
        facts: list[StructuredFact] = []
        for start in range(0, len(segments), 12):
            batch = segments[start : start + 12]
            payload_segments = [
                {"segment_index": index, "text": segment.text}
                for index, segment in enumerate(batch)
            ]
            request_body = {
                "model": self.model,
                "temperature": 0.1,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "Extract atomic factual statements from the supplied source segments. "
                            "Return JSON only as {\"facts\":[{\"segment_index\":0,"
                            "\"statement\":\"...\",\"evidence_quote\":\"exact substring...\"}]}. "
                            "Do not infer or add facts. The quote must be copied exactly from its "
                            "segment. Omit headings, opinions, instructions, and non-factual text."
                        ),
                    },
                    {"role": "user", "content": json.dumps(payload_segments, ensure_ascii=False)},
                ],
            }
            response = self._post(request_body)
            parsed = _parse_llm_json(response)
            for item in parsed.get("facts", []):
                fact = _validate_fact(item, batch)
                if fact is not None:
                    facts.append(fact)
        return facts

    def _post(self, payload: dict[str, object]) -> str:
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode(),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                body = json.loads(response.read())
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise EvidenceError(f"{self.provider} evidence structuring failed.") from exc
        try:
            return str(body["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as exc:
            raise EvidenceError(f"{self.provider} returned an invalid response.") from exc


def _parse_llm_json(content: str) -> dict[str, Any]:
    stripped = content.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*|\s*```$", "", stripped, flags=re.I)
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise EvidenceError("The evidence LLM did not return valid JSON.") from exc
    if not isinstance(value, dict) or not isinstance(value.get("facts", []), list):
        raise EvidenceError("The evidence LLM response did not contain a facts array.")
    return value


def _validate_fact(item: object, segments: list[RawSegment]) -> StructuredFact | None:
    if not isinstance(item, dict):
        return None
    index = item.get("segment_index")
    statement = item.get("statement")
    quote = item.get("evidence_quote")
    if not isinstance(index, int) or not 0 <= index < len(segments):
        return None
    if not isinstance(statement, str) or not isinstance(quote, str):
        return None
    statement, quote = statement.strip(), quote.strip()
    if not statement or not quote or len(statement) > 1000:
        return None
    source = segments[index]
    if quote not in source.text:
        return None
    if not set(NUMBER_RE.findall(statement)).issubset(NUMBER_RE.findall(quote)):
        return None
    return StructuredFact(
        text=statement,
        evidence_quote=quote,
        locator=source.locator,
        validation_status="exact_match",
    )


def build_evidence_structurer(settings: Settings) -> EvidenceStructurer | None:
    provider = settings.evidence_llm_provider
    if provider in {"", "disabled", "none"}:
        return None
    import os

    if provider == "gemini":
        api_key = os.getenv("GEMINI_API_KEY", "").strip()
        if not api_key:
            raise EvidenceError("GEMINI_API_KEY is required when Gemini structuring is enabled.")
        return OpenAICompatibleStructurer(
            provider="gemini",
            model=settings.evidence_llm_model or "gemini-3.8-flash",
            api_key=api_key,
            base_url="https://generativelanguage.googleapis.com/v1beta/openai",
            timeout_seconds=settings.evidence_llm_timeout_seconds,
        )
    if provider == "groq":
        api_key = (settings.groq_api_key or os.getenv("GROQ_API_KEY", "")).strip()
        if not api_key:
            raise EvidenceError(
                "DRIFTZERO_GROQ_API_KEY is required when Groq structuring is enabled."
            )
        return OpenAICompatibleStructurer(
            provider="groq",
            model=settings.evidence_llm_model or "openai/gpt-oss-20b",
            api_key=api_key,
            base_url="https://api.groq.com/openai/v1",
            timeout_seconds=settings.evidence_llm_timeout_seconds,
        )
    raise EvidenceError("DRIFTZERO_EVIDENCE_LLM_PROVIDER must be disabled, gemini, or groq.")


class EvidenceService:
    def __init__(self, settings: Settings, structurer: EvidenceStructurer | None = None) -> None:
        self.settings = settings
        self.structurer = structurer

    @staticmethod
    def _tenant_id(session: Session) -> str:
        return str(session.info.get("tenant_id", DEFAULT_TENANT_ID))

    def import_source(
        self, session: Session, model_id: str, payload: EvidenceImportRequest
    ) -> EvidenceSourceResponse:
        model = session.scalar(
            select(MonitoredModel).where(
                MonitoredModel.id == model_id,
                MonitoredModel.tenant_id == self._tenant_id(session),
            )
        )
        if model is None:
            raise EvidenceNotFound("Model not found.")
        try:
            content = base64.b64decode(payload.content_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise EvidenceError("content_base64 is not valid base64.") from exc
        if len(content) > self.settings.evidence_max_file_bytes:
            limit_mb = self.settings.evidence_max_file_bytes / 1_048_576
            raise EvidenceError(f"File exceeds the {limit_mb:g} MB evidence limit.")

        digest = hashlib.sha256(content).hexdigest()
        duplicate = session.scalar(
            select(EvidenceSource).where(
                EvidenceSource.model_id == model_id,
                EvidenceSource.content_hash == digest,
            )
        )
        if duplicate is not None:
            raise EvidenceConflict(f"This file is already source {duplicate.id}.")

        suffix, raw_segments = parse_evidence_file(payload.filename, content)
        facts: list[StructuredFact]
        if payload.use_llm:
            if suffix not in UNSTRUCTURED_SUFFIXES:
                raise EvidenceError("AI structuring is only used for PDF, TXT, and Markdown files.")
            if self.structurer is None:
                raise EvidenceError(
                    "AI structuring is disabled. Configure Gemini or Groq on the API server."
                )
            llm_facts = self.structurer.structure(raw_segments)
            # Always retain every parser segment alongside the convenience
            # facts. An LLM can improve retrieval, but can never erase source
            # material by omitting it from a probabilistic response.
            facts = [
                StructuredFact(segment.text, segment.text, segment.locator, "deterministic")
                for segment in raw_segments
            ] + llm_facts
        else:
            facts = [
                StructuredFact(segment.text, segment.text, segment.locator, "deterministic")
                for segment in raw_segments
            ]

        media_type = payload.media_type or mimetypes.guess_type(payload.filename)[0]
        media_type = media_type or "application/octet-stream"
        source = EvidenceSource(
            tenant_id=self._tenant_id(session),
            model_id=model_id,
            name=payload.name or PurePath(payload.filename).stem,
            filename=PurePath(payload.filename).name,
            media_type=media_type,
            content_hash=digest,
            corpus_version=f"evidence-{digest[:12]}",
            status="awaiting_review",
            extraction_method="deterministic+llm" if payload.use_llm else "deterministic",
            llm_provider=self.structurer.provider if payload.use_llm and self.structurer else None,
            llm_model=self.structurer.model if payload.use_llm and self.structurer else None,
            chunk_count=len(facts),
        )
        session.add(source)
        session.flush()
        for ordinal, fact in enumerate(facts):
            session.add(
                EvidenceChunk(
                    source_id=source.id,
                    ordinal=ordinal,
                    text=fact.text,
                    evidence_quote=fact.evidence_quote,
                    locator=fact.locator,
                    content_hash=hashlib.sha256(fact.evidence_quote.encode()).hexdigest(),
                    validation_status=fact.validation_status,
                )
            )
        self._audit(
            session,
            model_id,
            payload.actor,
            "evidence.source_imported",
            source.id,
            {"filename": source.filename, "chunks": len(facts), "status": source.status},
        )
        session.commit()
        return self.get_source(session, source.id)

    def list_sources(self, session: Session, model_id: str) -> list[EvidenceSourceResponse]:
        records = session.scalars(
            select(EvidenceSource)
            .options(selectinload(EvidenceSource.chunks))
            .where(
                EvidenceSource.model_id == model_id,
                EvidenceSource.tenant_id == self._tenant_id(session),
            )
            .order_by(EvidenceSource.created_at.desc())
        ).all()
        return [EvidenceSourceResponse.model_validate(record) for record in records]

    def get_source(self, session: Session, source_id: str) -> EvidenceSourceResponse:
        record = session.scalar(
            select(EvidenceSource)
            .options(selectinload(EvidenceSource.chunks))
            .where(
                EvidenceSource.id == source_id,
                EvidenceSource.tenant_id == self._tenant_id(session),
            )
        )
        if record is None:
            raise EvidenceNotFound("Evidence source not found.")
        return EvidenceSourceResponse.model_validate(record)

    def review_source(
        self, session: Session, source_id: str, payload: EvidenceReviewRequest
    ) -> EvidenceSourceResponse:
        source = session.scalar(
            select(EvidenceSource).where(
                EvidenceSource.id == source_id,
                EvidenceSource.tenant_id == self._tenant_id(session),
            )
        )
        if source is None:
            raise EvidenceNotFound("Evidence source not found.")
        if source.status == "retired":
            raise EvidenceConflict("Retired evidence cannot be reactivated.")
        source.status = payload.status
        source.rejection_reason = payload.reason if payload.status == "rejected" else None
        if payload.status == "approved":
            source.approved_by = payload.actor
            source.approved_at = utc_now()
        else:
            source.approved_by = None
            source.approved_at = None
        self._audit(
            session,
            source.model_id,
            payload.actor,
            f"evidence.source_{payload.status}",
            source.id,
            {"status": payload.status, "reason": payload.reason},
        )
        session.commit()
        return self.get_source(session, source.id)

    def search(
        self, session: Session, model_id: str, payload: EvidenceSearchRequest
    ) -> list[EvidenceSearchHit]:
        query_tokens = set(TOKEN_RE.findall(payload.query.lower()))
        if not query_tokens:
            return []
        rows = session.execute(
            select(EvidenceChunk, EvidenceSource)
            .join(EvidenceSource, EvidenceSource.id == EvidenceChunk.source_id)
            .where(
                EvidenceSource.model_id == model_id,
                EvidenceSource.tenant_id == self._tenant_id(session),
                EvidenceSource.status == "approved",
            )
        ).all()
        ranked: list[tuple[float, EvidenceChunk, EvidenceSource]] = []
        query_lower = payload.query.casefold().strip()
        for chunk, source in rows:
            chunk_tokens = set(TOKEN_RE.findall(chunk.text.lower()))
            overlap = len(query_tokens & chunk_tokens) / len(query_tokens)
            phrase_bonus = 0.2 if query_lower in chunk.text.casefold() else 0.0
            score = min(1.0, overlap * 0.8 + phrase_bonus)
            if score > 0:
                ranked.append((score, chunk, source))
        ranked.sort(key=lambda item: (-item[0], item[1].ordinal))
        return [
            EvidenceSearchHit(
                chunk_id=chunk.id,
                source_id=source.id,
                source_name=source.name,
                filename=source.filename,
                corpus_version=source.corpus_version,
                text=chunk.text,
                evidence_quote=chunk.evidence_quote,
                locator=chunk.locator,
                relevance=round(score, 4),
            )
            for score, chunk, source in ranked[: payload.limit]
        ]

    def _audit(
        self,
        session: Session,
        model_id: str,
        actor: str,
        event_type: str,
        source_id: str,
        details: dict[str, object],
    ) -> None:
        session.add(
            AuditEvent(
                tenant_id=self._tenant_id(session),
                model_id=model_id,
                event_type=event_type,
                actor=actor,
                actor_type=ActorType.SYSTEM if actor == "system" else ActorType.HUMAN,
                entity_type="evidence_source",
                entity_id=source_id,
                reason=str(details.get("reason") or "") or None,
                details=details,
            )
        )
