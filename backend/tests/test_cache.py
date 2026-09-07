"""Tenant cache keys must never cross customer boundaries."""

import pytest

from app.cache import TenantTTLCache


def test_cache_namespaces_tenants_copies_values_and_invalidates() -> None:
    cache = TenantTTLCache(30)
    original = {"score": 91, "points": [1, 2]}
    cache.set("tenant-a", "dashboard", "overview", original)
    cache.set("tenant-b", "dashboard", "overview", {"score": 44})

    first = cache.get("tenant-a", "dashboard", "overview")
    assert first == original
    first["points"].append(3)
    assert cache.get("tenant-a", "dashboard", "overview") == original
    assert cache.get("tenant-b", "dashboard", "overview") == {"score": 44}

    cache.invalidate("tenant-a")
    assert cache.get("tenant-a", "dashboard", "overview") is None
    assert cache.get("tenant-b", "dashboard", "overview") == {"score": 44}


def test_cache_refuses_secret_namespaces() -> None:
    cache = TenantTTLCache(30)

    with pytest.raises(ValueError, match="Sensitive or unknown"):
        cache.set("tenant-a", "api_keys", "provider", "secret")
