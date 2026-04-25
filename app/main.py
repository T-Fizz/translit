"""FastAPI app factory + module-level `app` for uvicorn."""
from __future__ import annotations

import logging
import time

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from . import logs
from .auth import Tenant, TenantStore, hash_key
from .cache import InMemoryCache, SupabaseCache, TieredCache
from .config import Settings
from .errors import ApiError
from .routes import router


def _build_bootstrap_tenants(raw: str | None) -> dict[str, Tenant]:
    """Parse BOOTSTRAP_API_KEYS into a {hash: Tenant} map.

    Format: comma-separated entries; each entry is `key[:tenant_name]`.
    """
    if not raw:
        return {}
    out: dict[str, Tenant] = {}
    for i, entry in enumerate(raw.split(",")):
        entry = entry.strip()
        if not entry:
            continue
        if ":" in entry:
            key, name = entry.split(":", 1)
        else:
            key, name = entry, f"bootstrap-{i}"
        out[hash_key(key)] = Tenant(id=f"bootstrap:{name}", name=name, tier="internal")
    return out


def _build_cache(settings: Settings) -> TieredCache:
    l1 = InMemoryCache(max_entries=settings.memo_max_entries)
    l2 = None
    if settings.has_db:
        try:
            l2 = SupabaseCache(settings.supabase_url, settings.supabase_service_key)  # type: ignore[arg-type]
        except Exception:
            logging.getLogger(__name__).exception("supabase init failed — continuing without L2")
    return TieredCache(l1=l1, l2=l2)


def _error_body(code: str, message: str, request_id: str | None) -> dict:
    return {"error": {"code": code, "message": message, "request_id": request_id}}


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    logs.configure(settings.log_level)
    log = logging.getLogger(__name__)

    app = FastAPI(title="translit", version="1.0.0", docs_url=None, redoc_url=None)
    app.state.cache = _build_cache(settings)
    app.state.tenants = TenantStore(
        bootstrap=_build_bootstrap_tenants(settings.bootstrap_api_keys)
    )

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        rid = request.headers.get("x-request-id") or logs.generate_request_id()
        logs.set_request_id(rid)
        request.state.request_id = rid
        started = time.monotonic()
        try:
            response = await call_next(request)
        finally:
            dur_ms = round((time.monotonic() - started) * 1000, 2)
            log.info(
                "request",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "latency_ms": dur_ms,
                },
            )
        response.headers["x-request-id"] = rid
        return response

    @app.exception_handler(ApiError)
    async def api_error_handler(request: Request, exc: ApiError):
        rid = getattr(request.state, "request_id", None) or logs.get_request_id()
        headers = {"x-request-id": rid} if rid else {}
        if exc.retry_after is not None:
            headers["Retry-After"] = str(exc.retry_after)
        return JSONResponse(
            _error_body(exc.code, exc.message, rid),
            status_code=exc.status_code,
            headers=headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        rid = getattr(request.state, "request_id", None) or logs.get_request_id()
        headers = {"x-request-id": rid} if rid else {}
        return JSONResponse(
            _error_body("invalid_request", "invalid request body", rid),
            status_code=400,
            headers=headers,
        )

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception):
        rid = getattr(request.state, "request_id", None) or logs.get_request_id()
        log.exception("unhandled error")
        headers = {"x-request-id": rid} if rid else {}
        return JSONResponse(
            _error_body("internal", "internal error", rid),
            status_code=500,
            headers=headers,
        )

    app.include_router(router)
    return app


app = create_app()
