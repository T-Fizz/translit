"""Shared fixtures for HTTP integration tests."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def api_key() -> str:
    return "test-key-abc"


@pytest.fixture
def settings(api_key: str) -> Settings:
    """No DB configured: L2 is absent, L1 (in-mem) handles all caching."""
    return Settings(
        supabase_url=None,
        supabase_service_key=None,
        bootstrap_api_keys=f"{api_key}:test-tenant",
        log_level="WARNING",
        memo_max_entries=1000,
    )


@pytest.fixture
def client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings=settings))


@pytest.fixture
def auth_headers(api_key: str) -> dict[str, str]:
    return {"x-api-key": api_key}
