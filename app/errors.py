"""Typed errors mapped to the machine-readable envelope in DESIGN.md."""
from __future__ import annotations


class ApiError(Exception):
    code: str = "internal"
    status_code: int = 500

    def __init__(self, message: str = "", *, retry_after: int | None = None) -> None:
        super().__init__(message or self.code)
        self.message = message or self.code
        self.retry_after = retry_after


class InvalidRequest(ApiError):
    code = "invalid_request"
    status_code = 400


class Unauthorized(ApiError):
    code = "unauthorized"
    status_code = 401


class PayloadTooLarge(ApiError):
    code = "payload_too_large"
    status_code = 413


class RateLimited(ApiError):
    code = "rate_limited"
    status_code = 429
