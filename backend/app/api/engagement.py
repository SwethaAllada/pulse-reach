"""Staff endpoints for patient-facing follow-up tasks and patient requests.

Everything is limited to the caller's organization and patient scope (assigned patients for care
coordinators/clinicians, the whole organization for population health managers).
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.auth import _users_mode_only
from app.api.v1 import get_followup_repository, get_read_repository
from app.core.auth import Principal, ensure_patient_access, require
from app.core.i18n import AppError, t
from app.models.identity import FollowUpTask, FollowUpTaskEvent, PatientRequest
from app.repositories.followup_repo import FollowUpRepository
from app.repositories.read_repo import ReadRepository
from app.schemas.portal import (
    PaginatedStaffRequestsOut,
    PaginatedTasksOut,
    RequestUpdateIn,
    StaffPatientRequestOut,
    TaskCompleteIn,
    TaskCreateIn,
    TaskDetailOut,
    TaskEscalateIn,
    TaskEventOut,
    TaskNoteIn,
    TaskOut,
    TaskUpdateIn,
)
from app.services.identity import directory, engagement
from app.services.identity.audit import record_event
from app.services.identity.store import identity_session

router = APIRouter(prefix="/api/v1", tags=["engagement"], dependencies=[Depends(_users_mode_only)])


def _task_out(task: FollowUpTask) -> dict:
    return dict(
        task_id=task.task_id, organization_id=task.organization_id, patient_id=task.patient_id,
        care_gap_id=task.care_gap_id, rule_id=task.rule_id, assigned_to_user_id=task.assigned_to_user_id,
        created_by_user_id=task.created_by_user_id, status=task.status, due_date=task.due_date,
        is_overdue=engagement.is_overdue(task), escalated_at=task.escalated_at, language=task.language,
        message_key=task.message_key, patient_message=t(f"task.{task.message_key}", task.language),
        patient_visible=task.patient_visible, staff_note=task.staff_note,
        patient_reported_completion=task.patient_reported_completion,
        completion_follow_up_id=task.completion_follow_up_id, created_at=task.created_at,
        updated_at=task.updated_at, completed_at=task.completed_at,
    )


def _event_out(e: FollowUpTaskEvent) -> TaskEventOut:
    return TaskEventOut(**{k: getattr(e, k) for k in TaskEventOut.model_fields})


def _detail(s, task: FollowUpTask) -> TaskDetailOut:
    return TaskDetailOut(**_task_out(task),
                         events=[_event_out(e) for e in engagement.task_events(s, task.task_id, include_internal=True)])


def _scoped_task(s, p: Principal, task_id: str) -> FollowUpTask:
    task = engagement.get_task(s, task_id, p.organization_id or "")
    ensure_patient_access(p, task.patient_id, f"Follow-up task '{task_id}' not found",
                          resource_type="follow_up_task", resource_id=task_id)
    return task


def _check_assignee(s, p: Principal, assignee: str | None, patient_id: str) -> None:
    if assignee is not None and not directory.can_staff_access_patient(s, assignee, p.organization_id, patient_id):
        raise AppError(422, "admin.staff_not_eligible")


@router.post("/follow-up-tasks", response_model=TaskDetailOut, status_code=201)
def create_task(
    req: TaskCreateIn,
    p: Principal = Depends(require("followups.create")),
    reads: ReadRepository = Depends(get_read_repository),
) -> TaskDetailOut:
    ensure_patient_access(p, req.patient_id, f"Synthetic patient '{req.patient_id}' not found")
    patient = reads.get_patient(req.patient_id)
    if patient is None:
        raise HTTPException(status_code=404, detail=f"Synthetic patient '{req.patient_id}' not found")
    rule_id = None
    if req.care_gap_id is not None:
        gap = next((g for g in reads.list_care_gaps(status=None, gap_type=None, rule_id=None, limit=200, offset=0,
                                                    patient_id=req.patient_id).items
                    if g.care_gap_id == req.care_gap_id), None)
        if gap is None or gap.status != "open":
            raise AppError(422, "workflow.care_gap_not_open")
        rule_id = gap.rule_id
    with identity_session() as s:
        _check_assignee(s, p, req.assigned_to_user_id, req.patient_id)
        task = engagement.create_task(
            s, organization_id=p.organization_id, patient_id=req.patient_id, care_gap_id=req.care_gap_id,
            rule_id=rule_id, assigned_to_user_id=req.assigned_to_user_id, created_by_user_id=p.user_id,
            actor_role=p.role, due_date=req.due_date, message_key=req.message_key,
            patient_visible=req.patient_visible, staff_note=req.staff_note,
            language=req.language or patient.preferred_language,
        )
        out = _detail(s, task)
    record_event(p, "follow_up_task.create", "follow_up_task", resource_id=out.task_id, patient_id=req.patient_id,
                 status_code=201, permission="followups.create",
                 details={"care_gap_id": req.care_gap_id, "assigned_to_user_id": req.assigned_to_user_id})
    return out


@router.get("/follow-up-tasks", response_model=PaginatedTasksOut)
def list_tasks(
    patient_id: str | None = Query(default=None),
    status: Literal["open", "awaiting_patient", "patient_responded", "in_progress", "completed", "cancelled"]
    | None = Query(default=None),
    assigned_to: str | None = Query(default=None, description="A user id, or 'me'."),
    overdue: bool | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    p: Principal = Depends(require("followups.read")),
) -> PaginatedTasksOut:
    with identity_session() as s:
        total, rows = engagement.list_tasks(
            s, organization_id=p.organization_id or "", patient_ids=p.patient_scope(), patient_id=patient_id,
            status=status, assigned_to_user_id=p.user_id if assigned_to == "me" else assigned_to,
            overdue=overdue, limit=limit, offset=offset,
        )
        items = [TaskOut(**_task_out(tk)) for tk in rows]
    return PaginatedTasksOut(total=total, limit=limit, offset=offset, items=items)


@router.get("/follow-up-tasks/{task_id}", response_model=TaskDetailOut)
def get_task(task_id: str, p: Principal = Depends(require("followups.read"))) -> TaskDetailOut:
    with identity_session() as s:
        return _detail(s, _scoped_task(s, p, task_id))


def _mutate(p: Principal, task_id: str, action: str, fn, details: dict | None = None) -> TaskDetailOut:
    patient_id = None
    try:
        with identity_session() as s:
            task = _scoped_task(s, p, task_id)
            patient_id = task.patient_id
            fn(s, task)
            s.flush()
            out = _detail(s, task)
    except HTTPException as exc:
        record_event(p, action, "follow_up_task", resource_id=task_id, patient_id=patient_id, outcome="failed",
                     status_code=exc.status_code, permission="followups.update")
        raise
    record_event(p, action, "follow_up_task", resource_id=task_id, patient_id=patient_id, status_code=200,
                 permission="followups.update", details=details)
    return out


@router.patch("/follow-up-tasks/{task_id}", response_model=TaskDetailOut)
def update_task(task_id: str, req: TaskUpdateIn, p: Principal = Depends(require("followups.update"))) -> TaskDetailOut:
    def apply(s, task):
        _check_assignee(s, p, req.assigned_to_user_id, task.patient_id)
        engagement.update_task(s, task, actor_user_id=p.user_id, actor_role=p.role, status=req.status,
                               assigned_to_user_id=req.assigned_to_user_id, due_date=req.due_date,
                               unset_due_date=req.clear_due_date)

    return _mutate(p, task_id, "follow_up_task.update", apply,
                   details={"status": req.status, "assigned_to_user_id": req.assigned_to_user_id})


@router.post("/follow-up-tasks/{task_id}/notes", response_model=TaskDetailOut)
def add_task_note(task_id: str, req: TaskNoteIn, p: Principal = Depends(require("followups.update"))) -> TaskDetailOut:
    """Internal note (default) or, with `patient_visible=true`, a message shown to the patient in the portal."""
    return _mutate(p, task_id, "follow_up_task.message" if req.patient_visible else "follow_up_task.note",
                   lambda s, task: engagement.add_staff_entry(s, task, actor_user_id=p.user_id, actor_role=p.role,
                                                              text=req.text, patient_visible=req.patient_visible))


@router.post("/follow-up-tasks/{task_id}/escalate", response_model=TaskDetailOut)
def escalate_task(task_id: str, req: TaskEscalateIn, p: Principal = Depends(require("followups.update"))) -> TaskDetailOut:
    return _mutate(p, task_id, "follow_up_task.escalate",
                   lambda s, task: engagement.escalate_task(s, task, actor_user_id=p.user_id, actor_role=p.role,
                                                            reason=req.reason))


@router.post("/follow-up-tasks/{task_id}/complete", response_model=TaskDetailOut)
def complete_task(
    task_id: str,
    req: TaskCompleteIn,
    p: Principal = Depends(require("followups.update")),
    followups: FollowUpRepository = Depends(get_followup_repository),
) -> TaskDetailOut:
    """Completes the task only if its care gap carries the referenced `completion_documented`
    follow-up (recorded with validated evidence through `POST /care-gaps/{id}/follow-ups`)."""

    def apply(s, task):
        verified = False
        if task.care_gap_id is not None and req.completion_follow_up_id:
            events = followups.list_follow_ups(task.care_gap_id, limit=200, offset=0).items
            verified = any(e.follow_up_id == req.completion_follow_up_id
                           and e.event_type == "completion_documented" for e in events)
        engagement.complete_task(s, task, actor_user_id=p.user_id, actor_role=p.role,
                                 completion_follow_up_id=req.completion_follow_up_id, completion_verified=verified)

    return _mutate(p, task_id, "follow_up_task.complete", apply,
                   details={"completion_follow_up_id": req.completion_follow_up_id})


# --- patient requests ----------------------------------------------------------------------


def _request_out(r: PatientRequest) -> StaffPatientRequestOut:
    return StaffPatientRequestOut(**{k: getattr(r, k) for k in StaffPatientRequestOut.model_fields
                                     if k != "preferred_dates"}, preferred_dates=list(r.preferred_dates or []))


@router.get("/patient-requests", response_model=PaginatedStaffRequestsOut)
def list_patient_requests(
    patient_id: str | None = Query(default=None),
    status: Literal["submitted", "acknowledged", "scheduled", "declined", "closed", "cancelled"]
    | None = Query(default=None),
    request_type: Literal["appointment", "assistance", "appointment_change"] | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    p: Principal = Depends(require("patient_requests.manage")),
) -> PaginatedStaffRequestsOut:
    with identity_session() as s:
        total, rows = engagement.list_requests(
            s, organization_id=p.organization_id or "", patient_ids=p.patient_scope(), patient_id=patient_id,
            status=status, request_type=request_type, limit=limit, offset=offset)
        items = [_request_out(r) for r in rows]
    return PaginatedStaffRequestsOut(total=total, limit=limit, offset=offset, items=items)


def _scoped_request(s, p: Principal, request_id: str) -> PatientRequest:
    r = engagement.get_request(s, request_id, p.organization_id or "")
    ensure_patient_access(p, r.patient_id, f"Patient request '{request_id}' not found",
                          resource_type="patient_request", resource_id=request_id)
    return r


@router.get("/patient-requests/{request_id}", response_model=StaffPatientRequestOut)
def get_patient_request(request_id: str, p: Principal = Depends(require("patient_requests.manage"))) -> StaffPatientRequestOut:
    with identity_session() as s:
        return _request_out(_scoped_request(s, p, request_id))


@router.patch("/patient-requests/{request_id}", response_model=StaffPatientRequestOut)
def update_patient_request(
    request_id: str,
    req: RequestUpdateIn,
    p: Principal = Depends(require("patient_requests.manage")),
    followups: FollowUpRepository = Depends(get_followup_repository),
) -> StaffPatientRequestOut:
    with identity_session() as s:
        r = _scoped_request(s, p, request_id)
        if req.appointment_id is not None and followups.get_appointment_patient_id(req.appointment_id) != r.patient_id:
            raise HTTPException(status_code=404, detail=f"Appointment '{req.appointment_id}' not found")
        engagement.update_request(s, r, actor_user_id=p.user_id, status=req.status,
                                  staff_response=req.staff_response, internal_note=req.internal_note,
                                  appointment_id=req.appointment_id)
        out = _request_out(r)
    record_event(p, "patient_request.update", "patient_request", resource_id=request_id, patient_id=out.patient_id,
                 status_code=200, permission="patient_requests.manage", details={"status": req.status})
    return out

