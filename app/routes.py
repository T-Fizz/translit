"""HTTP routes — all under /v1. Contracts pinned in DESIGN.md §API contract."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request

import translit_core as engine
from .auth import Tenant, require_tenant
from .cache import CacheEntry, TieredCache, cache_key
from .errors import PayloadTooLarge
from .models import (
    BatchRequest,
    BatchResponse,
    BatchResult,
    HealthResponse,
    SupportedPair,
    SupportedResponse,
    TransliterateRequest,
    TransliterateResponse,
)

log = logging.getLogger(__name__)

MAX_BATCH_ENTRIES = 100
MAX_BATCH_BODY_BYTES = 10 * 1024

router = APIRouter(prefix="/v1")


def _method_for(source_lang: str) -> str:
    if source_lang == "ja":
        return "pykakasi"
    if source_lang == "zh":
        return "pypinyin"
    return "unknown"


def _resolve_source(name: str, hint: str | None) -> tuple[str | None, str]:
    """Return (resolved_src_or_None_if_unsupported, detected_or_''_if_none)."""
    detected = engine.detect_source_script(name)
    if detected is None or detected == "latin":
        return None, detected or ""
    resolved = hint or detected
    if hint == "ja" and detected == "zh":
        resolved = "ja"
    elif hint == "zh" and detected == "ja":
        resolved = "zh"
    return resolved, detected


def _lookup(cache: TieredCache, req: TransliterateRequest) -> TransliterateResponse:
    resolved, detected = _resolve_source(req.name, req.source_lang)
    if resolved is None:
        return TransliterateResponse(
            phonetic=None,
            source_lang=detected,
            target_lang=req.target_lang,
            method=None,
            cached=False,
            reason="unsupported_pair",
        )

    key = cache_key(req.name, resolved, req.target_lang)
    hit = cache.get(key)
    if hit is not None:
        return TransliterateResponse(
            phonetic=hit.phonetic,
            source_lang=resolved,
            target_lang=req.target_lang,
            method=hit.method,
            cached=True,
        )

    phonetic = engine.transliterate(req.name, req.target_lang, source_lang=req.source_lang)
    if phonetic is None:
        return TransliterateResponse(
            phonetic=None,
            source_lang=resolved,
            target_lang=req.target_lang,
            method=None,
            cached=False,
            reason="unsupported_pair",
        )

    method = _method_for(resolved)
    cache.put(
        CacheEntry(
            hash=key,
            name=req.name,
            source_lang=resolved,
            target_lang=req.target_lang,
            phonetic=phonetic,
            method=method,
        )
    )
    return TransliterateResponse(
        phonetic=phonetic,
        source_lang=resolved,
        target_lang=req.target_lang,
        method=method,
        cached=False,
    )


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/supported", response_model=SupportedResponse)
def supported() -> SupportedResponse:
    return SupportedResponse(pairs=[SupportedPair(**p) for p in engine.supported_pairs()])


@router.post("/transliterate", response_model=TransliterateResponse)
def transliterate_one(
    request: Request,
    body: TransliterateRequest,
    _: Tenant = Depends(require_tenant),
) -> TransliterateResponse:
    cache: TieredCache = request.app.state.cache
    return _lookup(cache, body)


@router.post("/transliterate/batch", response_model=BatchResponse)
def transliterate_batch(
    request: Request,
    body: BatchRequest,
    _: Tenant = Depends(require_tenant),
) -> BatchResponse:
    if len(body.entries) > MAX_BATCH_ENTRIES:
        raise PayloadTooLarge(
            f"batch too large: {len(body.entries)} > {MAX_BATCH_ENTRIES}"
        )
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > MAX_BATCH_BODY_BYTES:
        raise PayloadTooLarge(
            f"batch body too large: {content_length} > {MAX_BATCH_BODY_BYTES}"
        )

    cache: TieredCache = request.app.state.cache
    out: list[BatchResult] = []
    for entry in body.entries:
        full = _lookup(cache, entry)
        out.append(
            BatchResult(
                phonetic=full.phonetic,
                method=full.method,
                cached=full.cached,
                reason=full.reason,
            )
        )
    return BatchResponse(results=out)
