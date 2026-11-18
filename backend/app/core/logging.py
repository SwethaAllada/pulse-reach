"""Structured JSON logging with request-ID correlation and PII redaction (`T-16`)."""

from __future__ import annotations

import json
import logging
import re
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

request_id_var: ContextVar[str | None] = ContextVar("pulsereach_request_id", default=None)

_EID_RE = re.compile(r"\b784[- ]?\d{4}[- ]?\d{7}[- ]?\d\b")
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_PHONE_RE = re.compile(r"(?<!\d)(?:(?:\+|00)971[- ]?5\d|05\d)[- ]?\d{3}[- ]?\d{4}(?!\d)")


def redact_pii(text: str) -> str:
    """Redact Emirates IDs, email addresses, and UAE phone numbers from log strings."""
    cleaned = _EID_RE.sub("[REDACTED_EID]", text)
    cleaned = _EMAIL_RE.sub("[REDACTED_EMAIL]", cleaned)
    cleaned = _PHONE_RE.sub("[REDACTED_PHONE]", cleaned)
    return cleaned


class JsonLogFormatter(logging.Formatter):
    """Emit single-line JSON log records with request_id and PII redaction."""

    _RESERVED = frozenset(
        {
            "name",
            "msg",
            "args",
            "levelname",
            "levelno",
            "pathname",
            "filename",
            "module",
            "exc_info",
            "exc_text",
            "stack_info",
            "lineno",
            "funcName",
            "created",
            "msecs",
            "relativeCreated",
            "thread",
            "threadName",
            "processName",
            "process",
            "message",
            "asctime",
        }
    )

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "request_id": getattr(record, "request_id", None) or request_id_var.get(),
            "message": redact_pii(record.getMessage()),
        }
        for key, value in record.__dict__.items():
            if key in self._RESERVED or key.startswith("_") or key in payload:
                continue
            payload[key] = redact_pii(value) if isinstance(value, str) else value
        if record.exc_info:
            payload["exception"] = redact_pii(self.formatException(record.exc_info))
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    """Configure root logger with `JsonLogFormatter` if not already configured."""
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    if not any(isinstance(h.formatter, JsonLogFormatter) for h in root.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(JsonLogFormatter())
        root.handlers = [handler]
