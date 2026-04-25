"""Structured JSON logging with a request_id context var.

Per TENETS and DESIGN: every log line carries `request_id`; APM is deferred
until revenue justifies it.
"""
from __future__ import annotations

import contextvars
import json
import logging
import sys
import time
import uuid

_STD_FIELDS = {
    "args", "asctime", "created", "exc_info", "exc_text", "filename",
    "funcName", "levelname", "levelno", "lineno", "module", "msecs",
    "message", "msg", "name", "pathname", "process", "processName",
    "relativeCreated", "stack_info", "thread", "threadName", "taskName",
}

_request_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)


def generate_request_id() -> str:
    return "req_" + uuid.uuid4().hex[:24]


def set_request_id(rid: str) -> None:
    _request_id.set(rid)


def get_request_id() -> str | None:
    return _request_id.get()


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "ts": round(time.time() * 1000),
            "level": record.levelname,
            "msg": record.getMessage(),
            "logger": record.name,
        }
        rid = _request_id.get()
        if rid:
            payload["request_id"] = rid
        for k, v in record.__dict__.items():
            if k in _STD_FIELDS or k == "request_id":
                continue
            try:
                json.dumps(v)
                payload[k] = v
            except TypeError:
                payload[k] = repr(v)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure(level: str = "INFO") -> None:
    root = logging.getLogger()
    root.setLevel(level)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.handlers = [handler]
