"""Scheduled website-to-JSON evidence refreshes with optional xAI structuring."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.connections import ConnectionCheckError, validate_target_url
from app.db import DEFAULT_TENANT_ID, ModelConnection, utc_now
from app.evidence import EvidenceService
from app.schemas import EvidenceImportRequest


class WebsiteSyncError(ValueError):
    """A safe website refresh error suitable for an operator."""


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Apply the target policy again before following an HTTP redirect."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        super().__init__()

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: object,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> urllib.request.Request | None:
        try:
            validate_target_url(newurl, self.settings)
        except ConnectionCheckError as exc:
            raise WebsiteSyncError("The website redirected to an unsafe target.") from exc
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class _ReadableHTML(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.title = ""
        self._in_title = False
        self._ignored = 0
        self._parts: list[str] = []
        self.links: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "svg", "template"}:
            self._ignored += 1
        if tag == "title":
            self._in_title = True
        if tag == "a":
            href = dict(attrs).get("href")
            if href and not href.startswith(("javascript:", "mailto:", "tel:")):
                self.links.append({"url": urljoin(self.base_url, href), "description": ""})

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg", "template"} and self._ignored:
            self._ignored -= 1
        if tag == "title":
            self._in_title = False
        if tag in {"p", "li", "h1", "h2", "h3", "h4", "tr", "br"}:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._ignored:
            return
        cleaned = re.sub(r"\s+", " ", data).strip()
        if not cleaned:
            return
        if self._in_title:
            self.title = f"{self.title} {cleaned}".strip()
        self._parts.append(cleaned)

    @property
    def text(self) -> str:
        return re.sub(r"\n{3,}", "\n\n", " ".join(self._parts)).strip()


@dataclass(frozen=True, slots=True)
class FetchedPage:
    url: str
    title: str
    text: str
    links: list[dict[str, str]]
    status_code: int
    latency_ms: int
    content_hash: str


@dataclass(frozen=True, slots=True)
class WebsiteRefreshResult:
    connection_id: str
    status: str
    source_id: str | None
    fetched_at: datetime
    content_hash: str
    fact_count: int
    message: str


def fetch_website(url: str, settings: Settings) -> FetchedPage:
    try:
        validate_target_url(url, settings)
    except ConnectionCheckError as exc:
        raise WebsiteSyncError(str(exc)) from exc
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "text/html,application/xhtml+xml,text/plain;q=0.8",
            "User-Agent": "DriftZero-Website-Monitor/1.0",
        },
    )
    started = time.perf_counter()
    opener = urllib.request.build_opener(_SafeRedirectHandler(settings))
    try:
        with opener.open(
            request,
            timeout=settings.website_fetch_timeout_seconds,
        ) as response:
            content_type = response.headers.get_content_type()
            if content_type not in {"text/html", "application/xhtml+xml", "text/plain"}:
                raise WebsiteSyncError(f"Unsupported website content type: {content_type}.")
            raw = response.read(settings.website_max_response_bytes + 1)
            status_code = response.status
            charset = response.headers.get_content_charset() or "utf-8"
    except WebsiteSyncError:
        raise
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
        raise WebsiteSyncError("The website could not be fetched.") from exc
    if len(raw) > settings.website_max_response_bytes:
        raise WebsiteSyncError("The website response exceeded the configured size limit.")
    try:
        html = raw.decode(charset, errors="replace")
    except LookupError as exc:
        raise WebsiteSyncError("The website declared an unsupported character encoding.") from exc
    parser = _ReadableHTML(url)
    parser.feed(html)
    text = parser.text
    if not text:
        raise WebsiteSyncError("The website contained no readable text.")
    return FetchedPage(
        url=url,
        title=parser.title or urlparse(url).hostname or "Website",
        text=text,
        links=parser.links[:100],
        status_code=status_code,
        latency_ms=max(1, round((time.perf_counter() - started) * 1000)),
        content_hash=hashlib.sha256(text.encode()).hexdigest(),
    )


class XaiWebsiteStructurer:
    """Convert readable page text to strict JSON while retaining exact quotes."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def structure(self, page: FetchedPage) -> dict[str, object]:
        if not self.settings.xai_api_key:
            raise WebsiteSyncError("XAI_API_KEY is required for Grok website structuring.")
        schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "summary": {"type": "string"},
                "facts": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "name": {"type": "string"},
                            "value": {"type": "string"},
                            "evidence_quote": {"type": "string"},
                        },
                        "required": ["name", "value", "evidence_quote"],
                    },
                },
            },
            "required": ["summary", "facts"],
        }
        body = {
            "model": self.settings.xai_model,
            "temperature": 0,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Extract testable facts from website text. Every value and evidence_quote "
                        "must be copied exactly from the supplied text. Do not infer missing facts."
                    ),
                },
                {"role": "user", "content": page.text[: self.settings.website_llm_text_chars]},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "website_data", "strict": True, "schema": schema},
            },
        }
        request = urllib.request.Request(
            f"{self.settings.xai_base_url.rstrip('/')}/chat/completions",
            data=json.dumps(body).encode(),
            headers={
                "Authorization": f"Bearer {self.settings.xai_api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=self.settings.website_llm_timeout_seconds,
            ) as response:
                payload = json.loads(response.read(settings_limit(self.settings)))
            result = json.loads(payload["choices"][0]["message"]["content"])
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
            raise WebsiteSyncError("xAI could not structure the website.") from exc
        except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
            raise WebsiteSyncError("xAI returned an invalid structured response.") from exc
        facts = []
        for item in result.get("facts", []):
            if not isinstance(item, dict):
                continue
            keys = ("name", "value", "evidence_quote")
            name, value, quote = (str(item.get(key, "")).strip() for key in keys)
            exact = quote in page.text and value.casefold() in quote.casefold()
            if name and value and quote and exact:
                facts.append({"name": name, "value": value, "evidence_quote": quote})
        if not facts:
            raise WebsiteSyncError("xAI returned no source-verifiable facts.")
        return {
            "metadata": {
                "title": page.title,
                "source_url": page.url,
                "content_hash": page.content_hash,
                "summary": str(result.get("summary", "")),
            },
            "facts": facts,
        }


def settings_limit(settings: Settings) -> int:
    return min(settings.website_max_response_bytes, 1_048_576)


class WebsiteSyncService:
    def __init__(self, settings: Settings, evidence_service: EvidenceService) -> None:
        self.settings = settings
        self.evidence_service = evidence_service

    def refresh(
        self,
        session: Session,
        connection_id: str,
        *,
        actor: str = "website-worker",
    ) -> WebsiteRefreshResult:
        connection = session.scalar(
            select(ModelConnection).where(
                ModelConnection.id == connection_id,
                ModelConnection.tenant_id
                == str(session.info.get("tenant_id", DEFAULT_TENANT_ID)),
            )
        )
        if connection is None or connection.kind != "website":
            raise WebsiteSyncError("Website connection not found.")
        if connection.status == "paused":
            raise WebsiteSyncError("Website connection is paused.")
        fetched_at = utc_now()
        try:
            page = fetch_website(str(connection.url), self.settings)
            previous_hash = str((connection.discovered_metadata or {}).get("content_hash", ""))
            if page.content_hash == previous_hash:
                self._update_connection(connection, page, fetched_at, status="connected")
                session.commit()
                return WebsiteRefreshResult(
                    connection.id,
                    "unchanged",
                    None,
                    fetched_at,
                    page.content_hash,
                    0,
                    "Website content has not changed.",
                )
            use_xai = bool((connection.config or {}).get("use_xai", True))
            if use_xai:
                data = XaiWebsiteStructurer(self.settings).structure(page)
            else:
                lines = [
                    line.strip()
                    for line in page.text.splitlines()
                    if len(line.strip()) >= 8
                ][:100]
                data = {
                    "metadata": {
                        "title": page.title,
                        "source_url": page.url,
                        "content_hash": page.content_hash,
                    },
                    "facts": [
                        {
                            "name": f"Website statement {index}",
                            "value": line,
                            "evidence_quote": line,
                        }
                        for index, line in enumerate(lines, start=1)
                    ],
                }
            encoded = base64.b64encode(json.dumps(data, ensure_ascii=False).encode()).decode()
            hostname = urlparse(page.url).hostname or "website"
            source = self.evidence_service.import_source(
                session,
                connection.model_id,
                EvidenceImportRequest(
                    filename=f"website-{hostname}.json",
                    name=f"Website · {connection.name}",
                    media_type="application/json",
                    content_base64=encoded,
                    actor=actor,
                ),
            )
            auto_approve = bool((connection.config or {}).get("auto_approve", False))
            if auto_approve:
                from app.schemas import EvidenceReviewRequest

                source = self.evidence_service.review_source(
                    session,
                    source.id,
                    EvidenceReviewRequest(status="approved", actor=actor),
                )
            self._update_connection(
                connection,
                page,
                fetched_at,
                status="connected",
                source_id=source.id,
            )
            session.commit()
            return WebsiteRefreshResult(
                connection.id,
                "updated",
                source.id,
                fetched_at,
                page.content_hash,
                len(data.get("facts", [])),
                (
                    "Website evidence was refreshed and approved."
                    if auto_approve
                    else "A new reviewable website evidence version was created."
                ),
            )
        except WebsiteSyncError as exc:
            self._record_failure(session, connection, fetched_at, str(exc))
            raise
        except Exception as exc:
            # A parser, persistence, or provider integration failure must not
            # leave the operator staring at "Waiting for first refresh". Roll
            # back any failed transaction, reload the connection, and persist
            # a safe status before presenting one consistent public error.
            session.rollback()
            connection = session.scalar(
                select(ModelConnection).where(
                    ModelConnection.id == connection_id,
                    ModelConnection.tenant_id
                    == str(session.info.get("tenant_id", DEFAULT_TENANT_ID)),
                )
            )
            if connection is not None:
                self._record_failure(
                    session,
                    connection,
                    fetched_at,
                    "Website refresh failed unexpectedly.",
                )
            raise WebsiteSyncError("Website refresh failed unexpectedly.") from exc

    @staticmethod
    def _record_failure(
        session: Session,
        connection: ModelConnection,
        fetched_at: datetime,
        message: str,
    ) -> None:
        connection.status = "error"
        connection.last_error = message
        connection.last_checked_at = fetched_at
        session.commit()

    @staticmethod
    def _update_connection(
        connection: ModelConnection,
        page: FetchedPage,
        fetched_at: datetime,
        *,
        status: str,
        source_id: str | None = None,
    ) -> None:
        metadata = dict(connection.discovered_metadata or {})
        metadata.update({
            "content_hash": page.content_hash,
            "last_synced_at": fetched_at.isoformat(),
            "title": page.title,
            "source_id": source_id or metadata.get("source_id"),
        })
        connection.discovered_metadata = metadata
        connection.status = status
        connection.last_status_code = page.status_code
        connection.last_latency_ms = page.latency_ms
        connection.last_error = None
        connection.last_checked_at = fetched_at


def connection_is_due(connection: ModelConnection, now: datetime) -> bool:
    interval = max(1, int((connection.config or {}).get("refresh_interval_minutes", 10)))
    raw = (connection.discovered_metadata or {}).get("last_synced_at")
    if not raw and connection.last_checked_at is not None:
        raw = connection.last_checked_at.isoformat()
    if not raw:
        return True
    try:
        previous = datetime.fromisoformat(str(raw))
        if previous.tzinfo is None:
            previous = previous.replace(tzinfo=UTC)
    except ValueError:
        return True
    return now >= previous + timedelta(minutes=interval)
