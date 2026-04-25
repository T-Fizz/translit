"""Three-layer transliteration cache.

Layer 1: process-local bounded LRU (hot keys, <1μs)
Layer 2: Supabase/Postgres shared cache (tenant-agnostic, 5–20ms)
Layer 3: miss — caller computes via translit_core

Cache is tenant-agnostic per TENETS.md §3 (cache-as-moat) and §5 (no PII).

Writes to L2 are best-effort: exceptions are logged and swallowed so a
DB blip never fails a hot-path lookup. Stale data is impossible because
rows are keyed by `sha256(name|source|target)` — idempotent upserts.
"""
from __future__ import annotations

import hashlib
import logging
import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Optional, Protocol

log = logging.getLogger(__name__)


def cache_key(name: str, source_lang: str, target_lang: str) -> str:
    raw = f"{name}|{source_lang}|{target_lang}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


@dataclass(frozen=True)
class CacheEntry:
    hash: str
    name: str
    source_lang: str
    target_lang: str
    phonetic: str
    method: str


class CacheStore(Protocol):
    def get(self, hash_key: str) -> Optional[CacheEntry]: ...
    def put(self, entry: CacheEntry) -> None: ...


class InMemoryCache:
    """Bounded-LRU in-memory cache. Thread-safe.

    Doubles as L1 always and as L2 when no DB is configured (dev / tests).
    """

    def __init__(self, max_entries: int = 50000):
        self._max = max_entries
        self._store: OrderedDict[str, CacheEntry] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, hash_key: str) -> Optional[CacheEntry]:
        with self._lock:
            entry = self._store.get(hash_key)
            if entry is not None:
                self._store.move_to_end(hash_key)
            return entry

    def put(self, entry: CacheEntry) -> None:
        with self._lock:
            self._store[entry.hash] = entry
            self._store.move_to_end(entry.hash)
            while len(self._store) > self._max:
                self._store.popitem(last=False)

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)


class SupabaseCache:
    """Postgres-backed cache via Supabase PostgREST.

    The `supabase` client is imported lazily so unit tests don't require
    network access or credentials.
    """

    TABLE = "transliteration_cache"

    def __init__(self, url: str, service_key: str):
        from supabase import create_client  # lazy

        self._client = create_client(url, service_key)

    def get(self, hash_key: str) -> Optional[CacheEntry]:
        try:
            res = (
                self._client.table(self.TABLE)
                .select("*")
                .eq("hash", hash_key)
                .limit(1)
                .execute()
            )
        except Exception as exc:
            log.warning("cache get failed", extra={"hash": hash_key, "err": str(exc)})
            return None
        rows = res.data or []
        if not rows:
            return None
        r = rows[0]
        return CacheEntry(
            hash=r["hash"],
            name=r["name"],
            source_lang=r["source_lang"],
            target_lang=r["target_lang"],
            phonetic=r["phonetic"],
            method=r["method"],
        )

    def put(self, entry: CacheEntry) -> None:
        try:
            (
                self._client.table(self.TABLE)
                .upsert(
                    {
                        "hash": entry.hash,
                        "name": entry.name,
                        "source_lang": entry.source_lang,
                        "target_lang": entry.target_lang,
                        "phonetic": entry.phonetic,
                        "method": entry.method,
                    },
                    on_conflict="hash",
                )
                .execute()
            )
        except Exception as exc:
            log.warning("cache put failed", extra={"hash": entry.hash, "err": str(exc)})


class TieredCache:
    """L1 in-mem → L2 (optional) → miss."""

    def __init__(self, l1: InMemoryCache, l2: Optional[CacheStore] = None):
        self.l1 = l1
        self.l2 = l2

    def get(self, hash_key: str) -> Optional[CacheEntry]:
        entry = self.l1.get(hash_key)
        if entry is not None:
            return entry
        if self.l2 is None:
            return None
        entry = self.l2.get(hash_key)
        if entry is not None:
            self.l1.put(entry)
        return entry

    def put(self, entry: CacheEntry) -> None:
        self.l1.put(entry)
        if self.l2 is not None:
            self.l2.put(entry)
