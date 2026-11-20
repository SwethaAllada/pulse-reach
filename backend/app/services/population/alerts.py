"""Population health alert persistence and lifecycle (no patient data, never contacts anyone).

De-duplication: one alert per `(organization_key, dedup_key)` while it is active (NEW,
ACKNOWLEDGED, INVESTIGATING; unique partial index). A repeated aggregation run that still detects
the condition updates that alert (metrics, severity, `last_detected_at`, `occurrence_count`)
instead of creating another. When a run no longer detects it, `condition_active` becomes false
(`condition_cleared` event) — the status is left to people. After an alert was RESOLVED or
DISMISSED, the same condition only raises a new alert once it has cleared and recurred, or when
its severity escalates above the closed alert's severity.

Lifecycle: NEW -> ACKNOWLEDGED | INVESTIGATING | RESOLVED | DISMISSED;
ACKNOWLEDGED -> INVESTIGATING | RESOLVED | DISMISSED; INVESTIGATING -> RESOLVED | DISMISSED.
RESOLVED and DISMISSED are terminal. Every change appends to `population_alert_event`.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.population import ACTIVE_ALERT_STATUSES, PopulationAlert, PopulationAlertEvent
from app.services.population.vocabulary import SEVERITY_RANK

TRANSITIONS: dict[str, frozenset[str]] = {
    "NEW": frozenset({"ACKNOWLEDGED", "INVESTIGATING", "RESOLVED", "DISMISSED"}),
    "ACKNOWLEDGED": frozenset({"INVESTIGATING", "RESOLVED", "DISMISSED"}),
    "INVESTIGATING": frozenset({"RESOLVED", "DISMISSED"}),
    "RESOLVED": frozenset(),
    "DISMISSED": frozenset(),
}
_TRACKED = ("severity", "metrics", "title", "explanation", "period_start", "period_end")


class InvalidTransition(ValueError):
    def __init__(self, from_status: str, to_status: str) -> None:
        super().__init__(f"{from_status} -> {to_status}")
        self.from_status, self.to_status = from_status, to_status


def _new_id() -> str:
    return str(uuid.uuid4())


def _d(v: str | None) -> date | None:
    return date.fromisoformat(v) if v else None


def _event(s: Session, a: PopulationAlert, event_type: str, at: datetime, *, run_id: str | None = None,
           actor: tuple[str | None, str | None] = (None, None), from_status: str | None = None,
           to_status: str | None = None, note: str | None = None, details: dict | None = None) -> None:
    s.add(PopulationAlertEvent(
        event_id=_new_id(), alert_id=a.alert_id, organization_key=a.organization_key, event_type=event_type,
        from_status=from_status, to_status=to_status, severity=a.severity, actor_user_id=actor[0],
        actor_role=actor[1], run_id=run_id, occurred_at=at, note=note, details=details or {},
    ))


def sync_alerts(s: Session, organization_key: str, run_id: str, candidates: list[dict[str, Any]],
                detected_at: datetime, data_freshness_at: datetime | None) -> dict[str, int]:
    summary = dict.fromkeys(("created", "updated", "unchanged", "cleared", "recurred", "suppressed_after_close"), 0)
    rows = list(s.scalars(select(PopulationAlert).where(PopulationAlert.organization_key == organization_key)
                          .order_by(PopulationAlert.created_at)))
    active = {a.dedup_key: a for a in rows if a.status in ACTIVE_ALERT_STATUSES}
    latest_closed: dict[str, PopulationAlert] = {}
    for a in rows:
        if a.status not in ACTIVE_ALERT_STATUSES:
            latest_closed[a.dedup_key] = a
    seen: set[str] = set()
    for c in candidates:
        key = c["dedup_key"]
        seen.add(key)
        values = {
            "severity": c["severity"], "metrics": {**c["metrics"], "message_key": c["explanation_key"],
                                                   "title_key": c["title_key"], "message_params": c["message_params"]},
            "thresholds": c["thresholds"], "title": c["title"], "explanation": c["explanation"],
            "period_key": c["period_key"], "period_start": _d(c["period_start"]), "period_end": _d(c["period_end"]),
        }
        a = active.get(key)
        if a is not None:
            changed = {k for k in _TRACKED if getattr(a, k) != values[k]}
            recurred = not a.condition_active
            for k, v in values.items():
                setattr(a, k, v)
            a.last_detected_at, a.data_freshness_at, a.last_run_id = detected_at, data_freshness_at, run_id
            a.occurrence_count += 1
            a.condition_active = True
            a.updated_at = detected_at
            if recurred:
                summary["recurred"] += 1
                _event(s, a, "condition_recurred", detected_at, run_id=run_id)
            if changed:
                summary["updated"] += 1
                _event(s, a, "updated", detected_at, run_id=run_id, details={"changed": sorted(changed)})
            elif not recurred:
                summary["unchanged"] += 1
            continue
        closed = latest_closed.get(key)
        if (closed is not None and closed.condition_active
                and SEVERITY_RANK[c["severity"]] <= SEVERITY_RANK[closed.severity]):
            summary["suppressed_after_close"] += 1
            continue
        a = PopulationAlert(
            alert_id=_new_id(), organization_key=organization_key, dedup_key=key, category=c["category"],
            area_id=c["area_id"], condition_code=c["condition_code"], first_detected_at=detected_at,
            last_detected_at=detected_at, data_freshness_at=data_freshness_at, status="NEW",
            condition_active=True, occurrence_count=1, last_run_id=run_id, created_at=detected_at,
            updated_at=detected_at, **values,
        )
        s.add(a)
        s.flush()
        summary["created"] += 1
        _event(s, a, "created", detected_at, run_id=run_id,
               details={"previous_closed_alert_id": closed.alert_id} if closed is not None else None)
    for a in rows:
        if a.condition_active and a.dedup_key not in seen:
            a.condition_active = False
            a.updated_at = detected_at
            if a.status in ACTIVE_ALERT_STATUSES:
                summary["cleared"] += 1
                _event(s, a, "condition_cleared", detected_at, run_id=run_id)
    return summary


def transition(s: Session, alert: PopulationAlert, to_status: str, *, actor_user_id: str,
               actor_role: str | None, note: str | None, at: datetime) -> PopulationAlert:
    if to_status not in TRANSITIONS[alert.status]:
        raise InvalidTransition(alert.status, to_status)
    from_status = alert.status
    alert.status = to_status
    alert.updated_at = at
    if to_status == "ACKNOWLEDGED":
        alert.acknowledged_by, alert.acknowledged_at = actor_user_id, at
    elif to_status == "INVESTIGATING":
        alert.investigating_by, alert.investigating_at = actor_user_id, at
    else:
        alert.closed_by, alert.closed_at = actor_user_id, at
    _event(s, alert, "status_changed", at, actor=(actor_user_id, actor_role), from_status=from_status,
           to_status=to_status, note=note)
    return alert
