"""API-key auth with TTL-cached tenant resolution.

Per DESIGN.md §Auth model:
  - Keys stored as sha256 hashes (never plaintext).
  - In-memory cache refreshed every 60s.
  - No OAuth, no JWT — developer-tool product.

For v1 we also accept a BOOTSTRAP_API_KEYS env var so the service runs
without a DB (internal tier only).
"""
from __future__ import annotations

import hashlib
import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

from fastapi import Header, Request

from .errors import Unauthorized

log = logging.getLogger(__name__)

TTL_SECONDS = 60


def hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Tenant:
    id: str
    name: str
    tier: str = "internal"


class TenantStore:
    """Combines bootstrap (env) and DB-backed (future) tenant lookup, with
    a TTL cache on DB hits and misses alike."""

    def __init__(
        self,
        bootstrap: dict[str, Tenant] | None = None,
        db_lookup: Optional[Callable[[str], Optional[Tenant]]] = None,
    ) -> None:
        self._bootstrap = dict(bootstrap or {})
        self._db_lookup = db_lookup
        self._lock = threading.Lock()
        self._cache: dict[str, tuple[float, Optional[Tenant]]] = {}

    def resolve(self, raw_key: str) -> Optional[Tenant]:
        h = hash_key(raw_key)
        if h in self._bootstrap:
            return self._bootstrap[h]
        now = time.monotonic()
        with self._lock:
            cached = self._cache.get(h)
            if cached and (now - cached[0]) < TTL_SECONDS:
                return cached[1]
        tenant: Optional[Tenant] = None
        if self._db_lookup is not None:
            try:
                tenant = self._db_lookup(h)
            except Exception as exc:
                log.warning("tenant lookup failed", extra={"err": str(exc)})
        with self._lock:
            self._cache[h] = (time.monotonic(), tenant)
        return tenant


def require_tenant(
    request: Request,
    x_api_key: Optional[str] = Header(default=None, alias="x-api-key"),
) -> Tenant:
    if not x_api_key:
        raise Unauthorized("missing x-api-key header")
    store: TenantStore | None = getattr(request.app.state, "tenants", None)
    if store is None:
        raise Unauthorized("auth not configured")
    tenant = store.resolve(x_api_key)
    if tenant is None:
        raise Unauthorized("invalid or revoked api key")
    return tenant
