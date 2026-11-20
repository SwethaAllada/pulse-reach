"""Follow-up, appointment, and referral write repositories (`T-09`, BE-08 … BE-15).

Every write is traceable:
- appointment and referral creates/status changes append a `workflow_status_event` (prior and
  new status, dates, actor); rows are never the only record of a decision;
- writes linked to a care gap also append a `care_gap_follow_up_event`, so the gap timeline
  shows outreach, appointments, referrals and documented completion together;
- a gap is closed as `closed_completed` only through validated completion evidence.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from fastapi import HTTPException
from sqlalchemy import func, or_, select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.clinical import Rule
from app.models.synthetic import (
    Appointment,
    Assessment,
    CareGap,
    CareGapFollowUpEvent,
    CareGapReview,
    Consent,
    EligibilityEvaluation,
    EvaluationRun,
    FacilityServiceProfile,
    GenerationRun,
    IfhasScreening,
    Patient,
    Referral,
    WellChildVisit,
    WorkflowStatusEvent,
)
from app.repositories.read_repo import (
    MemoryReadRepository,
    PostgresReadRepository,
    get_cached_bundle,
    get_cached_dataset,
    get_cached_engine,
    get_cached_index,
    _review_out,
)
from app.schemas.v1 import (
    AppointmentCreateIn,
    AppointmentOut,
    AppointmentPatchIn,
    CareGapReviewIn,
    CareGapReviewOut,
    CareGapReviewsOut,
    FollowUpCreateIn,
    FollowUpEventOut,
    PaginatedAppointmentsOut,
    PaginatedFollowUpEventsOut,
    PaginatedReferralsOut,
    PatientActivityOut,
    ReferralCreateIn,
    ReferralOut,
    ReferralPatchIn,
    WorkflowHistoryOut,
    WorkflowStatusEventOut,
)
from app.services.followup import (
    CompletionEvidence,
    FollowUpService,
    FollowUpValidationError,
    evaluate_current_rule,
)

logger = logging.getLogger(__name__)

_MEMORY_FOLLOW_UP_EVENTS: list[dict[str, Any]] = []
_MEMORY_WORKFLOW_EVENTS: list[dict[str, Any]] = []
_MEMORY_WRITE_LOCK = threading.RLock()

_CONFLICT_DETAIL = "The write conflicts with existing records or database constraints."


def reset_memory_writes() -> None:
    """Discard memory-mode follow-up and workflow events (tests, demo resets)."""
    with _MEMORY_WRITE_LOCK:
        _MEMORY_FOLLOW_UP_EVENTS.clear()
        _MEMORY_WORKFLOW_EVENTS.clear()


def get_memory_follow_up_events(
    care_gap_id: str | None = None,
    *,
    run_id: str | None = None,
    patient_id: str | None = None,
) -> list[dict[str, Any]]:
    return [
        e
        for e in _MEMORY_FOLLOW_UP_EVENTS
        if (care_gap_id is None or e["care_gap_id"] == care_gap_id)
        and (run_id is None or e["run_id"] == run_id)
        and (patient_id is None or e["patient_id"] == patient_id)
    ]


def get_memory_workflow_events(
    *,
    appointment_ids: set[str] | None = None,
    referral_ids: set[str] | None = None,
    care_gap_id: str | None = None,
    patient_id: str | None = None,
) -> list[dict[str, Any]]:
    """Workflow events matching any of the given entity/gap filters (and `patient_id`)."""
    entity_filter = appointment_ids is not None or referral_ids is not None or care_gap_id
    return [
        e
        for e in _MEMORY_WORKFLOW_EVENTS
        if (patient_id is None or e["patient_id"] == patient_id)
        and (
            not entity_filter
            or e["appointment_id"] in (appointment_ids or set())
            or e["referral_id"] in (referral_ids or set())
            or (care_gap_id is not None and e["care_gap_id"] == care_gap_id)
        )
    ]


def _next_synth_id(prefix: str, max_existing: str | None) -> str:
    if not max_existing:
        return f"{prefix}-000001"
    try:
        num = int(max_existing.rsplit("-", 1)[-1])
    except ValueError:
        num = 0
    return f"{prefix}-{num + 1:06d}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


# A follow-up identical to one recorded on the same gap within this window (same requested
# event, actor and note) is treated as an accidental resubmission (double click, client retry).
DUPLICATE_SUBMIT_WINDOW = timedelta(seconds=60)
ACTIVE_APPOINTMENT_STATUSES = ("scheduled", "rescheduled")
ACTIVE_REFERRAL_STATUSES = ("pending", "initiated")


def _duplicate(message: str, existing_id: str) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={"message": message, "code": "duplicate_request", "existing_id": existing_id},
    )


def _same_event_types(event_type: str) -> tuple[str, ...]:
    # An outreach attempt is recorded as `outreach_suppressed` when the gate refuses it.
    return ("outreach_attempted", "outreach_suppressed") if event_type == "outreach_attempted" else (event_type,)


def _is_resubmission(row: dict[str, Any], req: FollowUpCreateIn, now: datetime) -> bool:
    return (
        row["event_type"] in _same_event_types(req.event_type)
        and row["recorded_by"] == req.recorded_by
        and (row.get("note") or None) == (req.note or None)
        and now - row["recorded_at"] < DUPLICATE_SUBMIT_WINDOW
    )


def _transition_note(entity: str, entity_id: str, old: str | None, new: str, note: str | None) -> str:
    base = f"{entity} {entity_id}: {old} -> {new}" if old else f"{entity} {entity_id} created ({new})"
    return f"{base}. {note}" if note else base


# Called with the new event (and the PostgreSQL session) inside the write transaction, before it
# commits; an exception aborts the whole write.
OnRecorded = Callable[[FollowUpEventOut, "Session | None"], None]


class FollowUpRepository(Protocol):
    def create_follow_up(
        self, gap_id: str, req: FollowUpCreateIn, *, on_recorded: OnRecorded | None = None
    ) -> FollowUpEventOut: ...
    def list_follow_ups(self, gap_id: str, limit: int, offset: int) -> PaginatedFollowUpEventsOut: ...
    def list_appointments(
        self, patient_id: str | None, care_gap_id: str | None, status: str | None, limit: int, offset: int,
        patient_ids: frozenset[str] | None = None,
    ) -> PaginatedAppointmentsOut: ...
    def get_appointment_patient_id(self, appointment_id: str) -> str | None: ...
    def get_referral_patient_id(self, referral_id: str) -> str | None: ...
    def create_appointment(self, req: AppointmentCreateIn) -> AppointmentOut: ...
    def update_appointment(self, appointment_id: str, req: AppointmentPatchIn) -> AppointmentOut: ...
    def get_appointment_history(self, appointment_id: str) -> WorkflowHistoryOut: ...
    def list_referrals(
        self, patient_id: str | None, status: str | None, limit: int, offset: int,
        patient_ids: frozenset[str] | None = None,
    ) -> PaginatedReferralsOut: ...
    def create_referral(self, req: ReferralCreateIn) -> ReferralOut: ...
    def update_referral(self, referral_id: str, req: ReferralPatchIn) -> ReferralOut: ...
    def get_referral_history(self, referral_id: str) -> WorkflowHistoryOut: ...
    def get_patient_activity(self, patient_id: str) -> PatientActivityOut: ...
    def create_review(self, gap_id: str, req: CareGapReviewIn) -> CareGapReviewOut: ...
    def list_reviews(self, gap_id: str) -> CareGapReviewsOut: ...


def _validate_review(req: CareGapReviewIn) -> None:
    """A review records a clinician decision; it never changes the gap's clinical status."""
    if req.action == "priority_overridden":
        raise HTTPException(
            status_code=422,
            detail="priority_overridden is not available: AI priority scoring is not implemented, "
            "so there is no priority to override.",
        )
    if req.new_priority is not None:
        raise HTTPException(
            status_code=422, detail="new_priority is only allowed with action 'priority_overridden'."
        )


def _to_appointment_out(a: dict[str, Any]) -> AppointmentOut:
    return AppointmentOut(
        appointment_id=a["appointment_id"],
        patient_id=a["patient_id"],
        profile_id=a["profile_id"],
        care_gap_id=a.get("care_gap_id"),
        appointment_type=a["appointment_type"],
        scheduled_datetime=a["scheduled_datetime"],
        slot_type=a["slot_type"],
        status=a["status"],
        booked_via=a["booked_via"],
        is_synthetic=bool(a.get("is_synthetic", True)),
    )


def _to_referral_out(r: dict[str, Any]) -> ReferralOut:
    return ReferralOut(
        referral_id=r["referral_id"],
        patient_id=r["patient_id"],
        trigger_rule_id=r["trigger_rule_id"],
        trigger_rule_version=r["trigger_rule_version"],
        referral_target=r["referral_target"],
        target_profile_id=r.get("target_profile_id"),
        trigger_date=r["trigger_date"],
        initiated_date=r.get("initiated_date"),
        completed_date=r.get("completed_date"),
        status=r["status"],
        is_synthetic=bool(r.get("is_synthetic", True)),
    )


def _to_follow_up_out(f: dict[str, Any]) -> FollowUpEventOut:
    return FollowUpEventOut(
        follow_up_id=f["follow_up_id"],
        patient_id=f["patient_id"],
        care_gap_id=f["care_gap_id"],
        event_type=f["event_type"],
        outcome_status=f.get("outcome_status"),
        documented_evidence=bool(f.get("documented_evidence", False)),
        evidence_reference=f.get("evidence_reference"),
        contact_consent_id=f.get("contact_consent_id"),
        suppression_reason=f.get("suppression_reason"),
        recorded_by=f["recorded_by"],
        recorded_at=f["recorded_at"],
        note=f.get("note"),
        appointment_id=f.get("appointment_id"),
        referral_id=f.get("referral_id"),
        is_synthetic=bool(f.get("is_synthetic", True)),
    )


def _to_workflow_event_out(e: dict[str, Any]) -> WorkflowStatusEventOut:
    return WorkflowStatusEventOut(
        **{k: e.get(k) for k in WorkflowStatusEventOut.model_fields if k != "is_synthetic"},
        is_synthetic=bool(e.get("is_synthetic", True)),
    )


def _sorted_follow_ups(rows: list[dict[str, Any]]) -> list[FollowUpEventOut]:
    return [
        _to_follow_up_out(r)
        for r in sorted(rows, key=lambda x: (x["recorded_at"], x["follow_up_id"]), reverse=True)
    ]


def _sorted_workflow(rows: list[dict[str, Any]]) -> list[WorkflowStatusEventOut]:
    return [
        _to_workflow_event_out(r)
        for r in sorted(rows, key=lambda x: (x["recorded_at"], x["status_event_id"]))
    ]


def _validation(fn, *args, **kwargs) -> None:
    try:
        fn(*args, **kwargs)
    except FollowUpValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _workflow_row(
    *,
    run_id: str,
    patient_id: str,
    entity_type: str,
    entity_id: str,
    care_gap_id: str | None,
    from_status: str | None,
    to_status: str,
    recorded_by: str,
    note: str | None,
    recorded_at: datetime,
    scheduled_datetime: datetime | None = None,
    initiated_date: Any = None,
    completed_date: Any = None,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "patient_id": patient_id,
        "is_synthetic": True,
        "entity_type": entity_type,
        "appointment_id": entity_id if entity_type == "appointment" else None,
        "referral_id": entity_id if entity_type == "referral" else None,
        "care_gap_id": care_gap_id,
        "from_status": from_status,
        "to_status": to_status,
        "scheduled_datetime": scheduled_datetime,
        "initiated_date": initiated_date,
        "completed_date": completed_date,
        "recorded_by": recorded_by,
        "recorded_at": recorded_at,
        "note": note,
    }


def _gap_event_row(
    *,
    run_id: str,
    patient_id: str,
    care_gap_id: str,
    event_type: str,
    recorded_by: str,
    recorded_at: datetime,
    note: str | None,
    outcome_status: str | None = "status_recorded",
    appointment_id: str | None = None,
    referral_id: str | None = None,
    documented_evidence: bool = False,
    evidence_reference: str | None = None,
    contact_consent_id: str | None = None,
    suppression_reason: str | None = None,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "patient_id": patient_id,
        "care_gap_id": care_gap_id,
        "is_synthetic": True,
        "event_type": event_type,
        "outcome_status": outcome_status,
        "documented_evidence": documented_evidence,
        "evidence_reference": evidence_reference,
        "contact_consent_id": contact_consent_id,
        "suppression_reason": suppression_reason,
        "recorded_by": recorded_by,
        "recorded_at": recorded_at,
        "note": note,
        "appointment_id": appointment_id,
        "referral_id": referral_id,
    }


# ---------------------------------------------------------------------------
# Memory mode
# ---------------------------------------------------------------------------


class MemoryFollowUpRepository:
    """In-process writes against the cached synthetic dataset (demo mode, per worker)."""

    def __init__(self, service: FollowUpService | None = None) -> None:
        self._svc = service or FollowUpService()

    # -- helpers -------------------------------------------------------------------------------

    @staticmethod
    def _rule(rule_id: str, rule_version: str) -> dict[str, Any] | None:
        return next(
            (
                r
                for r in get_cached_bundle().rules
                if r["rule_id"] == rule_id and r["rule_version"] == rule_version
            ),
            None,
        )

    @staticmethod
    def _append_gap_event(row: dict[str, Any]) -> dict[str, Any]:
        row = {"follow_up_id": f"SYNTH-FUP-{len(_MEMORY_FOLLOW_UP_EVENTS) + 1:06d}", **row}
        _MEMORY_FOLLOW_UP_EVENTS.append(row)
        return row

    @staticmethod
    def _append_workflow_event(row: dict[str, Any]) -> dict[str, Any]:
        row = {"status_event_id": f"SYNTH-WSE-{len(_MEMORY_WORKFLOW_EVENTS) + 1:06d}", **row}
        _MEMORY_WORKFLOW_EVENTS.append(row)
        return row

    @staticmethod
    def _gap(gap_id: str, patient_id: str | None = None) -> dict[str, Any] | None:
        return next(
            (
                g
                for g in get_cached_dataset().care_gaps
                if g["care_gap_id"] == gap_id and (patient_id is None or g["patient_id"] == patient_id)
            ),
            None,
        )

    @staticmethod
    def _referral_gap_ids(ref: dict[str, Any]) -> list[str]:
        ids = {
            g["care_gap_id"]
            for g in get_cached_dataset().care_gaps
            if g["patient_id"] == ref["patient_id"] and g.get("subject_referral_id") == ref["referral_id"]
        }
        ids |= {
            e["care_gap_id"]
            for e in _MEMORY_WORKFLOW_EVENTS
            if e["referral_id"] == ref["referral_id"] and e["care_gap_id"]
        }
        return sorted(ids)

    @staticmethod
    def _referral_link_gap(referral_id: str) -> str | None:
        return next(
            (
                e["care_gap_id"]
                for e in _MEMORY_WORKFLOW_EVENTS
                if e["referral_id"] == referral_id and e["care_gap_id"]
            ),
            None,
        )

    # -- follow-ups ----------------------------------------------------------------------------

    def create_follow_up(
        self, gap_id: str, req: FollowUpCreateIn, *, on_recorded: OnRecorded | None = None
    ) -> FollowUpEventOut:
        # Validation and gap/event mutation happen under one lock so concurrent completion
        # attempts on the same gap cannot both observe it as open.
        with _MEMORY_WRITE_LOCK:
            return self._create_follow_up_locked(gap_id, req, on_recorded)

    def _create_follow_up_locked(
        self, gap_id: str, req: FollowUpCreateIn, on_recorded: OnRecorded | None
    ) -> FollowUpEventOut:
        ds = get_cached_dataset()
        idx = get_cached_index()
        gap = self._gap(gap_id)
        if gap is None:
            raise HTTPException(status_code=404, detail=f"Care gap '{gap_id}' not found")
        patient = idx.patients_by_id.get(gap["patient_id"])
        if patient is None:
            raise HTTPException(status_code=404, detail=f"Patient '{gap['patient_id']}' not found")
        rule = self._rule(gap["rule_id"], gap["rule_version"])

        if not req.close_gap:
            now = _now()
            dup = next(
                (e for e in get_memory_follow_up_events(gap_id) if _is_resubmission(e, req, now)), None
            )
            if dup is not None:
                raise _duplicate("An identical follow-up was just recorded for this care gap.", dup["follow_up_id"])

        event_type = req.event_type
        outcome_status: str | None = "noted"
        contact_consent_id: str | None = None
        suppression_reason: str | None = None

        if req.close_gap:
            ev_ref = (req.evidence_reference or "").strip()
            scr = next((s for s in ds.ifhas_screenings if s["screening_id"] == ev_ref), None)
            vis = next((v for v in ds.well_child_visits if v["visit_id"] == ev_ref), None)
            ref = next((r for r in ds.referrals if r["referral_id"] == ev_ref), None)
            evidence = (
                CompletionEvidence.from_screening(scr)
                if scr is not None
                else CompletionEvidence.from_visit(vis)
                if vis is not None
                else CompletionEvidence.from_referral(ref)
                if ref is not None
                else None
            )
            as_of = ds.evaluation_run["reference_date"]
            result = self._svc.validate_completion_evidence(
                gap=gap,
                rule=rule,
                evidence=evidence,
                documented_evidence=req.documented_evidence,
                evidence_reference=req.evidence_reference,
                as_of=as_of,
                current_evaluation=evaluate_current_rule(
                    get_cached_engine(),
                    MemoryReadRepository().get_patient_context(gap["patient_id"]),
                    rule_id=gap["rule_id"],
                    rule_version=gap["rule_version"],
                    as_of=as_of,
                    look_ahead_days=ds.evaluation_run.get("look_ahead_days"),
                ),
            )
            if not result.accepted:
                raise HTTPException(status_code=422, detail=result.message)
            gap[result.closed_by_field] = result.evidence_id
            gap["status"] = "closed_completed"
            gap["closed_date"] = as_of
            outcome_status = "completed"

        if req.event_type == "outreach_attempted":
            patient_evals = [
                e
                for e in idx.evaluations_by_patient.get(gap["patient_id"], [])
                if e["rule_id"] == gap["rule_id"]
            ]
            allowed, consent_id, blocked_reason = self._svc.evaluate_outreach_consent(
                patient=patient,
                consents=idx.consents_by_patient.get(gap["patient_id"], []),
                rule_meta=rule,
                care_gap=gap,
                evaluations=patient_evals,
            )
            event_type, outcome_status, contact_consent_id, suppression_reason = (
                self._svc.outreach_attempt_outcome(
                    allowed=allowed, consent_id=consent_id, blocked_reason=blocked_reason
                )
            )

        row = {
            "follow_up_id": f"SYNTH-FUP-{len(_MEMORY_FOLLOW_UP_EVENTS) + 1:06d}",
            **_gap_event_row(
                run_id=ds.generation_run["run_id"],
                patient_id=gap["patient_id"],
                care_gap_id=gap_id,
                event_type=event_type,
                outcome_status=outcome_status,
                documented_evidence=req.documented_evidence,
                evidence_reference=req.evidence_reference,
                contact_consent_id=contact_consent_id,
                suppression_reason=suppression_reason,
                recorded_by=req.recorded_by,
                recorded_at=_now(),
                note=req.note,
            ),
        }
        out = _to_follow_up_out(row)
        if on_recorded is not None:
            on_recorded(out, None)  # raising here records nothing
        _MEMORY_FOLLOW_UP_EVENTS.append(row)
        return out

    def list_follow_ups(self, gap_id: str, limit: int, offset: int) -> PaginatedFollowUpEventsOut:
        if self._gap(gap_id) is None:
            raise HTTPException(status_code=404, detail=f"Care gap '{gap_id}' not found")
        items = _sorted_follow_ups(get_memory_follow_up_events(gap_id))
        return PaginatedFollowUpEventsOut(
            total=len(items), limit=limit, offset=offset, items=items[offset : offset + limit]
        )

    # -- appointments --------------------------------------------------------------------------

    def list_appointments(
        self,
        patient_id: str | None,
        care_gap_id: str | None,
        status: str | None,
        limit: int,
        offset: int,
        patient_ids: frozenset[str] | None = None,
    ) -> PaginatedAppointmentsOut:
        apts = get_cached_dataset().appointments
        if patient_ids is not None:
            apts = [a for a in apts if a["patient_id"] in patient_ids]
        if patient_id is not None:
            apts = [a for a in apts if a["patient_id"] == patient_id]
        if care_gap_id is not None:
            apts = [a for a in apts if a.get("care_gap_id") == care_gap_id]
        if status is not None:
            apts = [a for a in apts if a["status"] == status]
        page = apts[offset : offset + limit]
        return PaginatedAppointmentsOut(
            is_synthetic=True,
            total=len(apts),
            limit=limit,
            offset=offset,
            items=[_to_appointment_out(a) for a in page],
        )

    def get_appointment_patient_id(self, appointment_id: str) -> str | None:
        return next(
            (a["patient_id"] for a in get_cached_dataset().appointments if a["appointment_id"] == appointment_id),
            None,
        )

    def get_referral_patient_id(self, referral_id: str) -> str | None:
        return next(
            (r["patient_id"] for r in get_cached_dataset().referrals if r["referral_id"] == referral_id), None
        )

    def create_appointment(self, req: AppointmentCreateIn) -> AppointmentOut:
        with _MEMORY_WRITE_LOCK:
            ds = get_cached_dataset()
            idx = get_cached_index()
            if req.patient_id not in idx.patients_by_id:
                raise HTTPException(status_code=404, detail=f"Patient '{req.patient_id}' not found")
            if not any(f["profile_id"] == req.profile_id for f in ds.facility_service_profiles):
                raise HTTPException(
                    status_code=404, detail=f"Facility service profile '{req.profile_id}' not found"
                )
            if req.care_gap_id is not None and self._gap(req.care_gap_id, req.patient_id) is None:
                raise HTTPException(
                    status_code=404, detail=f"Care gap '{req.care_gap_id}' not found for patient"
                )
            dup = next(
                (
                    a
                    for a in ds.appointments
                    if (a["patient_id"], a["profile_id"], a["scheduled_datetime"], a["appointment_type"])
                    == (req.patient_id, req.profile_id, req.scheduled_datetime, req.appointment_type)
                    and a["status"] in ACTIVE_APPOINTMENT_STATUSES
                ),
                None,
            )
            if dup is not None:
                raise _duplicate(
                    "An active appointment already exists for this patient, facility, type and time.",
                    dup["appointment_id"],
                )
            apt_id = f"SYNTH-APT-{len(ds.appointments) + 1:06d}"
            run_id = ds.generation_run["run_id"]
            row = {
                "appointment_id": apt_id,
                "run_id": run_id,
                "patient_id": req.patient_id,
                "is_synthetic": True,
                "profile_id": req.profile_id,
                "care_gap_id": req.care_gap_id,
                "appointment_type": req.appointment_type,
                "scheduled_datetime": req.scheduled_datetime,
                "slot_type": req.slot_type,
                "status": "scheduled",
                "booked_via": req.booked_via,
            }
            ds.appointments.append(row)
            now = _now()
            self._append_workflow_event(
                _workflow_row(
                    run_id=run_id,
                    patient_id=req.patient_id,
                    entity_type="appointment",
                    entity_id=apt_id,
                    care_gap_id=req.care_gap_id,
                    from_status=None,
                    to_status="scheduled",
                    scheduled_datetime=req.scheduled_datetime,
                    recorded_by=req.recorded_by,
                    recorded_at=now,
                    note=req.note,
                )
            )
            if req.care_gap_id is not None:
                self._append_gap_event(
                    _gap_event_row(
                        run_id=run_id,
                        patient_id=req.patient_id,
                        care_gap_id=req.care_gap_id,
                        event_type="appointment_scheduled",
                        appointment_id=apt_id,
                        recorded_by=req.recorded_by,
                        recorded_at=now,
                        note=_transition_note("Appointment", apt_id, None, "scheduled", req.note),
                    )
                )
            return _to_appointment_out(row)

    def update_appointment(self, appointment_id: str, req: AppointmentPatchIn) -> AppointmentOut:
        with _MEMORY_WRITE_LOCK:
            ds = get_cached_dataset()
            apt = next((a for a in ds.appointments if a["appointment_id"] == appointment_id), None)
            if apt is None:
                raise HTTPException(status_code=404, detail=f"Appointment '{appointment_id}' not found")
            _validation(self._svc.validate_appointment_transition, apt["status"], req.status)
            old = apt["status"]
            apt["status"] = req.status
            if req.scheduled_datetime is not None:
                apt["scheduled_datetime"] = req.scheduled_datetime
            now = _now()
            self._append_workflow_event(
                _workflow_row(
                    run_id=apt["run_id"],
                    patient_id=apt["patient_id"],
                    entity_type="appointment",
                    entity_id=appointment_id,
                    care_gap_id=apt.get("care_gap_id"),
                    from_status=old,
                    to_status=req.status,
                    scheduled_datetime=apt["scheduled_datetime"],
                    recorded_by=req.recorded_by,
                    recorded_at=now,
                    note=req.note,
                )
            )
            if apt.get("care_gap_id"):
                self._append_gap_event(
                    _gap_event_row(
                        run_id=apt["run_id"],
                        patient_id=apt["patient_id"],
                        care_gap_id=apt["care_gap_id"],
                        event_type="appointment_updated",
                        appointment_id=appointment_id,
                        recorded_by=req.recorded_by,
                        recorded_at=now,
                        note=_transition_note("Appointment", appointment_id, old, req.status, req.note),
                    )
                )
            return _to_appointment_out(apt)

    def get_appointment_history(self, appointment_id: str) -> WorkflowHistoryOut:
        if not any(a["appointment_id"] == appointment_id for a in get_cached_dataset().appointments):
            raise HTTPException(status_code=404, detail=f"Appointment '{appointment_id}' not found")
        return WorkflowHistoryOut(
            entity_type="appointment",
            entity_id=appointment_id,
            items=_sorted_workflow(get_memory_workflow_events(appointment_ids={appointment_id})),
        )

    # -- referrals -----------------------------------------------------------------------------

    def list_referrals(
        self,
        patient_id: str | None,
        status: str | None,
        limit: int,
        offset: int,
        patient_ids: frozenset[str] | None = None,
    ) -> PaginatedReferralsOut:
        refs = get_cached_dataset().referrals
        if patient_ids is not None:
            refs = [r for r in refs if r["patient_id"] in patient_ids]
        if patient_id is not None:
            refs = [r for r in refs if r["patient_id"] == patient_id]
        if status is not None:
            refs = [r for r in refs if r["status"] == status]
        page = refs[offset : offset + limit]
        return PaginatedReferralsOut(
            is_synthetic=True,
            total=len(refs),
            limit=limit,
            offset=offset,
            items=[_to_referral_out(r) for r in page],
        )

    def create_referral(self, req: ReferralCreateIn) -> ReferralOut:
        with _MEMORY_WRITE_LOCK:
            return self._create_referral_locked(req)

    def _create_referral_locked(self, req: ReferralCreateIn) -> ReferralOut:
        ds = get_cached_dataset()
        idx = get_cached_index()
        if req.patient_id not in idx.patients_by_id:
            raise HTTPException(status_code=404, detail=f"Patient '{req.patient_id}' not found")
        if self._rule(req.trigger_rule_id, req.trigger_rule_version) is None:
            raise HTTPException(
                status_code=404,
                detail=f"Rule '{req.trigger_rule_id}' v'{req.trigger_rule_version}' not found",
            )
        if req.target_profile_id is not None and not any(
            f["profile_id"] == req.target_profile_id for f in ds.facility_service_profiles
        ):
            raise HTTPException(
                status_code=404,
                detail=f"Target facility service profile '{req.target_profile_id}' not found",
            )
        for ref_id, rows, key, label in (
            (req.ifhas_screening_id, ds.ifhas_screenings, "screening_id", "IFHAS screening"),
            (req.well_child_visit_id, ds.well_child_visits, "visit_id", "Well-child visit"),
            (req.assessment_id, ds.assessments, "assessment_id", "Assessment"),
        ):
            if ref_id is not None and not any(
                r[key] == ref_id and r["patient_id"] == req.patient_id for r in rows
            ):
                raise HTTPException(status_code=404, detail=f"{label} '{ref_id}' not found for patient")
        if req.care_gap_id is not None and self._gap(req.care_gap_id, req.patient_id) is None:
            raise HTTPException(
                status_code=404, detail=f"Care gap '{req.care_gap_id}' not found for patient"
            )
        _validation(
            self._svc.validate_referral_create,
            ifhas_screening_id=req.ifhas_screening_id,
            well_child_visit_id=req.well_child_visit_id,
            assessment_id=req.assessment_id,
            status=req.status,
            trigger_date=req.trigger_date,
            initiated_date=req.initiated_date,
            completed_date=None,
        )
        dup = next(
            (
                r
                for r in ds.referrals
                if (r["patient_id"], r["trigger_rule_id"], r["trigger_rule_version"], r["referral_target"])
                == (req.patient_id, req.trigger_rule_id, req.trigger_rule_version, req.referral_target)
                and r["status"] in ACTIVE_REFERRAL_STATUSES
            ),
            None,
        )
        if dup is not None:
            raise _duplicate(
                "An active referral already exists for this patient, rule and target.", dup["referral_id"]
            )
        ref_id = f"SYNTH-REF-{len(ds.referrals) + 1:06d}"
        run_id = ds.generation_run["run_id"]
        row = {
            "referral_id": ref_id,
            "run_id": run_id,
            "patient_id": req.patient_id,
            "is_synthetic": True,
            "ifhas_screening_id": req.ifhas_screening_id,
            "well_child_visit_id": req.well_child_visit_id,
            "assessment_id": req.assessment_id,
            "trigger_rule_id": req.trigger_rule_id,
            "trigger_rule_version": req.trigger_rule_version,
            "rule_action_ordinal": None,
            "referral_target": req.referral_target,
            "target_profile_id": req.target_profile_id,
            "trigger_date": req.trigger_date,
            "initiated_date": req.initiated_date,
            "completed_date": None,
            "status": req.status,
        }
        ds.referrals.append(row)
        idx.referrals_by_patient.setdefault(req.patient_id, []).append(row)
        now = _now()
        self._append_workflow_event(
            _workflow_row(
                run_id=run_id,
                patient_id=req.patient_id,
                entity_type="referral",
                entity_id=ref_id,
                care_gap_id=req.care_gap_id,
                from_status=None,
                to_status=req.status,
                initiated_date=req.initiated_date,
                recorded_by=req.recorded_by,
                recorded_at=now,
                note=req.note,
            )
        )
        if req.care_gap_id is not None:
            self._append_gap_event(
                _gap_event_row(
                    run_id=run_id,
                    patient_id=req.patient_id,
                    care_gap_id=req.care_gap_id,
                    event_type="referral_created",
                    referral_id=ref_id,
                    recorded_by=req.recorded_by,
                    recorded_at=now,
                    note=_transition_note("Referral", ref_id, None, req.status, req.note),
                )
            )
        return _to_referral_out(row)

    def update_referral(self, referral_id: str, req: ReferralPatchIn) -> ReferralOut:
        with _MEMORY_WRITE_LOCK:
            ds = get_cached_dataset()
            ref = next((r for r in ds.referrals if r["referral_id"] == referral_id), None)
            if ref is None:
                raise HTTPException(status_code=404, detail=f"Referral '{referral_id}' not found")
            new_init = req.initiated_date if req.initiated_date is not None else ref.get("initiated_date")
            new_comp = req.completed_date if req.completed_date is not None else ref.get("completed_date")
            _validation(
                self._svc.validate_referral_transition,
                ref["status"],
                req.status,
                trigger_date=ref["trigger_date"],
                initiated_date=new_init,
                completed_date=new_comp,
            )
            old = ref["status"]
            ref["status"] = req.status
            ref["initiated_date"] = new_init
            ref["completed_date"] = new_comp
            now = _now()
            self._append_workflow_event(
                _workflow_row(
                    run_id=ref["run_id"],
                    patient_id=ref["patient_id"],
                    entity_type="referral",
                    entity_id=referral_id,
                    care_gap_id=self._referral_link_gap(referral_id),
                    from_status=old,
                    to_status=req.status,
                    initiated_date=new_init,
                    completed_date=new_comp,
                    recorded_by=req.recorded_by,
                    recorded_at=now,
                    note=req.note,
                )
            )
            for gap_id in self._referral_gap_ids(ref):
                self._append_gap_event(
                    _gap_event_row(
                        run_id=ref["run_id"],
                        patient_id=ref["patient_id"],
                        care_gap_id=gap_id,
                        event_type="referral_updated",
                        referral_id=referral_id,
                        recorded_by=req.recorded_by,
                        recorded_at=now,
                        note=_transition_note("Referral", referral_id, old, req.status, req.note),
                    )
                )
            return _to_referral_out(ref)

    def get_referral_history(self, referral_id: str) -> WorkflowHistoryOut:
        if not any(r["referral_id"] == referral_id for r in get_cached_dataset().referrals):
            raise HTTPException(status_code=404, detail=f"Referral '{referral_id}' not found")
        return WorkflowHistoryOut(
            entity_type="referral",
            entity_id=referral_id,
            items=_sorted_workflow(get_memory_workflow_events(referral_ids={referral_id})),
        )

    def get_patient_activity(self, patient_id: str) -> PatientActivityOut:
        if patient_id not in get_cached_index().patients_by_id:
            raise HTTPException(status_code=404, detail=f"Synthetic patient '{patient_id}' not found")
        return PatientActivityOut(
            patient_id=patient_id,
            follow_up_events=_sorted_follow_ups(get_memory_follow_up_events(patient_id=patient_id)),
            workflow_events=_sorted_workflow(get_memory_workflow_events(patient_id=patient_id)),
        )

    def create_review(self, gap_id: str, req: CareGapReviewIn) -> CareGapReviewOut:
        with _MEMORY_WRITE_LOCK:
            ds = get_cached_dataset()
            gap = self._gap(gap_id)
            if gap is None:
                raise HTTPException(status_code=404, detail=f"Care gap '{gap_id}' not found")
            _validate_review(req)
            row = {
                "review_id": _next_synth_id(
                    "SYNTH-REV", max((r["review_id"] for r in ds.care_gap_reviews), default=None)
                ),
                "run_id": gap["run_id"],
                "care_gap_id": gap_id,
                "is_synthetic": True,
                "reviewer": req.reviewer,
                "action": req.action,
                "previous_priority": gap.get("priority_score"),
                "new_priority": None,
                "reason": req.reason,
                "reviewed_at": _now(),
            }
            ds.care_gap_reviews.append(row)
            return _review_out(row)

    def list_reviews(self, gap_id: str) -> CareGapReviewsOut:
        if self._gap(gap_id) is None:
            raise HTTPException(status_code=404, detail=f"Care gap '{gap_id}' not found")
        rows = [r for r in get_cached_dataset().care_gap_reviews if r["care_gap_id"] == gap_id]
        return CareGapReviewsOut(
            care_gap_id=gap_id,
            items=[_review_out(r) for r in sorted(rows, key=lambda x: (x["reviewed_at"], x["review_id"]))],
        )


# ---------------------------------------------------------------------------
# PostgreSQL mode
# ---------------------------------------------------------------------------


class PostgresFollowUpRepository:
    def __init__(self, session: Session, service: FollowUpService | None = None) -> None:
        self._session = session
        self._svc = service or FollowUpService()

    # -- helpers -------------------------------------------------------------------------------

    @contextmanager
    def _write(self) -> Iterator[None]:
        """One transaction per write; constraint violations are 409, other DB errors 503."""
        try:
            yield
            self._session.commit()
        except HTTPException:
            self._session.rollback()
            raise
        except IntegrityError as exc:
            self._session.rollback()
            logger.warning("follow-up write rejected by database constraint: %s", type(exc.orig).__name__)
            raise HTTPException(status_code=409, detail=_CONFLICT_DETAIL) from exc
        except SQLAlchemyError as exc:
            self._session.rollback()
            logger.exception("follow-up write failed")
            raise HTTPException(status_code=503, detail="PostgreSQL write failed.") from exc

    @contextmanager
    def _read(self) -> Iterator[None]:
        try:
            yield
        except SQLAlchemyError as exc:
            logger.exception("follow-up read failed")
            raise HTTPException(status_code=503, detail="PostgreSQL query failed.") from exc

    def _latest_runs(self) -> tuple[GenerationRun, EvaluationRun]:
        gr = self._session.scalars(
            select(GenerationRun).order_by(
                GenerationRun.started_at.desc(), GenerationRun.run_id.desc()
            )
        ).first()
        if gr is None:
            raise HTTPException(
                status_code=503,
                detail="Database has no seeded synthetic generation/evaluation run.",
            )
        er = self._session.scalars(
            select(EvaluationRun)
            .where(EvaluationRun.run_id == gr.run_id)
            .order_by(EvaluationRun.started_at.desc(), EvaluationRun.evaluation_run_id.desc())
        ).first()
        if er is None:
            raise HTTPException(
                status_code=503,
                detail="Database has no seeded evaluation run.",
            )
        return gr, er

    @staticmethod
    def _row_dict(obj: Any) -> dict[str, Any]:
        return {col.name: getattr(obj, col.name) for col in obj.__table__.columns}

    @property
    def session(self) -> Session:
        return self._session

    def _lock(self, key: str) -> None:
        """Transaction-scoped advisory lock (re-entrant within the transaction)."""
        if self._session.get_bind().dialect.name == "postgresql":
            self._session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": key})

    def _next_id(self, model: Any, column: Any, prefix: str) -> str:
        # Serialise id minting per table for the rest of the transaction, so concurrent writers
        # cannot both read the same MAX() (BE-14).
        self._lock(prefix)
        return _next_synth_id(prefix, self._session.scalar(select(func.max(column))))

    def _add_workflow_event(self, row: dict[str, Any]) -> WorkflowStatusEvent:
        ev = WorkflowStatusEvent(
            status_event_id=self._next_id(
                WorkflowStatusEvent, WorkflowStatusEvent.status_event_id, "SYNTH-WSE"
            ),
            **row,
        )
        self._session.add(ev)
        self._session.flush()
        return ev

    def _add_gap_event(self, row: dict[str, Any]) -> CareGapFollowUpEvent:
        fup = CareGapFollowUpEvent(
            follow_up_id=self._next_id(
                CareGapFollowUpEvent, CareGapFollowUpEvent.follow_up_id, "SYNTH-FUP"
            ),
            **row,
        )
        self._session.add(fup)
        self._session.flush()
        return fup

    def _gap(self, run_id: str, gap_id: str, patient_id: str | None = None, *, lock: bool = False):
        stmt = select(CareGap).where(CareGap.run_id == run_id, CareGap.care_gap_id == gap_id)
        if patient_id is not None:
            stmt = stmt.where(CareGap.patient_id == patient_id)
        if lock:
            stmt = stmt.with_for_update()
        return self._session.scalars(stmt).first()

    def _patient(self, run_id: str, patient_id: str) -> Patient | None:
        return self._session.scalars(
            select(Patient).where(Patient.run_id == run_id, Patient.patient_id == patient_id)
        ).first()

    def _referral_link_gap(self, run_id: str, referral_id: str) -> str | None:
        return self._session.scalar(
            select(WorkflowStatusEvent.care_gap_id)
            .where(
                WorkflowStatusEvent.run_id == run_id,
                WorkflowStatusEvent.referral_id == referral_id,
                WorkflowStatusEvent.care_gap_id.is_not(None),
            )
            .order_by(WorkflowStatusEvent.recorded_at)
            .limit(1)
        )

    def _referral_gap_ids(self, ref: Referral) -> list[str]:
        ids = set(
            self._session.scalars(
                select(CareGap.care_gap_id).where(
                    CareGap.run_id == ref.run_id,
                    CareGap.patient_id == ref.patient_id,
                    CareGap.subject_referral_id == ref.referral_id,
                )
            ).all()
        )
        linked = self._referral_link_gap(ref.run_id, ref.referral_id)
        if linked:
            ids.add(linked)
        return sorted(ids)

    # -- follow-ups ----------------------------------------------------------------------------

    def create_follow_up(
        self, gap_id: str, req: FollowUpCreateIn, *, on_recorded: OnRecorded | None = None
    ) -> FollowUpEventOut:
        with self._write():
            gr, er = self._latest_runs()
            # Serialise concurrent writes on the same gap (completion, duplicate resubmissions).
            gap = self._gap(gr.run_id, gap_id, lock=True)
            if gap is None:
                raise HTTPException(status_code=404, detail=f"Care gap '{gap_id}' not found")
            if not req.close_gap:
                now = _now()
                recent = self._session.scalars(
                    select(CareGapFollowUpEvent).where(
                        CareGapFollowUpEvent.run_id == gr.run_id,
                        CareGapFollowUpEvent.care_gap_id == gap_id,
                        CareGapFollowUpEvent.event_type.in_(_same_event_types(req.event_type)),
                        CareGapFollowUpEvent.recorded_at > now - DUPLICATE_SUBMIT_WINDOW,
                    )
                ).all()
                dup = next((e for e in recent if _is_resubmission(self._row_dict(e), req, now)), None)
                if dup is not None:
                    raise _duplicate(
                        "An identical follow-up was just recorded for this care gap.", dup.follow_up_id
                    )
            patient = self._patient(gr.run_id, gap.patient_id)
            if patient is None:
                raise HTTPException(status_code=404, detail=f"Patient '{gap.patient_id}' not found")
            rule = self._session.scalars(
                select(Rule).where(
                    Rule.rule_id == gap.rule_id, Rule.rule_version == gap.rule_version
                )
            ).first()
            rule_dict = self._row_dict(rule) if rule is not None else None

            event_type = req.event_type
            outcome_status: str | None = "noted"
            contact_consent_id: str | None = None
            suppression_reason: str | None = None

            if req.close_gap:
                ev_ref = (req.evidence_reference or "").strip()
                evidence: CompletionEvidence | None = None
                for model, id_col, factory in (
                    (IfhasScreening, IfhasScreening.screening_id, CompletionEvidence.from_screening),
                    (WellChildVisit, WellChildVisit.visit_id, CompletionEvidence.from_visit),
                    (Referral, Referral.referral_id, CompletionEvidence.from_referral),
                ):
                    row = self._session.scalars(
                        select(model).where(model.run_id == gr.run_id, id_col == ev_ref)
                    ).first()
                    if row is not None:
                        evidence = factory(self._row_dict(row))
                        break
                result = self._svc.validate_completion_evidence(
                    gap=self._row_dict(gap),
                    rule=rule_dict,
                    evidence=evidence,
                    documented_evidence=req.documented_evidence,
                    evidence_reference=req.evidence_reference,
                    as_of=er.reference_date,
                    current_evaluation=evaluate_current_rule(
                        get_cached_engine(),
                        PostgresReadRepository(self._session).get_patient_context(gap.patient_id),
                        rule_id=gap.rule_id,
                        rule_version=gap.rule_version,
                        as_of=er.reference_date,
                        look_ahead_days=er.look_ahead_days,
                    ),
                )
                if not result.accepted:
                    raise HTTPException(status_code=422, detail=result.message)
                setattr(gap, result.closed_by_field, result.evidence_id)
                gap.status = "closed_completed"
                gap.closed_date = er.reference_date
                outcome_status = "completed"

            if req.event_type == "outreach_attempted":
                consents = [
                    self._row_dict(c)
                    for c in self._session.scalars(
                        select(Consent).where(
                            Consent.run_id == gr.run_id, Consent.patient_id == gap.patient_id
                        )
                    ).all()
                ]
                patient_evals = [
                    self._row_dict(e)
                    for e in self._session.scalars(
                        select(EligibilityEvaluation).where(
                            EligibilityEvaluation.run_id == gr.run_id,
                            EligibilityEvaluation.evaluation_run_id == er.evaluation_run_id,
                            EligibilityEvaluation.patient_id == gap.patient_id,
                            EligibilityEvaluation.rule_id == gap.rule_id,
                        )
                    ).all()
                ]
                allowed, consent_id, blocked_reason = self._svc.evaluate_outreach_consent(
                    patient=self._row_dict(patient),
                    consents=consents,
                    rule_meta=rule_dict,
                    care_gap=self._row_dict(gap),
                    evaluations=patient_evals,
                )
                event_type, outcome_status, contact_consent_id, suppression_reason = (
                    self._svc.outreach_attempt_outcome(
                        allowed=allowed, consent_id=consent_id, blocked_reason=blocked_reason
                    )
                )

            fup = self._add_gap_event(
                _gap_event_row(
                    run_id=gr.run_id,
                    patient_id=gap.patient_id,
                    care_gap_id=gap_id,
                    event_type=event_type,
                    outcome_status=outcome_status,
                    documented_evidence=req.documented_evidence,
                    evidence_reference=req.evidence_reference,
                    contact_consent_id=contact_consent_id,
                    suppression_reason=suppression_reason,
                    recorded_by=req.recorded_by,
                    recorded_at=_now(),
                    note=req.note,
                )
            )
            out = _to_follow_up_out(self._row_dict(fup))
            if on_recorded is not None:
                on_recorded(out, self._session)  # same transaction: raising rolls back the event
        return out

    def list_follow_ups(self, gap_id: str, limit: int, offset: int) -> PaginatedFollowUpEventsOut:
        with self._read():
            gr, _ = self._latest_runs()
            if self._gap(gr.run_id, gap_id) is None:
                raise HTTPException(status_code=404, detail=f"Care gap '{gap_id}' not found")
            rows = [
                self._row_dict(f)
                for f in self._session.scalars(
                    select(CareGapFollowUpEvent).where(
                        CareGapFollowUpEvent.run_id == gr.run_id,
                        CareGapFollowUpEvent.care_gap_id == gap_id,
                    )
                ).all()
            ]
        items = _sorted_follow_ups(rows)
        return PaginatedFollowUpEventsOut(
            total=len(items), limit=limit, offset=offset, items=items[offset : offset + limit]
        )

    # -- appointments --------------------------------------------------------------------------

    def list_appointments(
        self,
        patient_id: str | None,
        care_gap_id: str | None,
        status: str | None,
        limit: int,
        offset: int,
        patient_ids: frozenset[str] | None = None,
    ) -> PaginatedAppointmentsOut:
        with self._read():
            gr, _ = self._latest_runs()
            stmt = select(Appointment).where(Appointment.run_id == gr.run_id)
            if patient_ids is not None:
                stmt = stmt.where(Appointment.patient_id.in_(sorted(patient_ids)))
            if patient_id is not None:
                stmt = stmt.where(Appointment.patient_id == patient_id)
            if care_gap_id is not None:
                stmt = stmt.where(Appointment.care_gap_id == care_gap_id)
            if status is not None:
                stmt = stmt.where(Appointment.status == status)
            total = int(
                self._session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
            )
            page = self._session.scalars(
                stmt.order_by(Appointment.scheduled_datetime.desc(), Appointment.appointment_id)
                .limit(limit)
                .offset(offset)
            ).all()
            items = [_to_appointment_out(self._row_dict(a)) for a in page]
        return PaginatedAppointmentsOut(
            is_synthetic=True, total=total, limit=limit, offset=offset, items=items
        )

    def get_appointment_patient_id(self, appointment_id: str) -> str | None:
        with self._read():
            gr, _ = self._latest_runs()
            return self._session.scalar(select(Appointment.patient_id).where(
                Appointment.run_id == gr.run_id, Appointment.appointment_id == appointment_id))

    def get_referral_patient_id(self, referral_id: str) -> str | None:
        with self._read():
            gr, _ = self._latest_runs()
            return self._session.scalar(select(Referral.patient_id).where(
                Referral.run_id == gr.run_id, Referral.referral_id == referral_id))

    def create_appointment(self, req: AppointmentCreateIn) -> AppointmentOut:
        with self._write():
            gr, _ = self._latest_runs()
            if self._patient(gr.run_id, req.patient_id) is None:
                raise HTTPException(status_code=404, detail=f"Patient '{req.patient_id}' not found")
            fsp = self._session.scalars(
                select(FacilityServiceProfile).where(
                    FacilityServiceProfile.run_id == gr.run_id,
                    FacilityServiceProfile.profile_id == req.profile_id,
                )
            ).first()
            if fsp is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"Facility service profile '{req.profile_id}' not found",
                )
            if req.care_gap_id is not None and self._gap(gr.run_id, req.care_gap_id, req.patient_id) is None:
                raise HTTPException(
                    status_code=404, detail=f"Care gap '{req.care_gap_id}' not found for patient"
                )
            self._lock("SYNTH-APT")  # serialises the duplicate check with concurrent creates
            dup = self._session.scalar(
                select(Appointment.appointment_id).where(
                    Appointment.run_id == gr.run_id,
                    Appointment.patient_id == req.patient_id,
                    Appointment.profile_id == req.profile_id,
                    Appointment.scheduled_datetime == req.scheduled_datetime,
                    Appointment.appointment_type == req.appointment_type,
                    Appointment.status.in_(ACTIVE_APPOINTMENT_STATUSES),
                )
            )
            if dup is not None:
                raise _duplicate(
                    "An active appointment already exists for this patient, facility, type and time.", dup
                )
            apt = Appointment(
                appointment_id=self._next_id(Appointment, Appointment.appointment_id, "SYNTH-APT"),
                run_id=gr.run_id,
                patient_id=req.patient_id,
                is_synthetic=True,
                profile_id=req.profile_id,
                care_gap_id=req.care_gap_id,
                appointment_type=req.appointment_type,
                scheduled_datetime=req.scheduled_datetime,
                slot_type=req.slot_type,
                status="scheduled",
                booked_via=req.booked_via,
            )
            self._session.add(apt)
            self._session.flush()
            now = _now()
            self._add_workflow_event(
                _workflow_row(
                    run_id=gr.run_id,
                    patient_id=req.patient_id,
                    entity_type="appointment",
                    entity_id=apt.appointment_id,
                    care_gap_id=req.care_gap_id,
                    from_status=None,
                    to_status="scheduled",
                    scheduled_datetime=req.scheduled_datetime,
                    recorded_by=req.recorded_by,
                    recorded_at=now,
                    note=req.note,
                )
            )
            if req.care_gap_id is not None:
                self._add_gap_event(
                    _gap_event_row(
                        run_id=gr.run_id,
                        patient_id=req.patient_id,
                        care_gap_id=req.care_gap_id,
                        event_type="appointment_scheduled",
                        appointment_id=apt.appointment_id,
                        recorded_by=req.recorded_by,
                        recorded_at=now,
                        note=_transition_note("Appointment", apt.appointment_id, None, "scheduled", req.note),
                    )
                )
            out = _to_appointment_out(self._row_dict(apt))
        return out

    def update_appointment(self, appointment_id: str, req: AppointmentPatchIn) -> AppointmentOut:
        with self._write():
            gr, _ = self._latest_runs()
            apt = self._session.scalars(
                select(Appointment)
                .where(Appointment.run_id == gr.run_id, Appointment.appointment_id == appointment_id)
                .with_for_update()
            ).first()
            if apt is None:
                raise HTTPException(
                    status_code=404, detail=f"Appointment '{appointment_id}' not found"
                )
            _validation(self._svc.validate_appointment_transition, apt.status, req.status)
            old = apt.status
            apt.status = req.status
            if req.scheduled_datetime is not None:
                apt.scheduled_datetime = req.scheduled_datetime
            self._session.flush()
            now = _now()
            self._add_workflow_event(
                _workflow_row(
                    run_id=gr.run_id,
                    patient_id=apt.patient_id,
                    entity_type="appointment",
                    entity_id=appointment_id,
                    care_gap_id=apt.care_gap_id,
                    from_status=old,
                    to_status=req.status,
                    scheduled_datetime=apt.scheduled_datetime,
                    recorded_by=req.recorded_by,
                    recorded_at=now,
                    note=req.note,
                )
            )
            if apt.care_gap_id:
                self._add_gap_event(
                    _gap_event_row(
                        run_id=gr.run_id,
                        patient_id=apt.patient_id,
                        care_gap_id=apt.care_gap_id,
                        event_type="appointment_updated",
                        appointment_id=appointment_id,
                        recorded_by=req.recorded_by,
                        recorded_at=now,
                        note=_transition_note("Appointment", appointment_id, old, req.status, req.note),
                    )
                )
            out = _to_appointment_out(self._row_dict(apt))
        return out

    def _workflow_history(self, entity_type: str, entity_id: str) -> WorkflowHistoryOut:
        model, id_col, label = (
            (Appointment, Appointment.appointment_id, "Appointment")
            if entity_type == "appointment"
            else (Referral, Referral.referral_id, "Referral")
        )
        ev_col = (
            WorkflowStatusEvent.appointment_id
            if entity_type == "appointment"
            else WorkflowStatusEvent.referral_id
        )
        with self._read():
            gr, _ = self._latest_runs()
            if self._session.scalar(select(id_col).where(model.run_id == gr.run_id, id_col == entity_id)) is None:
                raise HTTPException(status_code=404, detail=f"{label} '{entity_id}' not found")
            rows = [
                self._row_dict(e)
                for e in self._session.scalars(
                    select(WorkflowStatusEvent).where(
                        WorkflowStatusEvent.run_id == gr.run_id, ev_col == entity_id
                    )
                ).all()
            ]
        return WorkflowHistoryOut(entity_type=entity_type, entity_id=entity_id, items=_sorted_workflow(rows))

    def get_appointment_history(self, appointment_id: str) -> WorkflowHistoryOut:
        return self._workflow_history("appointment", appointment_id)

    # -- referrals -----------------------------------------------------------------------------

    def list_referrals(
        self,
        patient_id: str | None,
        status: str | None,
        limit: int,
        offset: int,
        patient_ids: frozenset[str] | None = None,
    ) -> PaginatedReferralsOut:
        with self._read():
            gr, _ = self._latest_runs()
            stmt = select(Referral).where(Referral.run_id == gr.run_id)
            if patient_ids is not None:
                stmt = stmt.where(Referral.patient_id.in_(sorted(patient_ids)))
            if patient_id is not None:
                stmt = stmt.where(Referral.patient_id == patient_id)
            if status is not None:
                stmt = stmt.where(Referral.status == status)
            total = int(
                self._session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
            )
            page = self._session.scalars(
                stmt.order_by(Referral.trigger_date.desc(), Referral.referral_id)
                .limit(limit)
                .offset(offset)
            ).all()
            items = [_to_referral_out(self._row_dict(r)) for r in page]
        return PaginatedReferralsOut(
            is_synthetic=True, total=total, limit=limit, offset=offset, items=items
        )

    def create_referral(self, req: ReferralCreateIn) -> ReferralOut:
        with self._write():
            gr, _ = self._latest_runs()
            if self._patient(gr.run_id, req.patient_id) is None:
                raise HTTPException(status_code=404, detail=f"Patient '{req.patient_id}' not found")
            rule = self._session.scalars(
                select(Rule).where(
                    Rule.rule_id == req.trigger_rule_id,
                    Rule.rule_version == req.trigger_rule_version,
                )
            ).first()
            if rule is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"Rule '{req.trigger_rule_id}' v'{req.trigger_rule_version}' not found",
                )
            if req.target_profile_id is not None and self._session.scalar(
                select(FacilityServiceProfile.profile_id).where(
                    FacilityServiceProfile.run_id == gr.run_id,
                    FacilityServiceProfile.profile_id == req.target_profile_id,
                )
            ) is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"Target facility service profile '{req.target_profile_id}' not found",
                )
            for ref_id, model, id_col, label in (
                (req.ifhas_screening_id, IfhasScreening, IfhasScreening.screening_id, "IFHAS screening"),
                (req.well_child_visit_id, WellChildVisit, WellChildVisit.visit_id, "Well-child visit"),
                (req.assessment_id, Assessment, Assessment.assessment_id, "Assessment"),
            ):
                if ref_id is not None and self._session.scalar(
                    select(id_col).where(
                        model.run_id == gr.run_id,
                        model.patient_id == req.patient_id,
                        id_col == ref_id,
                    )
                ) is None:
                    raise HTTPException(status_code=404, detail=f"{label} '{ref_id}' not found for patient")
            if req.care_gap_id is not None and self._gap(gr.run_id, req.care_gap_id, req.patient_id) is None:
                raise HTTPException(
                    status_code=404, detail=f"Care gap '{req.care_gap_id}' not found for patient"
                )
            _validation(
                self._svc.validate_referral_create,
                ifhas_screening_id=req.ifhas_screening_id,
                well_child_visit_id=req.well_child_visit_id,
                assessment_id=req.assessment_id,
                status=req.status,
                trigger_date=req.trigger_date,
                initiated_date=req.initiated_date,
                completed_date=None,
            )
            self._lock("SYNTH-REF")  # serialises the duplicate check with concurrent creates
            dup = self._session.scalar(
                select(Referral.referral_id).where(
                    Referral.run_id == gr.run_id,
                    Referral.patient_id == req.patient_id,
                    Referral.trigger_rule_id == req.trigger_rule_id,
                    Referral.trigger_rule_version == req.trigger_rule_version,
                    Referral.referral_target == req.referral_target,
                    Referral.status.in_(ACTIVE_REFERRAL_STATUSES),
                )
            )
            if dup is not None:
                raise _duplicate("An active referral already exists for this patient, rule and target.", dup)
            ref = Referral(
                referral_id=self._next_id(Referral, Referral.referral_id, "SYNTH-REF"),
                run_id=gr.run_id,
                patient_id=req.patient_id,
                is_synthetic=True,
                ifhas_screening_id=req.ifhas_screening_id,
                well_child_visit_id=req.well_child_visit_id,
                assessment_id=req.assessment_id,
                trigger_rule_id=req.trigger_rule_id,
                trigger_rule_version=req.trigger_rule_version,
                referral_target=req.referral_target,
                target_profile_id=req.target_profile_id,
                trigger_date=req.trigger_date,
                initiated_date=req.initiated_date,
                completed_date=None,
                status=req.status,
            )
            self._session.add(ref)
            self._session.flush()
            now = _now()
            self._add_workflow_event(
                _workflow_row(
                    run_id=gr.run_id,
                    patient_id=req.patient_id,
                    entity_type="referral",
                    entity_id=ref.referral_id,
                    care_gap_id=req.care_gap_id,
                    from_status=None,
                    to_status=req.status,
                    initiated_date=req.initiated_date,
                    recorded_by=req.recorded_by,
                    recorded_at=now,
                    note=req.note,
                )
            )
            if req.care_gap_id is not None:
                self._add_gap_event(
                    _gap_event_row(
                        run_id=gr.run_id,
                        patient_id=req.patient_id,
                        care_gap_id=req.care_gap_id,
                        event_type="referral_created",
                        referral_id=ref.referral_id,
                        recorded_by=req.recorded_by,
                        recorded_at=now,
                        note=_transition_note("Referral", ref.referral_id, None, req.status, req.note),
                    )
                )
            out = _to_referral_out(self._row_dict(ref))
        return out

    def update_referral(self, referral_id: str, req: ReferralPatchIn) -> ReferralOut:
        with self._write():
            gr, _ = self._latest_runs()
            ref = self._session.scalars(
                select(Referral)
                .where(Referral.run_id == gr.run_id, Referral.referral_id == referral_id)
                .with_for_update()
            ).first()
            if ref is None:
                raise HTTPException(status_code=404, detail=f"Referral '{referral_id}' not found")
            new_init = req.initiated_date if req.initiated_date is not None else ref.initiated_date
            new_comp = req.completed_date if req.completed_date is not None else ref.completed_date
            _validation(
                self._svc.validate_referral_transition,
                ref.status,
                req.status,
                trigger_date=ref.trigger_date,
                initiated_date=new_init,
                completed_date=new_comp,
            )
            old = ref.status
            ref.status = req.status
            ref.initiated_date = new_init
            ref.completed_date = new_comp
            self._session.flush()
            now = _now()
            self._add_workflow_event(
                _workflow_row(
                    run_id=gr.run_id,
                    patient_id=ref.patient_id,
                    entity_type="referral",
                    entity_id=referral_id,
                    care_gap_id=self._referral_link_gap(gr.run_id, referral_id),
                    from_status=old,
                    to_status=req.status,
                    initiated_date=new_init,
                    completed_date=new_comp,
                    recorded_by=req.recorded_by,
                    recorded_at=now,
                    note=req.note,
                )
            )
            for gap_id in self._referral_gap_ids(ref):
                self._add_gap_event(
                    _gap_event_row(
                        run_id=gr.run_id,
                        patient_id=ref.patient_id,
                        care_gap_id=gap_id,
                        event_type="referral_updated",
                        referral_id=referral_id,
                        recorded_by=req.recorded_by,
                        recorded_at=now,
                        note=_transition_note("Referral", referral_id, old, req.status, req.note),
                    )
                )
            out = _to_referral_out(self._row_dict(ref))
        return out

    def get_referral_history(self, referral_id: str) -> WorkflowHistoryOut:
        return self._workflow_history("referral", referral_id)

    def get_patient_activity(self, patient_id: str) -> PatientActivityOut:
        with self._read():
            gr, _ = self._latest_runs()
            if self._patient(gr.run_id, patient_id) is None:
                raise HTTPException(status_code=404, detail=f"Synthetic patient '{patient_id}' not found")
            fups = [
                self._row_dict(f)
                for f in self._session.scalars(
                    select(CareGapFollowUpEvent).where(
                        CareGapFollowUpEvent.run_id == gr.run_id,
                        CareGapFollowUpEvent.patient_id == patient_id,
                    )
                ).all()
            ]
            wfs = [
                self._row_dict(e)
                for e in self._session.scalars(
                    select(WorkflowStatusEvent).where(
                        WorkflowStatusEvent.run_id == gr.run_id,
                        WorkflowStatusEvent.patient_id == patient_id,
                    )
                ).all()
            ]
        return PatientActivityOut(
            patient_id=patient_id,
            follow_up_events=_sorted_follow_ups(fups),
            workflow_events=_sorted_workflow(wfs),
        )


    def create_review(self, gap_id: str, req: CareGapReviewIn) -> CareGapReviewOut:
        with self._write():
            gr, _ = self._latest_runs()
            gap = self._gap(gr.run_id, gap_id)
            if gap is None:
                raise HTTPException(status_code=404, detail=f"Care gap '{gap_id}' not found")
            _validate_review(req)
            rev = CareGapReview(
                review_id=self._next_id(CareGapReview, CareGapReview.review_id, "SYNTH-REV"),
                run_id=gr.run_id,
                care_gap_id=gap_id,
                is_synthetic=True,
                reviewer=req.reviewer,
                action=req.action,
                previous_priority=gap.priority_score,
                new_priority=None,
                reason=req.reason,
                reviewed_at=_now(),
            )
            self._session.add(rev)
            self._session.flush()
            out = _review_out(self._row_dict(rev))
        return out

    def list_reviews(self, gap_id: str) -> CareGapReviewsOut:
        with self._read():
            gr, _ = self._latest_runs()
            if self._gap(gr.run_id, gap_id) is None:
                raise HTTPException(status_code=404, detail=f"Care gap '{gap_id}' not found")
            rows = [
                self._row_dict(r)
                for r in self._session.scalars(
                    select(CareGapReview).where(
                        CareGapReview.run_id == gr.run_id, CareGapReview.care_gap_id == gap_id
                    )
                ).all()
            ]
        return CareGapReviewsOut(
            care_gap_id=gap_id,
            items=[_review_out(r) for r in sorted(rows, key=lambda x: (x["reviewed_at"], x["review_id"]))],
        )


def postgres_gap_workflow_events(
    session: Session, *, run_id: str, care_gap_id: str, appointment_ids: set[str], referral_ids: set[str]
) -> list[dict[str, Any]]:
    """Workflow events for a care gap's linked appointments/referrals (care-gap detail)."""
    conds = [WorkflowStatusEvent.care_gap_id == care_gap_id]
    if appointment_ids:
        conds.append(WorkflowStatusEvent.appointment_id.in_(appointment_ids))
    if referral_ids:
        conds.append(WorkflowStatusEvent.referral_id.in_(referral_ids))
    return [
        {col.name: getattr(e, col.name) for col in e.__table__.columns}
        for e in session.scalars(
            select(WorkflowStatusEvent).where(WorkflowStatusEvent.run_id == run_id, or_(*conds))
        ).all()
    ]
