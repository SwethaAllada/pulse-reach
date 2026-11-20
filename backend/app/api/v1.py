"""FastAPI `/api/v1/*` router (`app.api.v1`).

Supports both `DATA_SOURCE=memory` (default deterministic demo mode) and `DATA_SOURCE=db`
(PostgreSQL-backed read repository) without ever silently falling back from DB to memory.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, Literal

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
    evaluation_markers,
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
    AIAuditOut,
    AIAuditRecordOut,
    AIGenerationOut,
    AIStatusOut,
    ExplanationOut,
    OutreachDraftOut,
    OutreachDraftRequestIn,
    OutreachDraftReviewIn,
    OutreachDraftReviewOut,
    PopulationInsightOut,
    ExplanationRequestIn,
    FollowUpCreateIn,
    FollowUpEventOut,
    OutreachPreviewOut,
    OutreachPreviewRequestIn,
    PaginatedAppointmentsOut,
    PaginatedCareGapsOut,
    FacilityDetailOut,
    OpenQuestionOut,
    PaginatedFacilitiesOut,
    PaginatedOpenQuestionsOut,
    CareGapReviewIn,
    CareGapReviewOut,
    CareGapReviewsOut,
    PaginatedFollowUpEventsOut,
    PaginatedPatientsOut,
    PaginatedReferralsOut,
    PaginatedRulesOut,
    PatientConsentsOut,
    PatientActivityOut,
    PatientEvaluationsOut,
    PatientHistoryOut,
    PatientSummaryOut,
    ReferralCreateIn,
    ReferralOut,
    ReferralPatchIn,
    RuleDetailOut,
    WorkflowHistoryOut,
)
from app.services.evaluation.engine import ENGINE_VERSION
from app.services.evaluation.recorded import (
    evaluation_reason_detail,
    evaluation_snapshot,
    fired_reason_detail,
)
from app.services.ai import AIGenerationMeta, AIService, DuplicateReviewError, get_ai_service
from app.services.ai.audit import sha256
from app.services.ai.guardrails import validate_outreach_output
from app.services.ai.service import NOT_GENERATED
from app.services.explanation import BoundedExplanationInput, PrivacyViolationError
from app.services.explanation.context import build_explanation_context
from app.services.outreach import OutreachRuleNotFoundError, OutreachService
from app.services.outreach.drafting import OutreachDraftGate, gate_outreach_draft, pre_consent_block

router = APIRouter(prefix="/api/v1", tags=["v1"])

_outreach_service = OutreachService()
_OUTREACH_DRAFT_DISCLAIMER = (
    "SIMULATED OUTREACH DRAFT — for human review only. PulseReach never sends SMS, e-mail, phone "
    "calls, app notifications or any other message; approval records a simulated attempt only."
)
_INSIGHT_DISCLAIMER = (
    "Aggregates of synthetic records computed deterministically by the backend; any narrative is "
    "a restatement of these counts, not an analysis, prediction or clinical finding."
)


def _ai_out(meta: AIGenerationMeta) -> AIGenerationOut:
    return AIGenerationOut(
        generation_mode=meta.generation_mode,
        prompt_version=meta.prompt_version,
        provider=meta.provider,
        model=meta.model,
        fallback_reason=meta.fallback_reason,
        violations=list(meta.violations),
        audit_id=meta.audit_id,
    )


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
    # Not persisted: ids are namespaced per patient so they can never collide with (or resolve
    # to) stored evaluations or care gaps of this or another patient (F-18).
    ephemeral = f"EPHEMERAL-{req.patient_id}"
    eval_items: list[EvaluationItemOut] = []
    eval_id_by_rule: dict[str, str] = {}
    for ord_ev, ev in enumerate(summary.evaluations, 1):
        eid = f"{ephemeral}-EVL-{ord_ev:04d}"
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
                reason_detail=evaluation_reason_detail(ev),
                next_due_date=ev.next_due_date,
                evaluated_at=ev.evaluated_at,
                input_snapshot=evaluation_snapshot(ctx, ev, ref_date),
                reasons=[
                    EvaluationReasonOut(
                        reason_ordinal=i,
                        reason_code=r.reason_code,
                        reason_detail=fired_reason_detail(r),
                        guard_id=r.guard_id,
                        item_category=r.item_category,
                        item_code=r.item_code,
                    )
                    for i, r in enumerate(ev.reasons, 1)
                ],
                **evaluation_markers(
                    ev.rule_id,
                    ev.evaluation_status,
                    ev.reason_code,
                    date_of_birth=ctx.date_of_birth,
                    sex=ctx.sex,
                    reference_date=ref_date,
                ),
            )
        )
    gap_items = [
        CareGapOut(
            care_gap_id=f"{ephemeral}-GAP-{i:04d}",
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
        is_persisted=False,
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


_FACILITY_LAYERS = Literal[
    "hospitals",
    "health_centres",
    "clinics",
    "pharmacy",
    "rehabilitation_center",
    "provision_health_service",
    "diagnostic_centers",
    "mobile_health_unit",
    "dialysis_centre",
]


@router.get("/facilities", response_model=PaginatedFacilitiesOut)
def list_facilities(
    limit: int = Query(default=25, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    region_id: int | None = Query(default=None, ge=1, le=3),
    facility_type: str | None = Query(default=None, min_length=1, max_length=64),
    source_layer: _FACILITY_LAYERS | None = Query(default=None),
    q: str | None = Query(default=None, max_length=100),
    repo: ReadRepository = Depends(get_read_repository),
) -> PaginatedFacilitiesOut:
    return repo.list_facilities(
        limit=limit,
        offset=offset,
        region_id=region_id,
        facility_type=facility_type,
        source_layer=source_layer,
        q=q,
    )


@router.get("/facilities/{ch_fid}", response_model=FacilityDetailOut)
def get_facility(
    ch_fid: str,
    repo: ReadRepository = Depends(get_read_repository),
) -> FacilityDetailOut:
    detail = repo.get_facility(ch_fid)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"Facility '{ch_fid}' not found")
    return detail


@router.get("/open-questions", response_model=PaginatedOpenQuestionsOut)
def list_open_questions(
    status: Literal["open", "resolved"] | None = Query(default=None),
    category: str | None = Query(default=None, max_length=64),
    repo: ReadRepository = Depends(get_read_repository),
) -> PaginatedOpenQuestionsOut:
    return repo.list_open_questions(status=status, category=category)


@router.get("/open-questions/{oq_id}", response_model=OpenQuestionOut)
def get_open_question(
    oq_id: str,
    repo: ReadRepository = Depends(get_read_repository),
) -> OpenQuestionOut:
    oq = repo.get_open_question(oq_id)
    if oq is None:
        raise HTTPException(status_code=404, detail=f"Open question '{oq_id}' not found")
    return oq


@router.post("/explanations", response_model=ExplanationOut)
def create_explanation(
    req: ExplanationRequestIn,
    repo: ReadRepository = Depends(get_read_repository),
    ai: AIService = Depends(get_ai_service),
) -> ExplanationOut:
    ev_match, r_meta, h_status, eval_reasons, rule_oqs = repo.get_explanation_inputs(
        req.patient_id, req.rule_id
    )
    if ev_match is None or r_meta is None:
        raise HTTPException(
            status_code=404,
            detail=f"Evaluation for patient '{req.patient_id}' and rule '{req.rule_id}' not found",
        )
    pe = repo.get_patient_evaluations(req.patient_id)
    rule_detail = repo.get_rule_detail(req.rule_id)
    ev_item = next(
        (e for e in (pe.evaluations if pe else []) if e.evaluation_id == ev_match["evaluation_id"]), None
    )
    context = (
        build_explanation_context(
            ev_item, rule_detail, [g for g in pe.care_gaps if g.rule_id == req.rule_id]
        )
        if ev_item is not None and rule_detail is not None
        else None
    )

    try:
        res, meta = ai.explain(
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
            ),
            context,
            run_id=ev_match.get("run_id"),
        )
    except PrivacyViolationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    structured = (
        {
            "evaluation_id": context.evaluation_id,
            "pathway": context.pathway,
            "history_status": context.history_status,
            "next_due_date": context.next_due_date,
            "why_identified": context.why_identified,
            "care_gaps": list(context.care_gaps),
            "supporting_evidence": [e.__dict__ for e in context.supporting_evidence],
            "missing_information": list(context.missing_information),
            "conflicting_information": list(context.conflicting_information),
            "rule_meaning": context.rule_meaning,
            "next_step": context.next_step,
        }
        if context is not None
        else {}
    )
    return ExplanationOut(
        **structured,
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
        ai=_ai_out(meta),
        generated_explanation=res.summary_text if meta.generation_mode == "llm_grounded" else None,
    )


def _gated_preview(req: OutreachPreviewRequestIn | OutreachDraftRequestIn, repo: ReadRepository):
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
    return res, rule, (p, gaps, consents)


@router.post("/outreach/preview", response_model=OutreachPreviewOut)
def preview_outreach(
    req: OutreachPreviewRequestIn,
    repo: ReadRepository = Depends(get_read_repository),
) -> OutreachPreviewOut:
    res, _, _ = _gated_preview(req, repo)
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


def _draft_gate(
    req: OutreachDraftRequestIn | OutreachDraftReviewIn, repo: ReadRepository, tone: str
) -> OutreachDraftGate:
    """All pre-generation checks (`app.services.outreach.drafting`); never calls a provider."""
    early = pre_consent_block(req.channel, req.language)
    if early is not None:
        patient = repo.get_patient(req.patient_id)
        if patient is None:
            raise HTTPException(status_code=404, detail=f"Synthetic patient '{req.patient_id}' not found")
        return OutreachDraftGate(
            allowed=False, blocked_reason=early, patient_id=req.patient_id, rule_id=req.rule_id,
            rule_version=None, care_gap_id=req.care_gap_id, channel=req.channel,
            language=req.language, tone=tone, run_id=patient.run_id,
        )
    res, _, (p, gaps, consents) = _gated_preview(req, repo)
    rule = repo.get_rule_detail(req.rule_id)
    return gate_outreach_draft(
        preview=res, patient=p, consents=consents, rule=rule.model_dump() if rule else {},
        care_gaps=gaps, channel=req.channel, language=req.language, tone=tone,
        requested_care_gap_id=req.care_gap_id,
    )


@router.post("/outreach/draft", response_model=OutreachDraftOut)
def draft_outreach(
    req: OutreachDraftRequestIn,
    repo: ReadRepository = Depends(get_read_repository),
    ai: AIService = Depends(get_ai_service),
) -> OutreachDraftOut:
    """Consent-gated, simulated outreach draft for human review. Nothing is ever sent."""
    gate = _draft_gate(req, repo, req.tone)
    draft = ai.draft_outreach(gate)  # audits blocked requests too; no provider call when blocked
    fallback = draft is not None and draft.meta.generation_mode == "deterministic_fallback"
    return OutreachDraftOut(
        synthetic_patient_id=gate.patient_id,
        care_gap_id=gate.care_gap_id,
        rule_id=gate.rule_id,
        rule_version=gate.rule_version,
        allowed=gate.allowed,
        blocked_reason=gate.blocked_reason,
        draft_message=draft.message if draft else None,
        draft_body=draft.body if draft else None,
        disclaimer=_OUTREACH_DRAFT_DISCLAIMER,
        ai=_ai_out(draft.meta) if draft else None,
        channel=gate.channel,
        language=gate.language,
        tone=gate.tone,
        recipient=gate.recipient if draft else None,
        generation_status="blocked" if draft is None else ("fallback" if fallback else "generated"),
        is_fallback=fallback,
        next_step=gate.next_step if draft else None,
        review_status="pending_review" if draft else "not_applicable",
    )


@router.post("/outreach/draft/review", response_model=OutreachDraftReviewOut)
def review_outreach_draft(
    req: OutreachDraftReviewIn,
    repo: ReadRepository = Depends(get_read_repository),
    followups: FollowUpRepository = Depends(get_followup_repository),
    ai: AIService = Depends(get_ai_service),
) -> OutreachDraftReviewOut:
    """Human approval or rejection of a draft. Approval re-checks consent and eligibility,
    validates the final text and records a *simulated* outreach attempt (`simulated_not_sent`);
    nothing is sent. A draft takes one terminal decision: approval cannot be replayed and a
    rejected draft cannot be approved later (409)."""
    src = ai.audit.get(req.draft_audit_id)
    if src is None or src.feature != "outreach_draft" or src.generation_mode == NOT_GENERATED:
        raise HTTPException(status_code=404, detail="Outreach draft not found; generate a new draft.")
    if (src.subject.get("patient_id"), src.subject.get("rule_id"), src.subject.get("care_gap_id"),
            src.extra.get("channel"), src.extra.get("language")) != (
            req.patient_id, req.rule_id, req.care_gap_id, req.channel, req.language):
        raise HTTPException(status_code=409, detail="Review does not match the generated draft.")
    _ensure_not_reviewed(ai, req.draft_audit_id)

    subject = {"patient_id": req.patient_id, "rule_id": req.rule_id, "care_gap_id": req.care_gap_id}
    extra: dict[str, Any] = {"draft_audit_id": req.draft_audit_id, "channel": req.channel,
                             "language": req.language, "reviewed_by": req.reviewed_by}
    out = dict(draft_audit_id=req.draft_audit_id, synthetic_patient_id=req.patient_id,
               care_gap_id=req.care_gap_id, rule_id=req.rule_id, channel=req.channel,
               language=req.language, disclaimer=_OUTREACH_DRAFT_DISCLAIMER)

    def review(decision: str, **kw: Any):
        try:
            return ai.record_outreach_review(subject=subject, decision=decision, run_id=src.run_id, **kw)
        except DuplicateReviewError as exc:
            raise _already_reviewed(ai, req.draft_audit_id) from exc

    if req.decision == "rejected":
        rec = review("rejected", extra={**extra, "reason_provided": bool(req.reason)})
        return OutreachDraftReviewOut(**out, review_audit_id=rec.audit_id, review_status="rejected")

    gate = _draft_gate(req, repo, str(src.extra.get("tone") or "supportive"))
    if not gate.allowed:  # consent or eligibility changed since the draft was generated
        rec = review("blocked", extra={**extra, "blocked_reason": gate.blocked_reason})
        return OutreachDraftReviewOut(**out, review_audit_id=rec.audit_id, review_status="blocked",
                                      blocked_reason=gate.blocked_reason)

    body = (req.final_message or "").strip()
    body = body.removeprefix(
        f"[SIMULATED OUTREACH PREVIEW — {req.channel.upper()} ({req.language})]"
    ).strip()
    violations = validate_outreach_output(body, facts=gate.facts, channel=gate.channel,
                                          language=gate.language, max_chars=gate.max_chars)
    if violations:
        review("invalid", violations=tuple(violations), extra={**extra, "message_sha256": sha256(body)})
        raise HTTPException(status_code=422, detail={"message": "Final message failed validation.",
                                                     "violations": violations})

    edited = sha256(body) != src.extra.get("returned_sha256")
    recorded: dict[str, Any] = {}

    def record_review(follow_up: FollowUpEventOut, session: Any) -> None:
        # Same transaction as the follow-up event: a concurrent or replayed approval violates the
        # one-terminal-review-per-draft constraint and rolls the follow-up back too.
        approved = follow_up.event_type == "outreach_attempted"
        recorded["rec"] = review(
            "approved" if approved else "blocked", session=session,
            extra={**extra, "message_sha256": sha256(body), "edited": edited,
                   "follow_up_id": follow_up.follow_up_id,
                   "simulated_outreach_status": follow_up.outcome_status,
                   **({} if approved else {"blocked_reason": follow_up.suppression_reason})},
        )

    try:
        follow_up = followups.create_follow_up(req.care_gap_id, FollowUpCreateIn(
            event_type="outreach_attempted", recorded_by=req.reviewed_by,
            note=f"AI-assisted outreach draft approved by reviewer (draft audit {req.draft_audit_id}; "
                 f"channel {req.channel}; language {req.language}). Simulated only; not sent.",
        ), on_recorded=record_review)
    except HTTPException as exc:
        if exc.status_code == 409 and ai.audit.terminal_review(req.draft_audit_id) is not None:
            raise _already_reviewed(ai, req.draft_audit_id) from exc
        raise
    rec = recorded["rec"]
    if follow_up.event_type != "outreach_attempted":  # the write-time consent gate suppressed it
        return OutreachDraftReviewOut(
            **out, review_audit_id=rec.audit_id, review_status="blocked",
            blocked_reason=follow_up.suppression_reason, follow_up=follow_up,
            simulated_outreach_status=follow_up.outcome_status,
        )
    return OutreachDraftReviewOut(
        **out, review_audit_id=rec.audit_id, review_status="approved", edited=edited,
        simulated_outreach_status=follow_up.outcome_status, follow_up=follow_up,
    )


def _already_reviewed(ai: AIService, draft_audit_id: str) -> HTTPException:
    prior = ai.audit.terminal_review(draft_audit_id)
    status = prior.generation_mode.removeprefix("human_") if prior else "reviewed"
    return HTTPException(status_code=409, detail={
        "message": f"Outreach draft was already {status}; generate a new draft.",
        "code": "draft_already_reviewed",
        "review_status": status,
        "review_audit_id": prior.audit_id if prior else None,
        "follow_up_id": prior.extra.get("follow_up_id") if prior else None,
    })


def _ensure_not_reviewed(ai: AIService, draft_audit_id: str) -> None:
    if ai.audit.terminal_review(draft_audit_id) is not None:
        raise _already_reviewed(ai, draft_audit_id)


@router.get("/insights/population", response_model=PopulationInsightOut)
def population_insight(
    repo: ReadRepository = Depends(get_read_repository),
    ai: AIService = Depends(get_ai_service),
) -> PopulationInsightOut:
    d = repo.get_dashboard_summary()
    facts = {
        "run_id": d.run_id,
        "evaluation_run_id": d.evaluation_run_id,
        "reference_date": d.reference_date.isoformat(),
        "total_patients": d.total_patients,
        "n_adults": d.n_adults,
        "n_children": d.n_children,
        "open_care_gaps_count": d.open_care_gaps_count,
        "closed_refused_care_gaps_count": d.closed_refused_care_gaps_count,
        "open_gaps_by_pathway": d.gaps_by_pathway,
        "open_gaps_by_type": d.gaps_by_type,
        "open_gaps_by_region": {str(r.region_id): r.open_care_gaps_count for r in d.region_breakdown},
        "unknown_history_patients_count": d.unknown_history_patients_count,
        "review_flagged_patients_count": d.review_flagged_patients_count,
        "rule_review_patients_count": d.rule_review_patients_count,
    }
    insight = ai.population_insight(facts)
    return PopulationInsightOut(
        facts=insight.facts,
        summary_text=insight.summary_text,
        disclaimer=_INSIGHT_DISCLAIMER,
        ai=_ai_out(insight.meta),
    )


@router.get("/ai/status", response_model=AIStatusOut)
def ai_status(ai: AIService = Depends(get_ai_service)) -> AIStatusOut:
    return AIStatusOut(**ai.status())


@router.get("/ai/audit", response_model=AIAuditOut)
def ai_audit(
    limit: int = Query(default=50, ge=1, le=500),
    feature: Literal["explanation", "outreach_draft", "outreach_review", "population_insight"] | None = Query(
        default=None
    ),
    ai: AIService = Depends(get_ai_service),
) -> AIAuditOut:
    return AIAuditOut(
        durable=ai.audit.durable,
        items=[
            AIAuditRecordOut(**{**r.__dict__, "violations": list(r.violations)})
            for r in ai.audit.recent(limit=limit, feature=feature)
        ]
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


@router.post("/care-gaps/{gap_id}/reviews", response_model=CareGapReviewOut, status_code=201)
def create_care_gap_review(
    gap_id: str,
    req: CareGapReviewIn,
    repo: FollowUpRepository = Depends(get_followup_repository),
) -> CareGapReviewOut:
    return repo.create_review(gap_id, req)


@router.get("/care-gaps/{gap_id}/reviews", response_model=CareGapReviewsOut)
def list_care_gap_reviews(
    gap_id: str,
    repo: FollowUpRepository = Depends(get_followup_repository),
) -> CareGapReviewsOut:
    return repo.list_reviews(gap_id)


@router.get("/care-gaps/{gap_id}/follow-ups", response_model=PaginatedFollowUpEventsOut)
def list_care_gap_follow_ups(
    gap_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    repo: FollowUpRepository = Depends(get_followup_repository),
) -> PaginatedFollowUpEventsOut:
    return repo.list_follow_ups(gap_id, limit=limit, offset=offset)


@router.get("/patients/{patient_id}/activity", response_model=PatientActivityOut)
def get_patient_activity(
    patient_id: str,
    repo: FollowUpRepository = Depends(get_followup_repository),
) -> PatientActivityOut:
    return repo.get_patient_activity(patient_id)


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


@router.get("/appointments/{appointment_id}/history", response_model=WorkflowHistoryOut)
def get_appointment_history(
    appointment_id: str,
    repo: FollowUpRepository = Depends(get_followup_repository),
) -> WorkflowHistoryOut:
    return repo.get_appointment_history(appointment_id)


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


@router.get("/referrals/{referral_id}/history", response_model=WorkflowHistoryOut)
def get_referral_history(
    referral_id: str,
    repo: FollowUpRepository = Depends(get_followup_repository),
) -> WorkflowHistoryOut:
    return repo.get_referral_history(referral_id)
