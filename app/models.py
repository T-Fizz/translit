"""Request / response models. Shapes match DESIGN.md §API contract exactly."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class TransliterateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=500)
    source_lang: str | None = Field(default=None, max_length=8)
    target_lang: str = Field(min_length=1, max_length=8)


class TransliterateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phonetic: str | None
    source_lang: str
    target_lang: str
    method: str | None
    cached: bool = False
    reason: str | None = None


class BatchRequest(BaseModel):
    entries: list[TransliterateRequest] = Field(min_length=1)


class BatchResult(BaseModel):
    """Lean per-entry result used inside /batch — DESIGN.md omits echoed
    source/target from batch entries (they're positional)."""
    phonetic: str | None
    method: str | None
    cached: bool = False
    reason: str | None = None


class BatchResponse(BaseModel):
    results: list[BatchResult]


class SupportedPair(BaseModel):
    source: str
    target: str
    method: str


class SupportedResponse(BaseModel):
    pairs: list[SupportedPair]


class HealthResponse(BaseModel):
    status: str = "ok"
