"""Security and workflow audit events (`identity.audit_event`, append-only).

The actor is always taken from the authenticated `Principal` (never from request bodies). Events
are written in their own short transaction after the operation (or the denial) and mirrored to the
JSON log (`pulsereach.audit`). Details hold identifiers and outcome metadata only — no free text,
no clinical values, no tokens or passwords.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select

from app.core.logging import request_id_var
from app.models.identity import AuditEvent
from app.services.identity.service import new_id, now
from app.services.identity.store import identity_session

if TYPE_CHECKING:
    from app.core.auth import Principal

logger = logging.getLogger("pulsereach.audit")
_FORBIDDEN_DETAIL_KEYS = frozenset({"password", "token", "refresh_token", "access_token", "code", "note", "message"})


def record_event(
    principal: "Principal | None",
    action: str,
    resource_type: str,
    *,
    resource_id: str | None = None,
    patient_id: str | None = None,
    outcome: str = "success",
    status_code: int | None = None,
    permission: str | None = None,
    details: dict[str, Any] | None = None,
    actor_user_id: str | None = None,
    organization_id: str | None = None,
) -> None:
    safe = {k: v for k, v in (details or {}).items() if k not in _FORBIDDEN_DETAIL_KEYS}
    event = AuditEvent(
        event_id=new_id(),
        occurred_at=now(),
        request_id=request_id_var.get(),
        actor_user_id=actor_user_id or (principal.user_id if principal else None),
        actor_role=principal.role if principal else None,
        organization_id=organization_id or (principal.organization_id if principal else None),
        permission=permission,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        patient_id=patient_id,
        outcome=outcome,
        status_code=status_code,
        details=safe,
    )
    logger.info(
        "audit event",
        extra={"audit": {k: getattr(event, k) for k in (
            "event_id", "action", "resource_type", "resource_id", "outcome", "status_code",
            "actor_user_id", "actor_role", "organization_id", "patient_id")}},
    )
    try:
        with identity_session() as s:
            s.add(event)
    except Exception:  # the operation already happened; never mask its result, but be loud
        logger.exception("AUDIT WRITE FAILED for action=%s resource=%s/%s", action, resource_type, resource_id)


def list_events(
    *,
    organization_id: str,
    action: str | None = None,
    resource_type: str | None = None,
    actor_user_id: str | None = None,
    patient_id: str | None = None,
    outcome: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[int, list[AuditEvent]]:
    stmt = select(AuditEvent).where(AuditEvent.organization_id == organization_id)
    for col, val in (
        (AuditEvent.action, action),
        (AuditEvent.resource_type, resource_type),
        (AuditEvent.actor_user_id, actor_user_id),
        (AuditEvent.patient_id, patient_id),
        (AuditEvent.outcome, outcome),
    ):
        if val is not None:
            stmt = stmt.where(col == val)
    if since is not None:
        stmt = stmt.where(AuditEvent.occurred_at >= since)
    if until is not None:
        stmt = stmt.where(AuditEvent.occurred_at < until)
    with identity_session() as s:
        total = int(s.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
        rows = list(s.scalars(stmt.order_by(AuditEvent.occurred_at.desc(), AuditEvent.event_id)
                              .limit(limit).offset(offset)))
    return total, rows
