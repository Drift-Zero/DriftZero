"""Small tenant-safe TTL cache for non-sensitive dashboard projections."""

from __future__ import annotations

import copy
import time
from threading import Lock
from typing import Any

_SAFE_NAMESPACES = frozenset({"health_timeline", "repository_metadata", "dashboard"})


class TenantTTLCache:
    """Cache public projections with tenant names in every key.

    Secrets and authentication material cannot be inserted because callers must
    use an explicitly allowed non-sensitive namespace.
    """

    def __init__(self, ttl_seconds: int, *, max_entries: int = 2_000) -> None:
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self._entries: dict[tuple[str, str, str], tuple[float, Any]] = {}
        self._lock = Lock()

    def get(self, tenant_id: str, namespace: str, key: str) -> Any | None:
        self._validate_namespace(namespace)
        if self.ttl_seconds <= 0:
            return None
        cache_key = (tenant_id, namespace, key)
        now = time.monotonic()
        with self._lock:
            entry = self._entries.get(cache_key)
            if entry is None:
                return None
            expires_at, value = entry
            if expires_at <= now:
                self._entries.pop(cache_key, None)
                return None
            return copy.deepcopy(value)

    def set(self, tenant_id: str, namespace: str, key: str, value: Any) -> None:
        self._validate_namespace(namespace)
        if self.ttl_seconds <= 0:
            return
        now = time.monotonic()
        with self._lock:
            if len(self._entries) >= self.max_entries:
                self._entries = {
                    item_key: item
                    for item_key, item in self._entries.items()
                    if item[0] > now
                }
                if len(self._entries) >= self.max_entries:
                    oldest = min(self._entries, key=lambda item_key: self._entries[item_key][0])
                    self._entries.pop(oldest, None)
            self._entries[(tenant_id, namespace, key)] = (
                now + self.ttl_seconds,
                copy.deepcopy(value),
            )

    def invalidate(
        self, tenant_id: str, namespace: str | None = None, key: str | None = None
    ) -> None:
        if namespace is not None:
            self._validate_namespace(namespace)
        with self._lock:
            self._entries = {
                cache_key: value
                for cache_key, value in self._entries.items()
                if not (
                    cache_key[0] == tenant_id
                    and (namespace is None or cache_key[1] == namespace)
                    and (key is None or cache_key[2] == key)
                )
            }

    @staticmethod
    def _validate_namespace(namespace: str) -> None:
        if namespace not in _SAFE_NAMESPACES:
            raise ValueError(f"Sensitive or unknown cache namespace: {namespace}")
