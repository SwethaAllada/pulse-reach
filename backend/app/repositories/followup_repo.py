"""Follow-up, appointment, and referral write repositories (`T-09`)."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Protocol

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.clinical import Rule
from app.models.synthetic import (
    Appointment,
    Assessment,
    CareGap,
    CareGapFollowUpEvent,
    Consent,
    EligibilityEvaluation,
    EvaluationRun,
    FacilityServiceProfile,
    GenerationRun,
    IfhasScreening,
    Patient,
    Referral,
    WellChildVisit,
)
from app.repositories.read_repo import get_cached_bundle, get_cached_dataset, get_cached_index
from app.schemas.v1 import (
    AppointmentCreateIn,
    AppointmentOut,
    AppointmentPatchIn,
    FollowUpCreateIn,
    FollowUpEventOut,
    PaginatedAppointmentsOut,
    PaginatedReferralsOut,
    ReferralCreateIn,
    ReferralOut,
    ReferralPatchIn,
)
from app.services.followup import FollowUpService, FollowUpValidationError

_MEMORY_FOLLOW_UP_EVENTS: list[dict[str, Any]] = []


def get_memory_follow_up_events(
    care_gap_id: str,
    *,
    run_id: str | None = None,
    patient_id: str | None = None,
) -> list[dict[str, Any]]:
    return [
        e
        for e in _MEMORY_FOLLOW_UP_EVENTS
        if e["care_gap_id"] == care_gap_id
        and (run_id is None or e["run_id"] == run_id)
        and (patient_id is None or e["patient_id"] == patient_id)
    ]


def _next_synth_id(prefix: str, max_existing: str | None) -> str:
    if not max_existing:
        return f"{prefix}-000001"
    try:
        num = int(max_existing.rsplit("-", 1)[-1])
    except ValueError:
        num = 0
    return f"{prefix}-{num + 1:06d}"


class FollowUpRepository(Protocol):
    def create_follow_up(self, gap_id: str, req: FollowUpCreateIn) -> FollowUpEventOut: ...
    def list_appointments(
        self, patient_id: str | None, care_gap_id: str | None, status: str | None, limit: int, offset: int
    ) -> PaginatedAppointmentsOut: ...
    def create_appointment(self, req: AppointmentCreateIn) -> AppointmentOut: ...
    def update_appointment(self, appointment_id: str, req: AppointmentPatchIn) -> AppointmentOut: ...
    def list_referrals(
        self, patient_id: str | None, status: str | None, limit: int, offset: int
    ) -> PaginatedReferralsOut: ...
    def create_referral(self, req: ReferralCreateIn) -> ReferralOut: ...
    def update_referral(self, referral_id: str, req: ReferralPatchIn) -> ReferralOut: ...


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
        is_synthetic=bool(f.get("is_synthetic", True)),
    )


class MemoryFollowUpRepository:
    def __init__(self, service: FollowUpService | None = None) -> None:
        self._svc = service or FollowUpService()

    def create_follow_up(self, gap_id: str, req: FollowUpCreateIn) -> FollowUpEventOut:
        ds = get_cached_dataset()
        idx = get_cached_index()
        gap = next((g for g in ds.care_gaps if g["care_gap_id"] == gap_id), None)
        if gap is None:
            raise HTTPException(status_code=404, detail=f"Care gap '{gap_id}' not found")
        patient = idx.patients_by_id.get(gap["patient_id"])
        if patient is None:
            raise HTTPException(status_code=404, detail=f"Patient '{gap['patient_id']}' not found")

        rule_meta = next(
            (
                r
                for r in get_cached_bundle().rules
                if r["rule_id"] == gap["rule_id"] and r["rule_version"] == gap["rule_version"]
            ),
            {"rule_id": gap["rule_id"], "rule_version": gap["rule_version"], "pathway": "ifhas"},
        )
        event_type = req.event_type
        outcome_status: str | None = "noted"
        contact_consent_id: str | None = None
        suppression_reason: str | None = None

        if req.close_gap:
            if gap["status"] != "open":
                raise HTTPException(
                    status_code=422,
                    detail=f"Cannot close care gap '{gap_id}' with status '{gap['status']}'.",
                )
            try:
                self._svc.validate_gap_completion(
                    documented_evidence=req.documented_evidence,
                    evidence_reference=req.evidence_reference,
                )
            except FollowUpValidationError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc

            ev_ref = req.evidence_reference.strip()
            pid = gap["patient_id"]
            if any(s["screening_id"] == ev_ref and s["patient_id"] == pid for s in ds.ifhas_screenings):
                gap["closed_by_ifhas_screening_id"] = ev_ref
            elif any(v["visit_id"] == ev_ref and v["patient_id"] == pid for v in ds.well_child_visits):
                gap["closed_by_well_child_visit_id"] = ev_ref
            elif any(r["referral_id"] == ev_ref and r["patient_id"] == pid for r in ds.referrals):
                gap["closed_by_referral_id"] = ev_ref
            else:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"evidence_reference '{ev_ref}' must reference an existing screening, "
                        f"well-child visit, or referral for patient '{pid}'."
                    ),
                )
            gap["status"] = "closed_completed"
            gap["closed_date"] = ds.evaluation_run["reference_date"]
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
                pathway=rule_meta["pathway"],
                rule_id=gap["rule_id"],
                rule_meta=rule_meta,
                care_gap=gap,
                evaluations=patient_evals,
            )
            if allowed and consent_id:
                contact_consent_id = consent_id
                outcome_status = "sent"
            else:
                event_type = "outreach_suppressed"
                outcome_status = "suppressed"
                suppression_reason = blocked_reason or "contact_consent_missing"

        fup_id = f"SYNTH-FUP-{len(_MEMORY_FOLLOW_UP_EVENTS) + 1:06d}"
        row = {
            "follow_up_id": fup_id,
            "run_id": ds.generation_run["run_id"],
            "patient_id": gap["patient_id"],
            "care_gap_id": gap_id,
            "is_synthetic": True,
            "event_type": event_type,
            "outcome_status": outcome_status,
            "documented_evidence": req.documented_evidence,
            "evidence_reference": req.evidence_reference,
            "contact_consent_id": contact_consent_id,
            "suppression_reason": suppression_reason,
            "recorded_by": req.recorded_by,
            "recorded_at": datetime.now(timezone.utc),
            "note": req.note,
        }
        _MEMORY_FOLLOW_UP_EVENTS.append(row)
        return _to_follow_up_out(row)

    def list_appointments(
        self,
        patient_id: str | None,
        care_gap_id: str | None,
        status: str | None,
        limit: int,
        offset: int,
    ) -> PaginatedAppointmentsOut:
        apts = get_cached_dataset().appointments
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

    def create_appointment(self, req: AppointmentCreateIn) -> AppointmentOut:
        ds = get_cached_dataset()
        idx = get_cached_index()
        if req.patient_id not in idx.patients_by_id:
            raise HTTPException(status_code=404, detail=f"Patient '{req.patient_id}' not found")
        if not any(f["profile_id"] == req.profile_id for f in ds.facility_service_profiles):
            raise HTTPException(
                status_code=404, detail=f"Facility service profile '{req.profile_id}' not found"
            )
        if req.care_gap_id is not None:
            gap = next(
                (
                    g
                    for g in ds.care_gaps
                    if g["care_gap_id"] == req.care_gap_id and g["patient_id"] == req.patient_id
                ),
                None,
            )
            if gap is None:
                raise HTTPException(
                    status_code=404, detail=f"Care gap '{req.care_gap_id}' not found for patient"
                )
        apt_id = f"SYNTH-APT-{len(ds.appointments) + 1:06d}"
        row = {
            "appointment_id": apt_id,
            "run_id": ds.generation_run["run_id"],
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
        return _to_appointment_out(row)

    def update_appointment(self, appointment_id: str, req: AppointmentPatchIn) -> AppointmentOut:
        ds = get_cached_dataset()
        apt = next((a for a in ds.appointments if a["appointment_id"] == appointment_id), None)
        if apt is None:
            raise HTTPException(status_code=404, detail=f"Appointment '{appointment_id}' not found")
        try:
            self._svc.validate_appointment_transition(apt["status"], req.status)
        except FollowUpValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        apt["status"] = req.status
        if req.scheduled_datetime is not None:
            apt["scheduled_datetime"] = req.scheduled_datetime
        return _to_appointment_out(apt)

    def list_referrals(
        self,
        patient_id: str | None,
        status: str | None,
        limit: int,
        offset: int,
    ) -> PaginatedReferralsOut:
        refs = get_cached_dataset().referrals
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
        ds = get_cached_dataset()
        idx = get_cached_index()
        if req.patient_id not in idx.patients_by_id:
            raise HTTPException(status_code=404, detail=f"Patient '{req.patient_id}' not found")
        if not any(
            r["rule_id"] == req.trigger_rule_id and r["rule_version"] == req.trigger_rule_version
            for r in get_cached_bundle().rules
        ):
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
        if req.ifhas_screening_id is not None and not any(
            s["screening_id"] == req.ifhas_screening_id and s["patient_id"] == req.patient_id
            for s in ds.ifhas_screenings
        ):
            raise HTTPException(
                status_code=404,
                detail=f"IFHAS screening '{req.ifhas_screening_id}' not found for patient",
            )
        if req.well_child_visit_id is not None and not any(
            v["visit_id"] == req.well_child_visit_id and v["patient_id"] == req.patient_id
            for v in ds.well_child_visits
        ):
            raise HTTPException(
                status_code=404,
                detail=f"Well-child visit '{req.well_child_visit_id}' not found for patient",
            )
        if req.assessment_id is not None and not any(
            a["assessment_id"] == req.assessment_id and a["patient_id"] == req.patient_id
            for a in ds.assessments
        ):
            raise HTTPException(
                status_code=404,
                detail=f"Assessment '{req.assessment_id}' not found for patient",
            )
        try:
            self._svc.validate_referral_create(
                ifhas_screening_id=req.ifhas_screening_id,
                well_child_visit_id=req.well_child_visit_id,
                assessment_id=req.assessment_id,
                status=req.status,
                trigger_date=req.trigger_date,
                initiated_date=req.initiated_date,
                completed_date=None,
            )
        except FollowUpValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        ref_id = f"SYNTH-REF-{len(ds.referrals) + 1:06d}"
        row = {
            "referral_id": ref_id,
            "run_id": ds.generation_run["run_id"],
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
        return _to_referral_out(row)

    def update_referral(self, referral_id: str, req: ReferralPatchIn) -> ReferralOut:
        ds = get_cached_dataset()
        ref = next((r for r in ds.referrals if r["referral_id"] == referral_id), None)
        if ref is None:
            raise HTTPException(status_code=404, detail=f"Referral '{referral_id}' not found")
        new_init = req.initiated_date if req.initiated_date is not None else ref.get("initiated_date")
        new_comp = req.completed_date if req.completed_date is not None else ref.get("completed_date")
        try:
            self._svc.validate_referral_transition(
                ref["status"],
                req.status,
                trigger_date=ref["trigger_date"],
                initiated_date=new_init,
                completed_date=new_comp,
            )
        except FollowUpValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        ref["status"] = req.status
        ref["initiated_date"] = new_init
        ref["completed_date"] = new_comp
        return _to_referral_out(ref)


class PostgresFollowUpRepository:
    def __init__(self, session: Session, service: FollowUpService | None = None) -> None:
        self._session = session
        self._svc = service or FollowUpService()

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

    def create_follow_up(self, gap_id: str, req: FollowUpCreateIn) -> FollowUpEventOut:
        try:
            gr, er = self._latest_runs()
            gap = self._session.scalars(
                select(CareGap).where(CareGap.run_id == gr.run_id, CareGap.care_gap_id == gap_id)
            ).first()
            if gap is None:
                raise HTTPException(status_code=404, detail=f"Care gap '{gap_id}' not found")
            patient = self._session.scalars(
                select(Patient).where(
                    Patient.run_id == gr.run_id, Patient.patient_id == gap.patient_id
                )
            ).first()
            if patient is None:
                raise HTTPException(status_code=404, detail=f"Patient '{gap.patient_id}' not found")
            rule = self._session.scalars(
                select(Rule).where(
                    Rule.rule_id == gap.rule_id, Rule.rule_version == gap.rule_version
                )
            ).first()
            pathway = rule.pathway if rule is not None else "ifhas"

            event_type = req.event_type
            outcome_status: str | None = "noted"
            contact_consent_id: str | None = None
            suppression_reason: str | None = None

            if req.close_gap:
                if gap.status != "open":
                    raise HTTPException(
                        status_code=422,
                        detail=f"Cannot close care gap '{gap_id}' with status '{gap.status}'.",
                    )
                try:
                    self._svc.validate_gap_completion(
                        documented_evidence=req.documented_evidence,
                        evidence_reference=req.evidence_reference,
                    )
                except FollowUpValidationError as exc:
                    raise HTTPException(status_code=422, detail=str(exc)) from exc
                ev_ref = req.evidence_reference.strip()
                scr = self._session.scalars(
                    select(IfhasScreening).where(
                        IfhasScreening.run_id == gr.run_id,
                        IfhasScreening.patient_id == gap.patient_id,
                        IfhasScreening.screening_id == ev_ref,
                    )
                ).first()
                vis = (
                    None
                    if scr is not None
                    else self._session.scalars(
                        select(WellChildVisit).where(
                            WellChildVisit.run_id == gr.run_id,
                            WellChildVisit.patient_id == gap.patient_id,
                            WellChildVisit.visit_id == ev_ref,
                        )
                    ).first()
                )
                ref = (
                    None
                    if (scr is not None or vis is not None)
                    else self._session.scalars(
                        select(Referral).where(
                            Referral.run_id == gr.run_id,
                            Referral.patient_id == gap.patient_id,
                            Referral.referral_id == ev_ref,
                        )
                    ).first()
                )
                if scr is not None:
                    gap.closed_by_ifhas_screening_id = ev_ref
                elif vis is not None:
                    gap.closed_by_well_child_visit_id = ev_ref
                elif ref is not None:
                    gap.closed_by_referral_id = ev_ref
                else:
                    raise HTTPException(
                        status_code=422,
                        detail=(
                            f"evidence_reference '{ev_ref}' must reference an existing screening, "
                            f"well-child visit, or referral for patient '{gap.patient_id}'."
                        ),
                    )
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
                    pathway=pathway,
                    rule_id=gap.rule_id,
                    rule_meta=self._row_dict(rule) if rule is not None else None,
                    care_gap=self._row_dict(gap),
                    evaluations=patient_evals,
                )
                if allowed and consent_id:
                    contact_consent_id = consent_id
                    outcome_status = "sent"
                else:
                    event_type = "outreach_suppressed"
                    outcome_status = "suppressed"
                    suppression_reason = blocked_reason or "contact_consent_missing"

            max_existing = self._session.scalar(
                select(func.max(CareGapFollowUpEvent.follow_up_id))
            )
            fup = CareGapFollowUpEvent(
                follow_up_id=_next_synth_id("SYNTH-FUP", max_existing),
                run_id=gr.run_id,
                patient_id=gap.patient_id,
                care_gap_id=gap_id,
                is_synthetic=True,
                event_type=event_type,
                outcome_status=outcome_status,
                documented_evidence=req.documented_evidence,
                evidence_reference=req.evidence_reference,
                contact_consent_id=contact_consent_id,
                suppression_reason=suppression_reason,
                recorded_by=req.recorded_by,
                recorded_at=datetime.now(timezone.utc),
                note=req.note,
            )
            self._session.add(fup)
            self._session.commit()
            self._session.refresh(fup)
        except SQLAlchemyError as exc:
            self._session.rollback()
            raise HTTPException(status_code=503, detail="PostgreSQL write failed.") from exc
        return _to_follow_up_out(self._row_dict(fup))

    def list_appointments(
        self,
        patient_id: str | None,
        care_gap_id: str | None,
        status: str | None,
        limit: int,
        offset: int,
    ) -> PaginatedAppointmentsOut:
        try:
            gr, _ = self._latest_runs()
            stmt = select(Appointment).where(Appointment.run_id == gr.run_id)
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
        except SQLAlchemyError as exc:
            raise HTTPException(status_code=503, detail=f"PostgreSQL query failed: {exc}") from exc
        return PaginatedAppointmentsOut(
            is_synthetic=True,
            total=total,
            limit=limit,
            offset=offset,
            items=[_to_appointment_out(self._row_dict(a)) for a in page],
        )

    def create_appointment(self, req: AppointmentCreateIn) -> AppointmentOut:
        try:
            gr, _ = self._latest_runs()
            p = self._session.scalars(
                select(Patient).where(
                    Patient.run_id == gr.run_id, Patient.patient_id == req.patient_id
                )
            ).first()
            if p is None:
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
            if req.care_gap_id is not None:
                gap = self._session.scalars(
                    select(CareGap).where(
                        CareGap.run_id == gr.run_id,
                        CareGap.care_gap_id == req.care_gap_id,
                        CareGap.patient_id == req.patient_id,
                    )
                ).first()
                if gap is None:
                    raise HTTPException(
                        status_code=404,
                        detail=f"Care gap '{req.care_gap_id}' not found for patient",
                    )
            max_existing = self._session.scalar(select(func.max(Appointment.appointment_id)))
            apt = Appointment(
                appointment_id=_next_synth_id("SYNTH-APT", max_existing),
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
            self._session.commit()
            self._session.refresh(apt)
        except SQLAlchemyError as exc:
            self._session.rollback()
            raise HTTPException(status_code=503, detail="PostgreSQL write failed.") from exc
        return _to_appointment_out(self._row_dict(apt))

    def update_appointment(self, appointment_id: str, req: AppointmentPatchIn) -> AppointmentOut:
        try:
            gr, _ = self._latest_runs()
            apt = self._session.scalars(
                select(Appointment).where(
                    Appointment.run_id == gr.run_id,
                    Appointment.appointment_id == appointment_id,
                )
            ).first()
            if apt is None:
                raise HTTPException(
                    status_code=404, detail=f"Appointment '{appointment_id}' not found"
                )
            try:
                self._svc.validate_appointment_transition(apt.status, req.status)
            except FollowUpValidationError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            apt.status = req.status
            if req.scheduled_datetime is not None:
                apt.scheduled_datetime = req.scheduled_datetime
            self._session.commit()
            self._session.refresh(apt)
        except SQLAlchemyError as exc:
            self._session.rollback()
            raise HTTPException(status_code=503, detail=f"PostgreSQL write failed: {exc}") from exc
        return _to_appointment_out(self._row_dict(apt))

    def list_referrals(
        self,
        patient_id: str | None,
        status: str | None,
        limit: int,
        offset: int,
    ) -> PaginatedReferralsOut:
        try:
            gr, _ = self._latest_runs()
            stmt = select(Referral).where(Referral.run_id == gr.run_id)
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
        except SQLAlchemyError as exc:
            raise HTTPException(status_code=503, detail=f"PostgreSQL query failed: {exc}") from exc
        return PaginatedReferralsOut(
            is_synthetic=True,
            total=total,
            limit=limit,
            offset=offset,
            items=[_to_referral_out(self._row_dict(r)) for r in page],
        )

    def create_referral(self, req: ReferralCreateIn) -> ReferralOut:
        try:
            gr, _ = self._latest_runs()
            p = self._session.scalars(
                select(Patient).where(
                    Patient.run_id == gr.run_id, Patient.patient_id == req.patient_id
                )
            ).first()
            if p is None:
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
            if req.target_profile_id is not None:
                fsp = self._session.scalars(
                    select(FacilityServiceProfile).where(
                        FacilityServiceProfile.run_id == gr.run_id,
                        FacilityServiceProfile.profile_id == req.target_profile_id,
                    )
                ).first()
                if fsp is None:
                    raise HTTPException(
                        status_code=404,
                        detail=f"Target facility service profile '{req.target_profile_id}' not found",
                    )
            if req.ifhas_screening_id is not None:
                scr = self._session.scalars(
                    select(IfhasScreening).where(
                        IfhasScreening.run_id == gr.run_id,
                        IfhasScreening.patient_id == req.patient_id,
                        IfhasScreening.screening_id == req.ifhas_screening_id,
                    )
                ).first()
                if scr is None:
                    raise HTTPException(
                        status_code=404,
                        detail=f"IFHAS screening '{req.ifhas_screening_id}' not found for patient",
                    )
            if req.well_child_visit_id is not None:
                vis = self._session.scalars(
                    select(WellChildVisit).where(
                        WellChildVisit.run_id == gr.run_id,
                        WellChildVisit.patient_id == req.patient_id,
                        WellChildVisit.visit_id == req.well_child_visit_id,
                    )
                ).first()
                if vis is None:
                    raise HTTPException(
                        status_code=404,
                        detail=f"Well-child visit '{req.well_child_visit_id}' not found for patient",
                    )
            if req.assessment_id is not None:
                asm = self._session.scalars(
                    select(Assessment).where(
                        Assessment.run_id == gr.run_id,
                        Assessment.patient_id == req.patient_id,
                        Assessment.assessment_id == req.assessment_id,
                    )
                ).first()
                if asm is None:
                    raise HTTPException(
                        status_code=404,
                        detail=f"Assessment '{req.assessment_id}' not found for patient",
                    )
            try:
                self._svc.validate_referral_create(
                    ifhas_screening_id=req.ifhas_screening_id,
                    well_child_visit_id=req.well_child_visit_id,
                    assessment_id=req.assessment_id,
                    status=req.status,
                    trigger_date=req.trigger_date,
                    initiated_date=req.initiated_date,
                    completed_date=None,
                )
            except FollowUpValidationError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            max_existing = self._session.scalar(select(func.max(Referral.referral_id)))
            ref = Referral(
                referral_id=_next_synth_id("SYNTH-REF", max_existing),
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
            self._session.commit()
            self._session.refresh(ref)
        except SQLAlchemyError as exc:
            self._session.rollback()
            raise HTTPException(status_code=503, detail="PostgreSQL write failed.") from exc
        return _to_referral_out(self._row_dict(ref))

    def update_referral(self, referral_id: str, req: ReferralPatchIn) -> ReferralOut:
        try:
            gr, _ = self._latest_runs()
            ref = self._session.scalars(
                select(Referral).where(
                    Referral.run_id == gr.run_id,
                    Referral.referral_id == referral_id,
                )
            ).first()
            if ref is None:
                raise HTTPException(status_code=404, detail=f"Referral '{referral_id}' not found")
            new_init = req.initiated_date if req.initiated_date is not None else ref.initiated_date
            new_comp = req.completed_date if req.completed_date is not None else ref.completed_date
            try:
                self._svc.validate_referral_transition(
                    ref.status,
                    req.status,
                    trigger_date=ref.trigger_date,
                    initiated_date=new_init,
                    completed_date=new_comp,
                )
            except FollowUpValidationError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            ref.status = req.status
            ref.initiated_date = new_init
            ref.completed_date = new_comp
            self._session.commit()
            self._session.refresh(ref)
        except SQLAlchemyError as exc:
            self._session.rollback()
            raise HTTPException(status_code=503, detail=f"PostgreSQL write failed: {exc}") from exc
        return _to_referral_out(self._row_dict(ref))
