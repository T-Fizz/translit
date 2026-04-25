"""Deterministic name-aware transliteration.

Currently:
    ja → latin (simplified Hepburn via pykakasi, with honorific detection)
    zh → latin (pinyin without tone marks via pypinyin)

Intentionally a small, import-only library — no I/O, no network, no caching
(callers layer those on top). See the top-level repo for a FastAPI service
that wraps this package with an HTTP contract, auth, and a Postgres cache.
"""
from .engine import detect_source_script, supported_pairs, transliterate

__all__ = ["detect_source_script", "supported_pairs", "transliterate"]
__version__ = "0.1.0"
