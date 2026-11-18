"""FastAPI `/api/v1/*` router (`app.api.v1`).

Supports both `DATA_SOURCE=memory` (default deterministic demo mode) and `DATA_SOURCE=db`
(PostgreSQL-backed read repository) without ever silently falling back from DB to memory.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.core.config import settings
from app.db.deps import get_db_session
from app.repositories.followup_repo import (
    FollowUpRepository,
    MemoryFollowUpRepository,
    PostgresFollowUpRepository,
)
from app.repositories.read_repo import (
    MemoryReadRepository,
    PostgresReadRepository,
    ReadRepository,
    build_safe_input_snapshot_from_context,
    describe_reason,
    get_cached_bundle,
    get_cached_engine,
)
from app.schemas.v1 import (
    AppointmentCreateIn,
    AppointmentOut,
    AppointmentPatchIn,
    CareGapDetailOut,
    CareGapOut,
    DashboardSummaryOut,
    EvaluateRequestIn,
    EvaluationItemOut,
    EvaluationReasonOut,
    ExplanationOut,
    ExplanationRequestIn,
    FollowUpCreateIn,
    FollowUpEventOut,
    OutreachPreviewOut,
    OutreachPreviewRequestIn,
    PaginatedAppointmentsOut,
    PaginatedCareGapsOut,
    PaginatedFacilitiesOut,
    PaginatedPatientsOut,
    PaginatedReferralsOut,
    PaginatedRulesOut,
    PatientConsentsOut,
    PatientEvaluationsOut,
    PatientHistoryOut,
    PatientSummaryOut,
    ReferralCreateIn,
    ReferralOut,
    ReferralPatchIn,
    RuleDetailOut,
)
from app.services.evaluation.engine import ENGINE_VERSION
from app.services.explanation import (
    BoundedExplanationInput,
    ExplanationService,
    PrivacyViolationError,
)
from app.services.outreach import OutreachRuleNotFoundError, OutreachService

router = APIRouter(prefix="/api/v1", tags=["v1"])

_explanation_service = ExplanationService(llm_provider=None)
_outreach_service = OutreachService()


def get_read_repository() -> Iterator[ReadRepository]:
    """Resolve the active read repository from `settings.data_source`."""
    if settings.data_source == "memory":
        yield MemoryReadRepository()
        return
    for session in get_db_session():
        yield PostgresReadRepository(session)


def get_followup_repository() -> Iterator[FollowUpRepository]:
    """Resolve the active follow-up write repository from `settings.data_source`."""
    if settings.data_source == "memory":
        yield MemoryFollowUpRepository()
        return
    for session in get_db_session():
        yield PostgresFollowUpRepository(session)


@router.get("/dashboard/summary", response_model=DashboardSummaryOut)
def get_dashboard_summary(
    repo: ReadRepository = Depends(get_read_repository),
) -> DashboardSummaryOut:
    return repo.get_dashboard_summary()


_ALLOWED_PATIENTS_QUERY_PARAMS = frozenset(
    {
        "limit",
        "offset",
        "sex",
        "region_id",
        "pathway",
        "q",
        "sort_by",
        "sort_dir",
        "evaluation_status",
        "has_open_care_gaps",
        "history_status",
        "age_band",
    }
)


@router.get("/patients", response_model=PaginatedPatientsOut)
def list_patients(
    request: Request,
    limit: int = Query(default=25, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    sex: Literal["female", "male"] | None = Query(default=None),
    region_id: int | None = Query(default=None, ge=1, le=3),
    pathway: Literal["ifhas", "well_child"] | None = Query(default=None),
    q: str | None = Query(default=None),
    sort_by: Literal["patient_id", "family_name", "age", "open_gaps"] = Query(default="patient_id"),
    sort_dir: Literal["asc", "desc"] = Query(default="asc"),
    evaluation_status: Literal[
        "eligible",
        "not_eligible",
        "due",
        "upcoming",
        "overdue",
        "completed",
        "unknown",
        "insufficient_information",
        "requires_clinical_review",
    ] | None = Query(default=None),
    has_open_care_gaps: bool | None = Query(default=None),
    history_status: Literal["available", "partial", "not_available"] | None = Query(default=None),
    age_band: Literal["child", "adult_18_39", "adult_40_59", "adult_60_plus"] | None = Query(
        default=None
    ),
    repo: ReadRepository = Depends(get_read_repository),
) -> PaginatedPatientsOut:
    extra = set(request.query_params.keys()) - _ALLOWED_PATIENTS_QUERY_PARAMS
    if extra:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported query parameters: {sorted(extra)}",
        )
    return repo.list_patients(
        limit=limit,
        offset=offset,
        sex=sex,
        region_id=region_id,
        pathway=pathway,
        q=q,
        sort_by=sort_by,
        sort_dir=sort_dir,
        evaluation_status=evaluation_status,
        has_open_care_gaps=has_open_care_gaps,
        history_status=history_status,
        age_band=age_band,
    )


@router.get("/patients/{patient_id}", response_model=PatientSummaryOut)
def get_patient(
    patient_id: str,
    repo: ReadRepository = Depends(get_read_repository),
) -> PatientSummaryOut:
    p = repo.get_patient(patient_id)
    if p is None:
        raise HTTPException(status_code=404, detail=f"Synthetic patient '{patient_id}' not found")
    return p


@router.get("/patients/{patient_id}/evaluations", response_model=PatientEvaluationsOut)
def get_patient_evaluations(
    patient_id: str,
    repo: ReadRepository = Depends(get_read_repository),
) -> PatientEvaluationsOut:
    res = repo.get_patient_evaluations(patient_id)
    if res is None:
        raise HTTPException(status_code=404, detail=f"Synthetic patient '{patient_id}' not found")
    return res


@router.get("/patients/{patient_id}/history", response_model=PatientHistoryOut)
def get_patient_history(
    patient_id: str,
    repo: ReadRepository = Depends(get_read_repository),
) -> PatientHistoryOut:
    res = repo.get_patient_history(patient_id)
    if res is None:
        raise HTTPException(status_code=404, detail=f"Synthetic patient '{patient_id}' not found")
    return res


@router.get("/patients/{patient_id}/consents", response_model=PatientConsentsOut)
def get_patient_consents(
    patient_id: str,
    repo: ReadRepository = Depends(get_read_repository),
) -> PatientConsentsOut:
    res = repo.get_patient_consents(patient_id)
    if res is None:
        raise HTTPException(status_code=404, detail=f"Synthetic patient '{patient_id}' not found")
    return res


@router.post("/evaluations", response_model=PatientEvaluationsOut)
def run_evaluation(
    req: EvaluateRequestIn,
    repo: ReadRepository = Depends(get_read_repository),
) -> PatientEvaluationsOut:
    eval_run_id, ref_date, default_look_ahead = repo.get_evaluation_run_info()
    ctx = repo.get_patient_context(req.patient_id)
    if ctx is None:
        raise HTTPException(
            status_code=404, detail=f"Synthetic patient '{req.patient_id}' not found"
        )
    if req.look_ahead_days == default_look_ahead:
        cached = repo.get_patient_evaluations(req.patient_id)
        if cached is not None:
            return cached

    engine = get_cached_engine()
    summary = engine.evaluate_patient(
        ctx,
        reference_date=ref_date,
        look_ahead_days=req.look_ahead_days,
    )
    rule_meta = {r["rule_id"]: r for r in get_cached_bundle().rules}
    prior_rules = {s.rule_id for s in ctx.ifhas_screenings} | {
        v.rule_id for v in ctx.well_child_visits
    }
    referral_rules = {r.trigger_rule_id for r in ctx.referrals if r.trigger_rule_id}
    eval_items: list[EvaluationItemOut] = []
    eval_id_by_rule: dict[str, str] = {}
    for ord_ev, ev in enumerate(summary.evaluations, 1):
        eid = f"SYNTH-EVL-{ord_ev:06d}"
        eval_id_by_rule[ev.rule_id] = eid
        rm = rule_meta.get(ev.rule_id, {})
        eval_items.append(
            EvaluationItemOut(
                evaluation_id=eid,
                patient_id=req.patient_id,
                rule_id=ev.rule_id,
                rule_version=ev.rule_version,
                pathway=ev.pathway,
                rule_type=ev.rule_type,
                source_name=rm.get("source_name"),
                source_version=rm.get("source_version"),
                source_reference=rm.get("source_reference"),
                is_authoritative=bool(rm.get("is_authoritative", False)),
                requires_clinical_review=bool(rm.get("requires_clinical_review", False)),
                engine_version=ENGINE_VERSION,
                look_ahead_days=req.look_ahead_days,
                evaluation_status=ev.evaluation_status,
                reason_code=ev.reason_code,
                reason_detail=describe_reason(
                    ev.reason_code,
                    evaluation_status=ev.evaluation_status,
                ),
                next_due_date=ev.next_due_date,
                evaluated_at=ev.evaluated_at,
                input_snapshot=build_safe_input_snapshot_from_context(
                    ctx=ctx,
                    pathway=ev.pathway,
                    has_prior_activity=ev.rule_id in prior_rules,
                    has_referral=ev.rule_id in referral_rules,
                    reference_date=ref_date,
                ),
                reasons=[
                    EvaluationReasonOut(
                        reason_ordinal=i,
                        reason_code=r.reason_code,
                        reason_detail=describe_reason(
                            r.reason_code,
                            r.guard_id,
                            r.item_category,
                            r.item_code,
                        ),
                        guard_id=r.guard_id,
                        item_category=r.item_category,
                        item_code=r.item_code,
                    )
                    for i, r in enumerate(ev.reasons, 1)
                ],
            )
        )
    gap_items = [
        CareGapOut(
            care_gap_id=f"SYNTH-GAP-{i:06d}",
            patient_id=req.patient_id,
            evaluation_id=eval_id_by_rule[gf.rule_id],
            rule_id=gf.rule_id,
            rule_version=gf.rule_version,
            gap_type=gf.gap_type,
            status=gf.status,
            identified_date=gf.opened_date,
            closed_date=gf.closed_date,
            closed_by_consent_id=gf.closed_by_consent_id,
            closed_by_component_result_id=gf.closed_by_component_result_id,
            subject_ifhas_screening_id=gf.subject_ifhas_screening_id,
            subject_well_child_visit_id=gf.subject_well_child_visit_id,
            subject_referral_id=gf.subject_referral_id,
            is_synthetic=True,
        )
        for i, gf in enumerate(summary.care_gaps, 1)
    ]
    return PatientEvaluationsOut(
        is_synthetic=True,
        patient_id=req.patient_id,
        evaluation_run_id=eval_run_id,
        reference_date=summary.reference_date,
        evaluations=eval_items,
        care_gaps=gap_items,
    )


@router.get("/rules", response_model=PaginatedRulesOut)
def list_rules(
    pathway: Literal["ifhas", "well_child"] | None = Query(default=None),
    verification_status: Literal["verified", "reported", "unresolved"] | None = Query(
        default=None
    ),
    is_authoritative: bool | None = Query(default=None),
    repo: ReadRepository = Depends(get_read_repository),
) -> PaginatedRulesOut:
    return repo.list_rules(
        pathway=pathway,
        verification_status=verification_status,
        is_authoritative=is_authoritative,
    )


@router.get("/rules/{rule_id}", response_model=RuleDetailOut)
def get_rule_detail(
    rule_id: str,
    repo: ReadRepository = Depends(get_read_repository),
) -> RuleDetailOut:
    detail = repo.get_rule_detail(rule_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"Rule '{rule_id}' not found")
    return detail


@router.get("/care-gaps", response_model=PaginatedCareGapsOut)
def list_care_gaps(
    status: Literal[
        "open", "closed_completed", "closed_refused", "suppressed", "superseded"
    ]
    | None = Query(default=None),
    gap_type: Literal[
        "no_documented_screening",
        "interval_elapsed",
        "partial_completion",
        "referral_not_initiated",
        "visit_not_attended",
    ]
    | None = Query(default=None),
    rule_id: str | None = Query(default=None),
    patient_id: str | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    repo: ReadRepository = Depends(get_read_repository),
) -> PaginatedCareGapsOut:
    return repo.list_care_gaps(
        status=status,
        gap_type=gap_type,
        rule_id=rule_id,
        limit=limit,
        offset=offset,
        patient_id=patient_id,
    )


@router.get("/care-gaps/{gap_id}", response_model=CareGapDetailOut)
def get_care_gap_detail(
    gap_id: str,
    repo: ReadRepository = Depends(get_read_repository),
) -> CareGapDetailOut:
    detail = repo.get_care_gap_detail(gap_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"Care gap '{gap_id}' not found")
    return detail


@router.get("/facilities", response_model=PaginatedFacilitiesOut)
def list_facilities(
    limit: int = Query(default=25, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    repo: ReadRepository = Depends(get_read_repository),
) -> PaginatedFacilitiesOut:
    return repo.list_facilities(limit=limit, offset=offset)


@router.post("/explanations", response_model=ExplanationOut)
def create_explanation(
    req: ExplanationRequestIn,
    repo: ReadRepository = Depends(get_read_repository),
) -> ExplanationOut:
    ev_match, r_meta, h_status, eval_reasons, rule_oqs = repo.get_explanation_inputs(
        req.patient_id, req.rule_id
    )
    if ev_match is None or r_meta is None:
        raise HTTPException(
            status_code=404,
            detail=f"Evaluation for patient '{req.patient_id}' and rule '{req.rule_id}' not found",
        )

    try:
        res = _explanation_service.explain_evaluation(
            BoundedExplanationInput(
                synthetic_patient_id=req.patient_id,
                pathway=r_meta["pathway"],
                standard_name=r_meta["source_name"],
                rule_id=req.rule_id,
                rule_version=r_meta["rule_version"],
                source_reference=r_meta["source_reference"],
                verification_status=r_meta["verification_status"],
                is_authoritative=r_meta["is_authoritative"],
                evaluation_status=ev_match["evaluation_status"],
                history_status=h_status,
                reason_codes=tuple(r["reason_code"] for r in eval_reasons),
                guard_ids=tuple(r["guard_id"] for r in eval_reasons if r["guard_id"]),
                open_question_ids=tuple(rule_oqs),
                next_due_date=(
                    ev_match["next_due_date"].isoformat()
                    if ev_match["next_due_date"] is not None
                    else None
                ),
            )
        )
    except PrivacyViolationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return ExplanationOut(
        synthetic_patient_id=res.synthetic_patient_id,
        rule_id=res.rule_id,
        rule_version=res.rule_version,
        evaluation_status=res.evaluation_status,
        is_authoritative=res.is_authoritative,
        is_synthetic=True,
        generation_mode=res.generation_mode,
        summary_text=res.summary_text,
        why_text=res.why_text,
        missing_or_uncertain_text=res.missing_or_uncertain_text,
        rule_citation_text=res.rule_citation_text,
        warnings=list(res.warnings),
    )


@router.post("/outreach/preview", response_model=OutreachPreviewOut)
def preview_outreach(
    req: OutreachPreviewRequestIn,
    repo: ReadRepository = Depends(get_read_repository),
) -> OutreachPreviewOut:
    p, evals, gaps, consents = repo.get_patient_outreach_inputs(req.patient_id)
    if p is None:
        raise HTTPException(
            status_code=404, detail=f"Synthetic patient '{req.patient_id}' not found"
        )

    rule = repo.get_rule_meta(req.rule_id)

    try:
        res = _outreach_service.preview_outreach(
            patient=p,
            rule=rule,
            rule_id=req.rule_id,
            evaluations=evals,
            care_gaps=gaps,
            consents=consents,
            channel=req.channel,
            language=req.language,
        )
    except OutreachRuleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PrivacyViolationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return OutreachPreviewOut(
        synthetic_patient_id=res.synthetic_patient_id,
        care_gap_id=res.care_gap_id,
        rule_id=res.rule_id,
        rule_version=res.rule_version,
        allowed=res.allowed,
        simulated_only=True,
        blocked_reason=res.blocked_reason,
        preview_message=res.preview_message,
        disclaimer=res.disclaimer,
    )


@router.post(
    "/care-gaps/{gap_id}/follow-ups",
    response_model=FollowUpEventOut,
    status_code=201,
)
def create_care_gap_follow_up(
    gap_id: str,
    req: FollowUpCreateIn,
    repo: FollowUpRepository = Depends(get_followup_repository),
) -> FollowUpEventOut:
    return repo.create_follow_up(gap_id, req)


@router.get("/appointments", response_model=PaginatedAppointmentsOut)
def list_appointments(
    patient_id: str | None = Query(default=None),
    care_gap_id: str | None = Query(default=None),
    status: Literal[
        "scheduled",
        "attended",
        "no_show",
        "cancelled_by_patient",
        "cancelled_by_facility",
        "rescheduled",
    ]
    | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    repo: FollowUpRepository = Depends(get_followup_repository),
) -> PaginatedAppointmentsOut:
    return repo.list_appointments(
        patient_id=patient_id,
        care_gap_id=care_gap_id,
        status=status,
        limit=limit,
        offset=offset,
    )


@router.post("/appointments", response_model=AppointmentOut, status_code=201)
def create_appointment(
    req: AppointmentCreateIn,
    repo: FollowUpRepository = Depends(get_followup_repository),
) -> AppointmentOut:
    return repo.create_appointment(req)


@router.patch("/appointments/{appointment_id}", response_model=AppointmentOut)
def update_appointment(
    appointment_id: str,
    req: AppointmentPatchIn,
    repo: FollowUpRepository = Depends(get_followup_repository),
) -> AppointmentOut:
    return repo.update_appointment(appointment_id, req)


@router.get("/referrals", response_model=PaginatedReferralsOut)
def list_referrals(
    patient_id: str | None = Query(default=None),
    status: Literal["pending", "initiated", "completed", "declined", "cancelled"] | None = Query(
        default=None
    ),
    limit: int = Query(default=25, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    repo: FollowUpRepository = Depends(get_followup_repository),
) -> PaginatedReferralsOut:
    return repo.list_referrals(
        patient_id=patient_id, status=status, limit=limit, offset=offset
    )


@router.post("/referrals", response_model=ReferralOut, status_code=201)
def create_referral(
    req: ReferralCreateIn,
    repo: FollowUpRepository = Depends(get_followup_repository),
) -> ReferralOut:
    return repo.create_referral(req)


@router.patch("/referrals/{referral_id}", response_model=ReferralOut)
def update_referral(
    referral_id: str,
    req: ReferralPatchIn,
    repo: FollowUpRepository = Depends(get_followup_repository),
) -> ReferralOut:
    return repo.update_referral(referral_id, req)
