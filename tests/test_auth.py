"""Unit tests for TenantStore (bootstrap + DB-backed + TTL cache)."""
from __future__ import annotations

import time

from app.auth import Tenant, TenantStore, hash_key


def test_hash_is_hex_64():
    h = hash_key("secret")
    assert len(h) == 64 and all(c in "0123456789abcdef" for c in h)


def test_bootstrap_tenant_wins():
    t = Tenant(id="bootstrap:internal", name="internal", tier="internal")
    store = TenantStore(bootstrap={hash_key("raw-key"): t})
    assert store.resolve("raw-key") is t


def test_unknown_key_returns_none():
    store = TenantStore()
    assert store.resolve("nothing") is None


def test_db_lookup_is_called_when_not_in_bootstrap():
    seen: list[str] = []
    t = Tenant(id="t-1", name="db-tenant", tier="internal")

    def db(h: str):
        seen.append(h)
        return t

    store = TenantStore(db_lookup=db)
    assert store.resolve("some-key") is t
    assert len(seen) == 1


def test_db_lookup_result_is_cached():
    calls = []

    def db(h: str):
        calls.append(h)
        return Tenant(id="t-1", name="x")

    store = TenantStore(db_lookup=db)
    store.resolve("k")
    store.resolve("k")
    store.resolve("k")
    assert len(calls) == 1


def test_db_lookup_none_is_also_cached():
    calls = []

    def db(h: str):
        calls.append(h)
        return None

    store = TenantStore(db_lookup=db)
    assert store.resolve("k") is None
    assert store.resolve("k") is None
    assert len(calls) == 1


def test_db_lookup_exception_is_swallowed():
    def db(h: str):
        raise RuntimeError("db down")

    store = TenantStore(db_lookup=db)
    assert store.resolve("k") is None
