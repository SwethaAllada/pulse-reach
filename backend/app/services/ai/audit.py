"""AI generation audit trail.

Every generation request - including ones answered by the deterministic fallback - and every
human outreach review produces one record: feature, subject ids (synthetic), prompt version,
provider/model, outcome, guardrail violations, latency and SHA-256 digests of the exact input and
output (the texts themselves are not retained). Records go to the structured JSON log
(`pulsereach.ai.audit`) and to a store exposed by `GET /api/v1/ai/audit`:

- `AIAuditLog`: bounded in-process buffer (`DATA_SOURCE=memory`, demo mode; lost on restart);
- `PostgresAIAuditLog`: `synthetic.ai_audit_record` (`DATA_SOURCE=db`); records - and therefore
  draft ids - survive restarts and are shared by every worker.

Both allow at most one terminal review (`approved` / `rejected`) per draft.
"""

from __future__ import annotations

import hashlib
import logging
import threading
import uuid
from collections import deque
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.logging import request_id_var

logger = logging.getLogger("pulsereach.ai.audit")

TERMINAL_REVIEW_MODES = ("human_approved", "human_rejected")


def sha256(text: str | None) -> str | None:
    return hashlib.sha256(text.encode("utf-8")).hexdigest() if text is not None else None


class DuplicateReviewError(RuntimeError):
    """The draft already has a terminal (approved/rejected) review."""


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
    run_id: str | None = None

    @property
    def is_terminal_review(self) -> bool:
        return self.feature == "outreach_review" and self.generation_mode in TERMINAL_REVIEW_MODES


def _new_record(**kw: Any) -> AIAuditRecord:
    rec = AIAuditRecord(
        audit_id=uuid.uuid4().hex,
        recorded_at=datetime.now(timezone.utc),
        request_id=request_id_var.get(),
        **kw,
    )
    payload = asdict(rec)
    payload["recorded_at"] = rec.recorded_at.isoformat()
    logger.info("AI generation", extra={"ai_audit": payload})
    return rec


class AIAuditLog:
    """In-process store (memory mode). `session` is accepted for interface parity and ignored."""

    durable = False

    def __init__(self, maxlen: int = 500) -> None:
        self._records: deque[AIAuditRecord] = deque(maxlen=maxlen)
        self._lock = threading.Lock()

    def record(self, *, session: Session | None = None, **kw: Any) -> AIAuditRecord:
        with self._lock:
            draft_id = (kw.get("extra") or {}).get("draft_audit_id")
            if (
                kw.get("feature") == "outreach_review"
                and kw.get("generation_mode") in TERMINAL_REVIEW_MODES
                and any(r.is_terminal_review and r.extra.get("draft_audit_id") == draft_id for r in self._records)
            ):
                raise DuplicateReviewError(draft_id)
            rec = _new_record(**kw)
            self._records.append(rec)
        return rec

    def recent(
        self, limit: int = 50, feature: str | None = None, organization_id: str | None = None
    ) -> list[AIAuditRecord]:
        with self._lock:
            items = [
                r for r in self._records
                if (feature is None or r.feature == feature)
                and (organization_id is None or r.extra.get("organization_id") == organization_id)
            ]
        return list(reversed(items))[:limit]

    def get(self, audit_id: str) -> AIAuditRecord | None:
        with self._lock:
            return next((r for r in self._records if r.audit_id == audit_id), None)

    def last_provider_call(self) -> AIAuditRecord | None:
        return next((r for r in self.recent(limit=500) if r.provider is not None), None)

    def terminal_review(self, draft_audit_id: str) -> AIAuditRecord | None:
        with self._lock:
            return next(
                (r for r in self._records if r.is_terminal_review and r.extra.get("draft_audit_id") == draft_audit_id),
                None,
            )

    def clear(self) -> None:
        with self._lock:
            self._records.clear()


class PostgresAIAuditLog:
    """`synthetic.ai_audit_record` store (database mode).

    `record(session=...)` writes inside the caller's transaction (used so a review and its
    simulated follow-up event commit or roll back together); without a session it commits its own.
    """

    durable = True

    def __init__(self, engine_factory: Callable[[], Engine]) -> None:
        self._engine_factory = engine_factory

    @staticmethod
    def _row(rec: AIAuditRecord) -> Any:
        from app.models.synthetic import AIAuditRecord as Row

        if rec.run_id is None:
            raise ValueError("A durable AI audit record needs the synthetic run id.")
        extra = rec.extra or {}
        review = rec.feature == "outreach_review"
        return Row(
            audit_id=rec.audit_id,
            run_id=rec.run_id,
            is_synthetic=True,
            recorded_at=rec.recorded_at,
            request_id=rec.request_id,
            feature=rec.feature,
            patient_id=rec.subject.get("patient_id"),
            rule_id=rec.subject.get("rule_id"),
            care_gap_id=rec.subject.get("care_gap_id"),
            subject=rec.subject,
            prompt_version=rec.prompt_version,
            provider=rec.provider,
            model=rec.model,
            generation_mode=rec.generation_mode,
            fallback_reason=rec.fallback_reason,
            violations=list(rec.violations),
            input_sha256=rec.input_sha256,
            output_sha256=rec.output_sha256,
            latency_ms=rec.latency_ms,
            extra=extra,
            draft_audit_id=extra.get("draft_audit_id") if review else None,
            review_decision=rec.generation_mode.removeprefix("human_") if review else None,
            reviewed_by=extra.get("reviewed_by") if review else None,
            follow_up_id=extra.get("follow_up_id") if review else None,
            simulated_outreach_status=extra.get("simulated_outreach_status") if review else None,
        )

    @staticmethod
    def _from_row(row: Any) -> AIAuditRecord:
        return AIAuditRecord(
            audit_id=row.audit_id,
            recorded_at=row.recorded_at,
            request_id=row.request_id,
            feature=row.feature,
            subject=dict(row.subject or {}),
            prompt_version=row.prompt_version,
            provider=row.provider,
            model=row.model,
            generation_mode=row.generation_mode,
            fallback_reason=row.fallback_reason,
            violations=tuple(row.violations or ()),
            input_sha256=row.input_sha256,
            output_sha256=row.output_sha256,
            latency_ms=row.latency_ms,
            extra=dict(row.extra or {}),
            run_id=row.run_id,
        )

    def record(self, *, session: Session | None = None, **kw: Any) -> AIAuditRecord:
        rec = _new_record(**kw)
        row = self._row(rec)
        if session is not None:
            session.add(row)
            session.flush()  # surfaces a duplicate terminal review inside the caller's transaction
            return rec
        try:
            with Session(self._engine_factory()) as s, s.begin():
                s.add(row)
        except IntegrityError as exc:
            if rec.is_terminal_review:
                raise DuplicateReviewError(rec.extra.get("draft_audit_id")) from exc
            raise
        return rec

    def _query(self, stmt) -> list[AIAuditRecord]:
        with Session(self._engine_factory()) as s:
            return [self._from_row(r) for r in s.scalars(stmt).all()]

    def recent(
        self, limit: int = 50, feature: str | None = None, organization_id: str | None = None
    ) -> list[AIAuditRecord]:
        from app.models.synthetic import AIAuditRecord as Row

        stmt = select(Row).order_by(Row.recorded_at.desc(), Row.audit_id.desc()).limit(limit)
        if feature is not None:
            stmt = stmt.where(Row.feature == feature)
        if organization_id is not None:
            stmt = stmt.where(Row.extra["organization_id"].astext == organization_id)
        return self._query(stmt)

    def get(self, audit_id: str) -> AIAuditRecord | None:
        from app.models.synthetic import AIAuditRecord as Row

        found = self._query(select(Row).where(Row.audit_id == audit_id))
        return found[0] if found else None

    def last_provider_call(self) -> AIAuditRecord | None:
        from app.models.synthetic import AIAuditRecord as Row

        found = self._query(
            select(Row).where(Row.provider.is_not(None))
            .order_by(Row.recorded_at.desc(), Row.audit_id.desc()).limit(1)
        )
        return found[0] if found else None

    def terminal_review(self, draft_audit_id: str) -> AIAuditRecord | None:
        from app.models.synthetic import AIAuditRecord as Row

        found = self._query(
            select(Row).where(
                Row.draft_audit_id == draft_audit_id, Row.review_decision.in_(("approved", "rejected"))
            )
        )
        return found[0] if found else None
