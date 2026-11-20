"""Patient-facing follow-up tasks and patient requests (`engagement` schema).

Workflow: deterministic evaluation finds a care gap -> staff review it -> staff create/assign a
follow-up task (optionally patient-visible, with a localized message template) -> the patient
views it in the portal and responds, asks for help or requests an appointment -> a care
coordinator reviews the response and updates the task -> the task is completed only when its care
gap carries a `completion_documented` follow-up (verified evidence via the existing completion
workflow). Patients can *report* completion elsewhere; that never closes anything.

Nothing here sends messages: "patient-visible" means visible in the portal.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.i18n import AppError
from app.models.identity import (
    TASK_TERMINAL_STATUSES,
    FollowUpTask,
    FollowUpTaskEvent,
    PatientRequest,
)
from app.services.identity.service import new_id, now

# Staff-driven task transitions (completion has its own verified path).
TASK_TRANSITIONS: dict[str, frozenset[str]] = {
    "open": frozenset({"awaiting_patient", "in_progress", "cancelled"}),
    "awaiting_patient": frozenset({"in_progress", "cancelled"}),
    "patient_responded": frozenset({"in_progress", "awaiting_patient", "cancelled"}),
    "in_progress": frozenset({"awaiting_patient", "cancelled"}),
    "completed": frozenset(),
    "cancelled": frozenset(),
}
REQUEST_TRANSITIONS: dict[str, frozenset[str]] = {
    "submitted": frozenset({"acknowledged", "scheduled", "declined", "closed", "cancelled"}),
    "acknowledged": frozenset({"scheduled", "declined", "closed", "cancelled"}),
    "scheduled": frozenset({"closed"}),
    "declined": frozenset(),
    "closed": frozenset(),
    "cancelled": frozenset(),
}
PATIENT_RESPONSES = ("will_book", "already_done", "need_help", "not_interested", "question")


def _event(
    session: Session, task: FollowUpTask, *, actor_user_id: str, actor_role: str, event_type: str,
    visibility: str, from_status: str | None = None, to_status: str | None = None,
    response_code: str | None = None, message: str | None = None,
) -> FollowUpTaskEvent:
    ev = FollowUpTaskEvent(
        event_id=new_id(), task_id=task.task_id, organization_id=task.organization_id,
        patient_id=task.patient_id, actor_user_id=actor_user_id, actor_role=actor_role,
        event_type=event_type, visibility=visibility, from_status=from_status, to_status=to_status,
        response_code=response_code, message=message, created_at=now(),
    )
    session.add(ev)
    return ev


def is_overdue(task: FollowUpTask, today: date | None = None) -> bool:
    today = today or now().date()
    return task.due_date is not None and task.due_date < today and task.status not in TASK_TERMINAL_STATUSES


# --- tasks ---------------------------------------------------------------------------------


def create_task(
    session: Session, *, organization_id: str, patient_id: str, care_gap_id: str | None,
    rule_id: str | None, assigned_to_user_id: str | None, created_by_user_id: str, actor_role: str,
    due_date: date | None, message_key: str, patient_visible: bool, staff_note: str | None, language: str,
) -> FollowUpTask:
    ts = now()
    task = FollowUpTask(
        task_id=new_id(), organization_id=organization_id, patient_id=patient_id, care_gap_id=care_gap_id,
        rule_id=rule_id, assigned_to_user_id=assigned_to_user_id, created_by_user_id=created_by_user_id,
        status="awaiting_patient" if patient_visible else "open", due_date=due_date, language=language,
        message_key=message_key, patient_visible=patient_visible, staff_note=staff_note,
        patient_reported_completion=False, created_at=ts, updated_at=ts,
    )
    session.add(task)
    session.flush()
    _event(session, task, actor_user_id=created_by_user_id, actor_role=actor_role, event_type="created",
           visibility="patient" if patient_visible else "internal", to_status=task.status)
    if staff_note:
        _event(session, task, actor_user_id=created_by_user_id, actor_role=actor_role, event_type="staff_note",
               visibility="internal", message=staff_note)
    return task


def get_task(session: Session, task_id: str, organization_id: str) -> FollowUpTask:
    task = session.get(FollowUpTask, task_id)
    if task is None or task.organization_id != organization_id:
        raise AppError(404, "error.not_found", detail=f"Follow-up task '{task_id}' not found")
    return task


def list_tasks(
    session: Session, *, organization_id: str, patient_ids: frozenset[str] | None, patient_id: str | None = None,
    status: str | None = None, assigned_to_user_id: str | None = None, overdue: bool | None = None,
    patient_visible_only: bool = False, limit: int = 50, offset: int = 0,
) -> tuple[int, list[FollowUpTask]]:
    stmt = select(FollowUpTask).where(FollowUpTask.organization_id == organization_id)
    if patient_ids is not None:
        stmt = stmt.where(FollowUpTask.patient_id.in_(sorted(patient_ids)))
    if patient_id is not None:
        stmt = stmt.where(FollowUpTask.patient_id == patient_id)
    if status is not None:
        stmt = stmt.where(FollowUpTask.status == status)
    if assigned_to_user_id is not None:
        stmt = stmt.where(FollowUpTask.assigned_to_user_id == assigned_to_user_id)
    if patient_visible_only:
        stmt = stmt.where(FollowUpTask.patient_visible)
    if overdue is not None:
        cond = (FollowUpTask.due_date < now().date()) & FollowUpTask.status.not_in(TASK_TERMINAL_STATUSES)
        stmt = stmt.where(cond if overdue else ~cond | FollowUpTask.due_date.is_(None))
    total = int(session.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    rows = list(session.scalars(stmt.order_by(FollowUpTask.due_date.is_(None), FollowUpTask.due_date,
                                              FollowUpTask.created_at.desc()).limit(limit).offset(offset)))
    return total, rows


def task_events(session: Session, task_id: str, *, include_internal: bool) -> list[FollowUpTaskEvent]:
    stmt = select(FollowUpTaskEvent).where(FollowUpTaskEvent.task_id == task_id)
    if not include_internal:
        stmt = stmt.where(FollowUpTaskEvent.visibility == "patient")
    return list(session.scalars(stmt.order_by(FollowUpTaskEvent.created_at, FollowUpTaskEvent.event_id)))


def _ensure_open(task: FollowUpTask) -> None:
    if task.status in TASK_TERMINAL_STATUSES:
        raise AppError(409, "workflow.task_closed")


def update_task(
    session: Session, task: FollowUpTask, *, actor_user_id: str, actor_role: str, status: str | None = None,
    assigned_to_user_id: str | None = None, due_date: date | None = None, unset_due_date: bool = False,
) -> FollowUpTask:
    _ensure_open(task)
    ts = now()
    if status is not None and status != task.status:
        if status not in TASK_TRANSITIONS.get(task.status, frozenset()):
            raise AppError(422, "workflow.invalid_transition",
                           params={"from_status": task.status, "to_status": status})
        _event(session, task, actor_user_id=actor_user_id, actor_role=actor_role, event_type="status_changed",
               visibility="patient" if task.patient_visible else "internal",
               from_status=task.status, to_status=status)
        task.status = status
    if assigned_to_user_id is not None and assigned_to_user_id != task.assigned_to_user_id:
        task.assigned_to_user_id = assigned_to_user_id
        _event(session, task, actor_user_id=actor_user_id, actor_role=actor_role, event_type="assigned",
               visibility="internal")
    if unset_due_date or (due_date is not None and due_date != task.due_date):
        task.due_date = None if unset_due_date else due_date
        _event(session, task, actor_user_id=actor_user_id, actor_role=actor_role, event_type="due_date_changed",
               visibility="patient" if task.patient_visible else "internal")
    task.updated_at = ts
    return task


def add_staff_entry(
    session: Session, task: FollowUpTask, *, actor_user_id: str, actor_role: str, text: str, patient_visible: bool
) -> FollowUpTaskEvent:
    _ensure_open(task)
    task.updated_at = now()
    if patient_visible:
        if not task.patient_visible:
            raise AppError(422, "error.validation", params={"reason": "task is not patient-visible"})
        return _event(session, task, actor_user_id=actor_user_id, actor_role=actor_role,
                      event_type="staff_message", visibility="patient", message=text)
    return _event(session, task, actor_user_id=actor_user_id, actor_role=actor_role, event_type="staff_note",
                  visibility="internal", message=text)


def escalate_task(session: Session, task: FollowUpTask, *, actor_user_id: str, actor_role: str,
                  reason: str | None) -> FollowUpTask:
    _ensure_open(task)
    task.escalated_at = task.updated_at = now()
    _event(session, task, actor_user_id=actor_user_id, actor_role=actor_role, event_type="escalated",
           visibility="internal", message=reason)
    return task


def complete_task(
    session: Session, task: FollowUpTask, *, actor_user_id: str, actor_role: str,
    completion_follow_up_id: str | None, completion_verified: bool,
) -> FollowUpTask:
    """`completion_verified` must come from the caller checking that `completion_follow_up_id` is a
    `completion_documented` event on the task's care gap (evidence validated by the follow-up service)."""
    _ensure_open(task)
    if task.care_gap_id is not None and not completion_verified:
        raise AppError(422, "workflow.completion_evidence_required")
    ts = now()
    _event(session, task, actor_user_id=actor_user_id, actor_role=actor_role, event_type="completed",
           visibility="patient" if task.patient_visible else "internal", from_status=task.status,
           to_status="completed")
    task.status, task.completed_at, task.updated_at = "completed", ts, ts
    task.completion_follow_up_id = completion_follow_up_id
    return task


def patient_respond(
    session: Session, task: FollowUpTask, *, user_id: str, response_code: str, message: str | None
) -> FollowUpTaskEvent:
    _ensure_open(task)
    previous = task.status
    ev = _event(session, task, actor_user_id=user_id, actor_role="PATIENT", event_type="patient_response",
                visibility="patient", from_status=previous, to_status="patient_responded",
                response_code=response_code, message=message)
    if response_code == "already_done":
        task.patient_reported_completion = True  # staff must verify; nothing is closed
    task.status, task.updated_at = "patient_responded", now()
    return ev


# --- patient requests ----------------------------------------------------------------------


def create_request(
    session: Session, *, organization_id: str, patient_id: str, user_id: str, request_type: str,
    language: str, task: FollowUpTask | None = None, care_gap_id: str | None = None,
    appointment_id: str | None = None, change_action: str | None = None,
    preferred_dates: list[str] | None = None, preferred_time_of_day: str | None = None,
    message: str | None = None,
) -> PatientRequest:
    ts = now()
    if task is not None:
        _ensure_open(task)
    req = PatientRequest(
        request_id=new_id(), organization_id=organization_id, patient_id=patient_id,
        submitted_by_user_id=user_id, request_type=request_type, status="submitted",
        task_id=task.task_id if task else None, care_gap_id=care_gap_id or (task.care_gap_id if task else None),
        appointment_id=appointment_id, change_action=change_action, preferred_dates=preferred_dates or [],
        preferred_time_of_day=preferred_time_of_day, message=message, language=language,
        created_at=ts, updated_at=ts,
    )
    session.add(req)
    session.flush()
    if task is not None:
        _event(session, task, actor_user_id=user_id, actor_role="PATIENT",
               event_type="appointment_requested" if request_type == "appointment" else "assistance_requested",
               visibility="patient", message=message)
        if task.status in ("awaiting_patient", "open"):
            task.status = "patient_responded"
        task.updated_at = ts
    return req


def get_request(session: Session, request_id: str, organization_id: str) -> PatientRequest:
    r = session.get(PatientRequest, request_id)
    if r is None or r.organization_id != organization_id:
        raise AppError(404, "error.not_found", detail=f"Patient request '{request_id}' not found")
    return r


def list_requests(
    session: Session, *, organization_id: str, patient_ids: frozenset[str] | None, patient_id: str | None = None,
    status: str | None = None, request_type: str | None = None, limit: int = 50, offset: int = 0,
) -> tuple[int, list[PatientRequest]]:
    stmt = select(PatientRequest).where(PatientRequest.organization_id == organization_id)
    if patient_ids is not None:
        stmt = stmt.where(PatientRequest.patient_id.in_(sorted(patient_ids)))
    for col, val in ((PatientRequest.patient_id, patient_id), (PatientRequest.status, status),
                     (PatientRequest.request_type, request_type)):
        if val is not None:
            stmt = stmt.where(col == val)
    total = int(session.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    rows = list(session.scalars(stmt.order_by(PatientRequest.created_at.desc()).limit(limit).offset(offset)))
    return total, rows


def update_request(
    session: Session, r: PatientRequest, *, actor_user_id: str, status: str | None,
    staff_response: str | None, internal_note: str | None, appointment_id: str | None,
) -> PatientRequest:
    if status is not None and status != r.status:
        if status not in REQUEST_TRANSITIONS.get(r.status, frozenset()):
            raise AppError(422, "workflow.invalid_transition", params={"from_status": r.status, "to_status": status})
        r.status = status
    if staff_response is not None:
        r.staff_response = staff_response
    if internal_note is not None:
        r.internal_note = internal_note
    if appointment_id is not None:
        r.appointment_id = appointment_id
    r.handled_by_user_id, r.updated_at = actor_user_id, now()
    return r


def cancel_request_by_patient(session: Session, r: PatientRequest) -> PatientRequest:
    if "cancelled" not in REQUEST_TRANSITIONS.get(r.status, frozenset()) or r.status == "scheduled":
        raise AppError(422, "workflow.invalid_transition", params={"from_status": r.status, "to_status": "cancelled"})
    r.status, r.updated_at = "cancelled", now()
    return r


def summary_counts(session: Session, *, organization_id: str, patient_id: str) -> dict[str, Any]:
    tasks = list(session.scalars(select(FollowUpTask).where(
        FollowUpTask.organization_id == organization_id, FollowUpTask.patient_id == patient_id,
        FollowUpTask.patient_visible)))
    open_reqs = int(session.scalar(select(func.count()).select_from(PatientRequest).where(
        PatientRequest.organization_id == organization_id, PatientRequest.patient_id == patient_id,
        PatientRequest.status.in_(("submitted", "acknowledged")))) or 0)
    return {
        "open_follow_ups": sum(1 for t in tasks if t.status not in TASK_TERMINAL_STATUSES),
        "awaiting_your_reply": sum(1 for t in tasks if t.status == "awaiting_patient"),
        "open_requests": open_reqs,
    }
