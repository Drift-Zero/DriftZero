"""Safe connection validation and read-only discovery adapters."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from app.config import Settings


class ConnectionCheckError(Exception):
    """A connection could not be checked safely or successfully."""


class CredentialVault:
    """Encrypt connection credentials with an operator-supplied Fernet key."""

    def __init__(self, key: str | None) -> None:
        self._fernet = Fernet(key.encode()) if key else None

    @property
    def configured(self) -> bool:
        return self._fernet is not None

    def encrypt(self, value: str) -> str:
        if self._fernet is None:
            raise ConnectionCheckError(
                "DRIFTZERO_CONNECTION_SECRET_KEY must be configured before storing credentials."
            )
        return self._fernet.encrypt(value.encode()).decode()

    def decrypt(self, value: str | None) -> str | None:
        if not value:
            return None
        if self._fernet is None:
            raise ConnectionCheckError("The connection credential vault is unavailable.")
        try:
            return self._fernet.decrypt(value.encode()).decode()
        except InvalidToken as exc:
            raise ConnectionCheckError(
                "The stored connection credential cannot be decrypted."
            ) from exc


@dataclass(frozen=True, slots=True)
class CheckResult:
    status_code: int
    latency_ms: int
    metadata: dict[str, Any]


def _is_local_environment(settings: Settings) -> bool:
    return settings.environment.lower() in {"development", "test", "demo", "hackathon-demo"}


def validate_target_url(url: str, settings: Settings) -> urllib.parse.ParseResult:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ConnectionCheckError("Connection targets must be absolute HTTP(S) URLs.")
    if parsed.username or parsed.password:
        raise ConnectionCheckError("Credentials must not be embedded in connection URLs.")
    if parsed.scheme != "https" and not _is_local_environment(settings):
        raise ConnectionCheckError("Production connection targets must use HTTPS.")

    try:
        addresses = {
            item[4][0]
            for item in socket.getaddrinfo(
                parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM
            )
        }
    except socket.gaierror as exc:
        raise ConnectionCheckError("The connection hostname could not be resolved.") from exc

    for address in addresses:
        ip = ipaddress.ip_address(address)
        unsafe = (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        )
        if unsafe and not _is_local_environment(settings):
            raise ConnectionCheckError("Private or reserved network targets are not allowed.")
    return parsed


class ConnectionInspector:
    """Perform bounded, read-only checks for GitHub, websites, and APIs."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def check(self, connection: Any, credential: str | None) -> CheckResult:
        if connection.kind == "github":
            return self._check_github(connection, credential)
        if connection.kind in {"api", "website"}:
            return self._check_http(connection, credential)
        if connection.kind == "telemetry":
            return CheckResult(
                status_code=200,
                latency_ms=0,
                metadata={"ingestion_key_configured": bool(connection.ingest_key_hash)},
            )
        raise ConnectionCheckError(f"Unsupported connection kind '{connection.kind}'.")

    def _check_github(self, connection: Any, credential: str | None) -> CheckResult:
        repository = connection.repository or self._repository_from_url(connection.url)
        if not repository or repository.count("/") != 1:
            raise ConnectionCheckError("GitHub repository must use the owner/repository format.")
        api_url = f"https://api.github.com/repos/{repository}"
        repo, status_code, latency_ms = self._json_request(api_url, credential)
        branch = connection.branch or repo.get("default_branch")
        commit, _, commit_latency = self._json_request(
            f"{api_url}/commits/{urllib.parse.quote(str(branch), safe='')}", credential
        )
        tree_sha = commit.get("commit", {}).get("tree", {}).get("sha")
        tree_count = None
        tree_truncated = None
        manifest_hash = None
        detected_ai_files: list[str] = []
        if tree_sha:
            tree, _, tree_latency = self._json_request(
                f"{api_url}/git/trees/{tree_sha}?recursive=1", credential
            )
            entries = tree.get("tree", [])
            tree_count = len(entries)
            tree_truncated = bool(tree.get("truncated"))
            manifest = [
                {
                    "path": entry.get("path"),
                    "mode": entry.get("mode"),
                    "type": entry.get("type"),
                    "sha": entry.get("sha"),
                    "size": entry.get("size"),
                }
                for entry in entries
                if isinstance(entry, dict)
            ]
            manifest_hash = hashlib.sha256(
                json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            ai_markers = (
                "prompt",
                "agent",
                "eval",
                "openai",
                "anthropic",
                "gemini",
                "langchain",
                "llamaindex",
                "model",
            )
            detected_ai_files = [
                str(entry["path"])
                for entry in manifest
                if entry.get("type") == "blob"
                and any(marker in str(entry.get("path", "")).lower() for marker in ai_markers)
            ][:100]
            commit_latency += tree_latency
        metadata = {
            "repository": repository,
            "default_branch": repo.get("default_branch"),
            "private": bool(repo.get("private")),
            "archived": bool(repo.get("archived")),
            "language": repo.get("language"),
            "commit_sha": commit.get("sha"),
            "tree_sha": tree_sha,
            "tree_entries": tree_count,
            "tree_truncated": tree_truncated,
            "manifest_sha256": manifest_hash,
            "detected_ai_files": detected_ai_files,
            "pushed_at": repo.get("pushed_at"),
        }
        return CheckResult(status_code, latency_ms + commit_latency, metadata)

    def _check_http(self, connection: Any, credential: str | None) -> CheckResult:
        target = connection.api_endpoint if connection.kind == "api" else connection.url
        if not target:
            raise ConnectionCheckError("The connection has no target URL.")
        validate_target_url(target, self.settings)
        config = connection.config or {}
        method = str(config.get("method", "POST" if connection.kind == "api" else "GET")).upper()
        if method not in {"GET", "HEAD", "POST"}:
            raise ConnectionCheckError("Connection checks only support GET, HEAD, or POST.")
        body = None
        if method == "POST":
            body = json.dumps(config.get("sample_request", {})).encode()
        headers = {
            "Accept": "application/json, text/plain, text/html;q=0.8",
            "User-Agent": "DriftZero-Connection-Check/1.0",
        }
        if body is not None:
            headers["Content-Type"] = "application/json"
        if credential:
            if connection.auth_scheme == "x-api-key":
                headers["X-API-Key"] = credential
            else:
                headers["Authorization"] = f"Bearer {credential}"
        started = time.perf_counter()
        request = urllib.request.Request(target, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(
                request, timeout=self.settings.connection_check_timeout_seconds
            ) as response:
                payload = response.read(65_537)
                if len(payload) > 65_536:
                    raise ConnectionCheckError("Connection check response exceeded 64 KiB.")
                latency_ms = round((time.perf_counter() - started) * 1000)
                return CheckResult(
                    status_code=response.status,
                    latency_ms=latency_ms,
                    metadata={
                        "content_type": response.headers.get("Content-Type"),
                        "content_length": len(payload),
                        "body_sha256": hashlib.sha256(payload).hexdigest(),
                    },
                )
        except urllib.error.HTTPError as exc:
            raise ConnectionCheckError(f"Target returned HTTP {exc.code}.") from exc
        except urllib.error.URLError as exc:
            raise ConnectionCheckError(f"Target could not be reached: {exc.reason}.") from exc

    def _json_request(self, url: str, credential: str | None) -> tuple[dict[str, Any], int, int]:
        validate_target_url(url, self.settings)
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "DriftZero/1.0"}
        if credential:
            headers["Authorization"] = f"Bearer {credential}"
        started = time.perf_counter()
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(
                request, timeout=self.settings.connection_check_timeout_seconds
            ) as response:
                payload = response.read(10_485_761)
                if len(payload) > 10_485_760:
                    raise ConnectionCheckError("GitHub response exceeded 10 MiB.")
                parsed = json.loads(payload)
                if not isinstance(parsed, dict):
                    raise ConnectionCheckError("GitHub returned an unexpected response.")
                return parsed, response.status, round((time.perf_counter() - started) * 1000)
        except urllib.error.HTTPError as exc:
            raise ConnectionCheckError(f"GitHub returned HTTP {exc.code}.") from exc
        except (urllib.error.URLError, json.JSONDecodeError) as exc:
            raise ConnectionCheckError("GitHub repository discovery failed.") from exc

    @staticmethod
    def _repository_from_url(url: str | None) -> str | None:
        if not url:
            return None
        parsed = urllib.parse.urlparse(url)
        if parsed.hostname not in {"github.com", "www.github.com"}:
            return None
        return parsed.path.strip("/").removesuffix(".git")
