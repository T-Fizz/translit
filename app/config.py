"""Runtime settings sourced from environment variables.

Fly/Supabase creds come from secrets; see DESIGN.md §Deployment.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    supabase_url: str | None
    supabase_service_key: str | None
    bootstrap_api_keys: str | None
    log_level: str
    memo_max_entries: int

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            supabase_url=os.environ.get("SUPABASE_URL") or None,
            supabase_service_key=os.environ.get("SUPABASE_SERVICE_KEY") or None,
            bootstrap_api_keys=os.environ.get("BOOTSTRAP_API_KEYS") or None,
            log_level=os.environ.get("LOG_LEVEL", "INFO").upper(),
            memo_max_entries=int(os.environ.get("MEMO_MAX_ENTRIES", "50000")),
        )

    @property
    def has_db(self) -> bool:
        return bool(self.supabase_url and self.supabase_service_key)
