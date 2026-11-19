"""AI generation audit trail.

Every generation request - including ones answered by the deterministic fallback - produces one
record: feature, subject ids (synthetic), prompt version, provider/model, outcome, guardrail
violations, latency and SHA-256 digests of the exact input and output (the texts themselves
are not retained). Records go to the structured JSON log (`pulsereach.ai.audit`) and to a
bounded in-process buffer exposed by `GET /api/v1/ai/audit`.
"""

from __future__ import annotations

import hashlib
import logging
import threading
import uuid
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.core.logging import request_id_var

logger = logging.getLogger("pulsereach.ai.audit")


def sha256(text: str | None) -> str | None:
    return hashlib.sha256(text.encode("utf-8")).hexdigest() if text is not None else None


@dataclass(frozen=True)
class AIAuditRecord:
    audit_id: str
    recorded_at: datetime
    request_id: str | None
    feature: str
    subject: dict[str, Any]
    prompt_version: str
    provider: str | None
    model: str | None
    generation_mode: str
    fallback_reason: str | None
    violations: tuple[str, ...]
    input_sha256: str | None
    output_sha256: str | None
    latency_ms: float | None
    extra: dict[str, Any] = field(default_factory=dict)


class AIAuditLog:
    def __init__(self, maxlen: int = 500) -> None:
        self._records: deque[AIAuditRecord] = deque(maxlen=maxlen)
        self._lock = threading.Lock()

    def record(self, **kw: Any) -> AIAuditRecord:
        rec = AIAuditRecord(
            audit_id=uuid.uuid4().hex,
            recorded_at=datetime.now(timezone.utc),
            request_id=request_id_var.get(),
            **kw,
        )
        with self._lock:
            self._records.append(rec)
        payload = asdict(rec)
        payload["recorded_at"] = rec.recorded_at.isoformat()
        logger.info("AI generation", extra={"ai_audit": payload})
        return rec

    def recent(self, limit: int = 50, feature: str | None = None) -> list[AIAuditRecord]:
        with self._lock:
            items = [r for r in self._records if feature is None or r.feature == feature]
        return list(reversed(items))[:limit]

    def clear(self) -> None:
        with self._lock:
            self._records.clear()
