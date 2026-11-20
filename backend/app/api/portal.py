"""Patient portal (`/api/v1/portal/*`): a PATIENT account sees only its own linked record.

The patient id is never taken from the request: it comes from the verified account link of the
authenticated session. Ids of other patients' resources answer 404 exactly like missing ones.
Responses are localized (`?lang=` > profile language > `Accept-Language`), carry `locale` and
`direction`, and never expose staff notes, reviewer identities, reason codes or rule internals.
Patients can report that something was done elsewhere, but nothing they submit closes a care gap.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.api.auth import _users_mode_only
from app.api.v1 import get_followup_repository, get_read_repository
from app.core.auth import Principal, authenticated
from app.core.i18n import MESSAGES, AppError, direction, format_date, format_datetime, label, resolve_locale, t
from app.core.rate_limit import check_rate_limit
from app.models.identity import FollowUpTask, FollowUpTaskEvent, PatientRequest
from app.repositories.followup_repo import FollowUpRepository
from app.repositories.read_repo import ReadRepository, get_cached_bundle
from app.schemas.portal import (
    AppointmentChangeIn,
    AppointmentRequestIn,
    AssistanceIn,
    EvaluationItemPatientOut,
    FollowUpResponseIn,
    HealthSummaryOut,
    HistoryItemOut,
    PatientAssistantIn,
    PatientAssistantOut,
    PortalAssistantIn,
    PortalAssistantOut,
    PatientEvaluationHistoryOut,
    PatientRequestDetailOut,
    PatientRequestOut,
    PatientRequestsOut,
    PortalAppointmentOut,
    PortalAppointmentsOut,
    PortalFollowUpDetailOut,
    PortalFollowUpHistoryOut,
    PortalFollowUpOut,
    PortalFollowUpsOut,
    PortalLinkIn,
    PortalLinkOut,
    PortalProfileOut,
    PortalReferralOut,
    PortalReferralsOut,
    RecommendationDetailOut,
    RecommendationExplanationOut,
    RecommendationOut,
    RecommendationsOut,
    ScreeningItemOut,
    TaskEventPatientOut,
)
from app.services.ai import LLM_GROUNDED, AIService, get_ai_service
from app.services.care_pathway import recommended_pathway
from app.services.identity import directory, engagement
from app.services.identity.audit import record_event
from app.services.identity.store import identity_session
from app.services.ai.guardrails import sanitize_question, screen_question
from app.services.portal_assistant import (
    AssistantContext,
    PortalContext,
    build_facts,
    build_portal_facts,
    deterministic_answer,
    deterministic_portal_answer,
    screened_answer,
)

router = APIRouter(prefix="/api/v1/portal", tags=["portal"], dependencies=[Depends(_users_mode_only)])

CHANGE_CUTOFF = timedelta(hours=24)  # online cancel/reschedule requests close 24 h before the visit
_TIMELINE_EVENTS = frozenset({"appointment_scheduled", "appointment_updated", "referral_created",
                              "referral_updated", "completion_documented", "outreach_attempted"})
_PATIENT_EVENT_TYPES = frozenset({"created", "status_changed", "due_date_changed", "staff_message",
                                  "patient_response", "assistance_requested", "appointment_requested",
                                  "completed"})


def portal_patient(request: Request, p: Principal = Depends(authenticated)) -> Principal:
    """The caller must be a PATIENT with a verified, active link to a patient record."""
    if p.role is not None and not p.has("patients.read_self"):
        record_event(p, "authz.denied", "endpoint", resource_id=f"{request.method} {request.url.path}",
                     outcome="denied", status_code=403, permission="patients.read_self")
        raise AppError(403, "error.forbidden")
    if p.patient_id is None:
        raise AppError(404, "portal.not_linked")
    return p


portal_patient.__pulsereach_permissions__ = ("patients.read_self",)  # type: ignore[attr-defined]


def _loc(request: Request, p: Principal) -> tuple[str, dict[str, str]]:
    loc = resolve_locale(request, p.preferred_language)
    return loc, {"locale": loc, "direction": direction(loc)}


def _pathway(rule_id: str | None) -> str:
    rule = next((r for r in get_cached_bundle().rules if r["rule_id"] == rule_id), None)
    if rule is not None:
        return rule["pathway"]
    return "well_child" if (rule_id or "").startswith("WCV") else "ifhas"


def _not_found(kind: str, ident: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"{kind} '{ident}' not found")


# --- linking -------------------------------------------------------------------------------


@router.post("/link", response_model=PortalLinkOut)
def link_account(
    req: PortalLinkIn,
    request: Request,
    p: Principal = Depends(authenticated),
    repo: ReadRepository = Depends(get_read_repository),
) -> PortalLinkOut:
    """Redeem a staff-issued invitation code; the date of birth must match the patient record."""
    check_rate_limit(f"portal_link:user:{p.user_id}", limit=5)

    def dob(patient_id: str):
        rec = repo.get_patient(patient_id)
        return False if rec is None else rec.date_of_birth

    try:
        with identity_session() as s:
            link = directory.redeem_invitation(s, user_id=p.user_id, code=req.invitation_code,
                                               date_of_birth=req.date_of_birth, patient_dob_lookup=dob)
            patient_id, org = link.patient_id, link.organization_id
    except HTTPException as exc:
        record_event(p, "patient_link.redeem", "patient_link", outcome="denied", status_code=exc.status_code)
        raise
    record_event(p, "patient_link.redeem", "patient_link", resource_id=patient_id, patient_id=patient_id,
                 organization_id=org, status_code=200)
    loc, meta = _loc(request, p)
    return PortalLinkOut(linked=True, patient_id=patient_id, message=t("link.completed", loc), **meta)


# --- profile and health information ----------------------------------------------------------


def _gaps(repo: ReadRepository, pid: str) -> list[Any]:
    return repo.list_care_gaps(status=None, gap_type=None, rule_id=None, limit=200, offset=0, patient_id=pid).items


def _appointments(repo: FollowUpRepository, pid: str) -> list[Any]:
    return repo.list_appointments(patient_id=pid, care_gap_id=None, status=None, limit=200, offset=0).items


@router.get("/summary", response_model=PortalProfileOut)
def get_summary(
    request: Request,
    p: Principal = Depends(portal_patient),
    repo: ReadRepository = Depends(get_read_repository),
    followups: FollowUpRepository = Depends(get_followup_repository),
) -> PortalProfileOut:
    loc, meta = _loc(request, p)
    rec = repo.get_patient(p.patient_id)
    if rec is None:
        raise AppError(404, "portal.not_linked")
    ts = datetime.now(timezone.utc)
    upcoming = sum(1 for a in _appointments(followups, p.patient_id)
                   if a.status in ("scheduled", "rescheduled") and a.scheduled_datetime >= ts)
    with identity_session() as s:
        counts = engagement.summary_counts(s, organization_id=p.organization_id, patient_id=p.patient_id)
    return PortalProfileOut(
        patient_id=rec.patient_id, given_name=rec.given_name, family_name=rec.family_name,
        date_of_birth=rec.date_of_birth, date_of_birth_display=format_date(rec.date_of_birth, loc),
        sex=rec.sex, preferred_language=rec.preferred_language, preferred_channel=rec.preferred_channel,
        region_id=rec.region_id, open_recommendations=rec.open_care_gaps_count, upcoming_appointments=upcoming,
        **counts, **meta,
    )


@router.get("/health-summary", response_model=HealthSummaryOut)
def get_health_summary(
    request: Request, p: Principal = Depends(portal_patient), repo: ReadRepository = Depends(get_read_repository)
) -> HealthSummaryOut:
    loc, meta = _loc(request, p)
    hist = repo.get_patient_history(p.patient_id)
    if hist is None:
        raise AppError(404, "portal.not_linked")
    events = [
        ScreeningItemOut(kind="screening", programme="ifhas", programme_label=t("programme.ifhas", loc),
                         performed_date=s.performed_date, performed_date_display=format_date(s.performed_date, loc),
                         status=s.completion_status, status_label=label("screening_status", s.completion_status, loc),
                         results_communicated_date=s.results_communicated_date)
        for s in hist.ifhas_screenings
    ] + [
        ScreeningItemOut(kind="well_child_visit", programme="well_child",
                         programme_label=t("programme.well_child", loc), performed_date=v.performed_date,
                         performed_date_display=format_date(v.performed_date, loc), status=v.attendance_status,
                         status_label=label("attendance_status", v.attendance_status, loc))
        for v in hist.well_child_visits
    ]
    events.sort(key=lambda e: (e.performed_date or date.min), reverse=True)
    return HealthSummaryOut(
        patient_id=p.patient_id,
        history=[HistoryItemOut(programme=h.pathway, programme_label=label("programme", h.pathway, loc),
                                status=h.history_status, status_label=label("history_status", h.history_status, loc))
                 for h in hist.history_availability],
        events=events, disclaimer=t("explain.disclaimer", loc), **meta,
    )


@router.get("/evaluations", response_model=PatientEvaluationHistoryOut)
def get_evaluation_history(
    request: Request, p: Principal = Depends(portal_patient), repo: ReadRepository = Depends(get_read_repository)
) -> PatientEvaluationHistoryOut:
    """Results inside the person's age/sex band only; rule-level review flags and 'not applicable'
    results are omitted (they say nothing about the person)."""
    loc, meta = _loc(request, p)
    pe = repo.get_patient_evaluations(p.patient_id)
    if pe is None:
        raise AppError(404, "portal.not_linked")
    items = [
        EvaluationItemPatientOut(
            rule_id=e.rule_id, programme=e.pathway, programme_label=label("programme", e.pathway, loc),
            status=e.evaluation_status, status_label=label("evaluation_status", e.evaluation_status, loc),
            next_due_date=e.next_due_date, next_due_date_display=format_date(e.next_due_date, loc),
            evaluated_at=e.evaluated_at,
        )
        for e in pe.evaluations
        if e.applicability != "out_of_band" and e.evaluation_status != "not_eligible" and e.review_origin != "rule"
    ]
    return PatientEvaluationHistoryOut(patient_id=p.patient_id, reference_date=pe.reference_date,
                                       reference_date_display=format_date(pe.reference_date, loc), items=items,
                                       disclaimer=t("explain.disclaimer", loc), **meta)


# --- recommendations -------------------------------------------------------------------------


def _next_step(repo: ReadRepository, gap: Any, cache: dict[str, Any]) -> str | None:
    if gap.rule_id not in cache:
        detail = repo.get_rule_detail(gap.rule_id)
        cache[gap.rule_id] = detail.model_dump() if detail else None
    rule = cache[gap.rule_id]
    if rule is None:
        return None
    step = recommended_pathway(gap.model_dump(), rule)
    return step["next_step"] if step["status"] == "documented_next_step" else None


def _recommendation(gap: Any, loc: str, step: str | None) -> dict[str, Any]:
    pw = _pathway(gap.rule_id)
    programme = t(f"programme.{pw}", loc)
    step_key = f"next_step.{step}" if step else "next_step.care_team_review"
    return dict(
        recommendation_id=gap.care_gap_id, rule_id=gap.rule_id, programme=pw, programme_label=programme,
        gap_type=gap.gap_type, title=t(f"gap.{gap.gap_type}.title", loc),
        description=t(f"gap.{gap.gap_type}.description", loc, programme=programme),
        status=gap.status, status_label=label("care_gap_status", gap.status, loc),
        identified_date=gap.identified_date, identified_date_display=format_date(gap.identified_date, loc),
        closed_date=gap.closed_date, next_step=step,
        next_step_text=t(step_key if step_key in MESSAGES else "next_step.care_team_review", loc),
    )


def _own_gap(repo: ReadRepository, pid: str, gap_id: str) -> Any:
    gap = next((g for g in _gaps(repo, pid) if g.care_gap_id == gap_id), None)
    if gap is None:
        raise _not_found("Recommendation", gap_id)
    return gap


@router.get("/recommendations", response_model=RecommendationsOut)
def list_recommendations(
    request: Request,
    status: str = Query(default="active", pattern="^(active|all)$"),
    p: Principal = Depends(portal_patient),
    repo: ReadRepository = Depends(get_read_repository),
) -> RecommendationsOut:
    loc, meta = _loc(request, p)
    cache: dict[str, Any] = {}
    gaps = [g for g in _gaps(repo, p.patient_id) if status == "all" or g.status == "open"]
    items = [RecommendationOut(**_recommendation(g, loc, _next_step(repo, g, cache))) for g in gaps]
    return RecommendationsOut(total=len(items), items=items, **meta)


@router.get("/recommendations/{recommendation_id}", response_model=RecommendationDetailOut)
def get_recommendation(
    recommendation_id: str,
    request: Request,
    p: Principal = Depends(portal_patient),
    repo: ReadRepository = Depends(get_read_repository),
    followups: FollowUpRepository = Depends(get_followup_repository),
) -> RecommendationDetailOut:
    loc, meta = _loc(request, p)
    gap = _own_gap(repo, p.patient_id, recommendation_id)
    rec = _recommendation(gap, loc, _next_step(repo, gap, {}))
    timeline = _timeline(followups, gap)
    with identity_session() as s:
        _, tasks = engagement.list_tasks(s, organization_id=p.organization_id, patient_ids=None,
                                         patient_id=p.patient_id, patient_visible_only=True, limit=200)
    return RecommendationDetailOut(
        **rec, **meta,
        evidence=_evidence(repo, p.patient_id, gap, loc),
        history=[dict(occurred_on=x["occurred_on"], occurred_on_display=format_date(x["occurred_on"], loc),
                      event=x["event"], label=t(f"timeline.{x['event']}", loc)) for x in timeline],
        related_follow_up_ids=[tk.task_id for tk in tasks if tk.care_gap_id == gap.care_gap_id],
        disclaimer=t("explain.disclaimer", loc),
    )


def _timeline(followups: FollowUpRepository, gap: Any) -> list[dict[str, Any]]:
    timeline = [dict(occurred_on=gap.identified_date, event="identified")]
    for ev in followups.list_follow_ups(gap.care_gap_id, limit=200, offset=0).items:
        if ev.event_type in _TIMELINE_EVENTS:
            timeline.append(dict(occurred_on=ev.recorded_at.date(), event=ev.event_type))
    if gap.closed_date:
        timeline.append(dict(occurred_on=gap.closed_date, event="closed"))
    timeline.sort(key=lambda x: x["occurred_on"])
    return timeline


def _evidence(repo: ReadRepository, pid: str, gap: Any, loc: str) -> list[str]:
    pw = _pathway(gap.rule_id)
    out = [t(f"gap.{gap.gap_type}.description", loc, programme=t(f"programme.{pw}", loc)),
           t("explain.why", loc, identified_date=format_date(gap.identified_date, loc))]
    pe = repo.get_patient_evaluations(pid)
    ev = next((e for e in (pe.evaluations if pe else []) if e.evaluation_id == gap.evaluation_id), None)
    if ev is not None and ev.next_due_date is not None:
        out.append(t("explain.next_due", loc, next_due_date=format_date(ev.next_due_date, loc)))
    hist = repo.get_patient(pid)
    if hist is not None and hist.history_by_pathway.get(pw) == "not_available":
        out.append(t("explain.history_unknown", loc))
    return out


@router.get("/recommendations/{recommendation_id}/explanation", response_model=RecommendationExplanationOut)
def explain_recommendation(
    recommendation_id: str,
    request: Request,
    p: Principal = Depends(portal_patient),
    repo: ReadRepository = Depends(get_read_repository),
) -> RecommendationExplanationOut:
    """Deterministic, patient-friendly explanation in the requested language. No model is called:
    the AI explanation endpoint stays staff-only."""
    loc, meta = _loc(request, p)
    gap = _own_gap(repo, p.patient_id, recommendation_id)
    rec = _recommendation(gap, loc, _next_step(repo, gap, {}))
    return RecommendationExplanationOut(
        recommendation_id=gap.care_gap_id, title=rec["title"], paragraphs=_evidence(repo, p.patient_id, gap, loc),
        next_step_text=rec["next_step_text"], disclaimer=t("explain.disclaimer", loc), **meta,
    )


_OPEN_REQUEST_STATUSES = frozenset({"submitted", "acknowledged", "scheduled"})


@router.post("/recommendations/{recommendation_id}/assistant", response_model=PatientAssistantOut)
def ask_assistant(
    recommendation_id: str,
    req: PatientAssistantIn,
    request: Request,
    p: Principal = Depends(portal_patient),
    repo: ReadRepository = Depends(get_read_repository),
    followups: FollowUpRepository = Depends(get_followup_repository),
    ai: AIService = Depends(get_ai_service),
) -> PatientAssistantOut:
    """Plain-language help on a fixed topic about one of the patient's own recommendations.

    Patient and recommendation come from the session's account link (other patients' ids answer
    404). Only the de-identified portal facts of this recommendation reach the model, which
    restates them; nothing is changed, booked or sent. Disabled, failing or rejected generations
    return the deterministic answer built from the same facts. Every answer is audited."""
    check_rate_limit(f"portal_assistant:user:{p.user_id}", limit=20)
    loc, meta = _loc(request, p)
    gap = _own_gap(repo, p.patient_id, recommendation_id)
    patient = repo.get_patient(p.patient_id)
    if patient is None:
        raise AppError(404, "portal.not_linked")
    step = _next_step(repo, gap, {})
    rec = _recommendation(gap, loc, step)
    appts = sorted((a for a in _appointments(followups, p.patient_id) if a.care_gap_id == gap.care_gap_id),
                   key=lambda a: a.scheduled_datetime, reverse=True)[:5]
    appt_ids = {a.appointment_id for a in appts}
    with identity_session() as s:
        _, tasks = engagement.list_tasks(s, organization_id=p.organization_id, patient_ids=None,
                                         patient_id=p.patient_id, patient_visible_only=True, active=True, limit=200)
        _, reqs = engagement.list_requests(s, organization_id=p.organization_id, patient_ids=None,
                                           patient_id=p.patient_id, limit=200)
        follow_ups = [{"status": label("task_status", tk.status, loc), "due": format_date(tk.due_date, loc)}
                      for tk in tasks if tk.care_gap_id == gap.care_gap_id]
        open_requests = [{"type": label("request_type", r.request_type, loc),
                          "status": label("request_status", r.status, loc)}
                         for r in reqs if r.status in _OPEN_REQUEST_STATUSES
                         and (r.care_gap_id == gap.care_gap_id or r.appointment_id in appt_ids)]
    ctx = AssistantContext(
        locale=loc, programme=rec["programme_label"], title=rec["title"], description=rec["description"],
        status=gap.status, status_label=rec["status_label"], identified_on=rec["identified_date_display"],
        evidence=_evidence(repo, p.patient_id, gap, loc), next_step_text=rec["next_step_text"],
        next_step_documented=step is not None,
        history=["{} ({})".format(t("timeline." + x["event"], loc), format_date(x["occurred_on"], loc))
                 for x in _timeline(followups, gap)],
        earlier_history_on_file=patient.history_by_pathway.get(rec["programme"]) != "not_available",
        change_cutoff_hours=int(CHANGE_CUTOFF.total_seconds() // 3600),
        appointments=[{"type": o.appointment_type_label, "when": o.scheduled_display, "status": o.status_label,
                       "can_request_change_online": o.can_request_change}
                      for o in (_appointment_out(a, loc) for a in appts)],
        open_requests=open_requests, follow_ups=follow_ups,
    )
    question, fallback, screened, kind = _screen(p, req, loc, deterministic_answer(ctx, req.topic))
    answer, gen = ai.patient_assistant(
        build_facts(ctx, req.topic), topic=req.topic, language=loc, fallback=fallback,
        allow_completed=gap.status == "closed_completed",
        subject={"patient_id": p.patient_id, "care_gap_id": gap.care_gap_id, "rule_id": gap.rule_id},
        run_id=patient.run_id, actor=p.audit_actor(), question=question, skip_reason=screened,
    )
    record_event(p, "ai.patient_assistant", "care_gap", resource_id=gap.care_gap_id, patient_id=p.patient_id,
                 status_code=200, permission="patients.read_self",
                 details={"topic": req.topic, "generation_mode": gen.generation_mode, "ai_audit_id": gen.audit_id,
                          "screened": screened})
    return PatientAssistantOut(
        recommendation_id=gap.care_gap_id, topic=req.topic, answer=answer, **_answer_meta(req.topic, gen, kind, loc),
        **meta,
    )


def _screen(p: Principal, req: Any, loc: str, fallback: list[str]) -> tuple[str | None, list[str], str | None, str]:
    """Free-text questions: sanitize, apply the stricter question rate limit and screen before any
    model call. Returns `(question, fallback, skip_reason, answer_kind)`."""
    if req.topic != "question":
        return None, fallback, None, "answer"
    check_rate_limit(f"portal_question:user:{p.user_id}", limit=10)
    question = sanitize_question(req.question)
    reason = screen_question(question)
    lines, kind = screened_answer(reason, loc)
    return question, lines, (f"blocked:{reason}" if reason else None), (kind if reason else "answer")


def _answer_meta(topic: str, gen: Any, kind: str, loc: str) -> dict[str, Any]:
    grounded = gen.generation_mode == LLM_GROUNDED
    if not grounded and kind == "answer" and topic == "question":
        kind = "unavailable"
    if grounded:
        note = t("assistant.source.ai", loc) + (" " + t("assistant.source.ai_translation", loc) if loc == "ar" else "")
    else:
        note = t("assistant.source.screened" if kind != "answer" and kind != "unavailable" else "assistant.source.standard", loc)
    return dict(topic_label=t(f"assistant.topic.{topic}", loc), generation_mode=gen.generation_mode, answer_kind=kind,
                ai_generated=grounded, source_note=note, escalation=t("assistant.escalation", loc),
                disclaimer=t("explain.disclaimer", loc))


@router.post("/assistant", response_model=PortalAssistantOut)
def ask_portal_assistant(
    req: PortalAssistantIn,
    request: Request,
    p: Principal = Depends(portal_patient),
    repo: ReadRepository = Depends(get_read_repository),
    followups: FollowUpRepository = Depends(get_followup_repository),
    ai: AIService = Depends(get_ai_service),
) -> PortalAssistantOut:
    """Care navigation across the portal: the patient's own open recommendations and counts, the
    portal sections and the routes to the care team. The patient comes from the session's account
    link; only de-identified labels and counts reach the model; nothing is changed, booked or sent."""
    check_rate_limit(f"portal_guide:user:{p.user_id}", limit=20)
    loc, meta = _loc(request, p)
    patient = repo.get_patient(p.patient_id)
    if patient is None:
        raise AppError(404, "portal.not_linked")
    cache: dict[str, Any] = {}
    recs = [_recommendation(g, loc, _next_step(repo, g, cache)) for g in _gaps(repo, p.patient_id) if g.status == "open"]
    ts = datetime.now(timezone.utc)
    upcoming = sorted((a for a in _appointments(followups, p.patient_id)
                       if a.status in ("scheduled", "rescheduled") and a.scheduled_datetime >= ts),
                      key=lambda a: a.scheduled_datetime)
    nxt = _appointment_out(upcoming[0], loc) if upcoming else None
    with identity_session() as s:
        counts = engagement.summary_counts(s, organization_id=p.organization_id, patient_id=p.patient_id)
    ctx = PortalContext(
        locale=loc,
        recommendations=[{"title": r["title"], "programme": r["programme_label"], "next_step": r["next_step_text"]}
                         for r in recs],
        open_recommendations=len(recs), upcoming_appointments=len(upcoming),
        awaiting_your_reply=counts["awaiting_your_reply"], open_requests=counts["open_requests"],
        next_appointment={"type": nxt.appointment_type_label, "when": nxt.scheduled_display, "status": nxt.status_label}
        if nxt else None,
    )
    question, fallback, screened, kind = _screen(p, req, loc, deterministic_portal_answer(ctx, req.topic))
    answer, gen = ai.portal_assistant(
        build_portal_facts(ctx, req.topic), topic=req.topic, language=loc, fallback=fallback,
        subject={"patient_id": p.patient_id}, run_id=patient.run_id, actor=p.audit_actor(), question=question,
        skip_reason=screened,
    )
    record_event(p, "ai.portal_assistant", "patient", resource_id=p.patient_id, patient_id=p.patient_id,
                 status_code=200, permission="patients.read_self",
                 details={"topic": req.topic, "generation_mode": gen.generation_mode, "ai_audit_id": gen.audit_id,
                          "screened": screened})
    return PortalAssistantOut(topic=req.topic, answer=answer, **_answer_meta(req.topic, gen, kind, loc), **meta)


# --- appointments and referrals ------------------------------------------------------------


def _appointment_out(a: Any, loc: str) -> PortalAppointmentOut:
    changeable = a.status in ("scheduled", "rescheduled") and a.scheduled_datetime - datetime.now(timezone.utc) > CHANGE_CUTOFF
    return PortalAppointmentOut(
        appointment_id=a.appointment_id, appointment_type=a.appointment_type,
        appointment_type_label=label("appointment_type", a.appointment_type, loc),
        scheduled_datetime=a.scheduled_datetime, scheduled_display=format_datetime(a.scheduled_datetime, loc),
        status=a.status, status_label=label("appointment_status", a.status, loc), recommendation_id=a.care_gap_id,
        can_request_change=changeable,
    )


def _own_appointment(repo: FollowUpRepository, pid: str, appointment_id: str) -> Any:
    a = next((a for a in _appointments(repo, pid) if a.appointment_id == appointment_id), None)
    if a is None:
        raise _not_found("Appointment", appointment_id)
    return a


@router.get("/appointments", response_model=PortalAppointmentsOut)
def list_my_appointments(
    request: Request, p: Principal = Depends(portal_patient),
    followups: FollowUpRepository = Depends(get_followup_repository),
) -> PortalAppointmentsOut:
    loc, meta = _loc(request, p)
    items = [_appointment_out(a, loc) for a in _appointments(followups, p.patient_id)]
    return PortalAppointmentsOut(total=len(items), items=items, **meta)


@router.get("/appointments/{appointment_id}", response_model=PortalAppointmentOut)
def get_my_appointment(
    appointment_id: str, request: Request, p: Principal = Depends(portal_patient),
    followups: FollowUpRepository = Depends(get_followup_repository),
) -> PortalAppointmentOut:
    loc, _ = _loc(request, p)
    return _appointment_out(_own_appointment(followups, p.patient_id, appointment_id), loc)


@router.get("/referrals", response_model=PortalReferralsOut)
def list_my_referrals(
    request: Request, p: Principal = Depends(portal_patient),
    followups: FollowUpRepository = Depends(get_followup_repository),
) -> PortalReferralsOut:
    loc, meta = _loc(request, p)
    refs = followups.list_referrals(patient_id=p.patient_id, status=None, limit=200, offset=0).items
    items = [PortalReferralOut(referral_id=r.referral_id, referral_target=r.referral_target, status=r.status,
                               status_label=label("referral_status", r.status, loc), trigger_date=r.trigger_date,
                               trigger_date_display=format_date(r.trigger_date, loc), initiated_date=r.initiated_date, completed_date=r.completed_date) for r in refs]
    return PortalReferralsOut(total=len(items), items=items, **meta)


@router.get("/referrals/{referral_id}", response_model=PortalReferralOut)
def get_my_referral(
    referral_id: str, request: Request, p: Principal = Depends(portal_patient),
    followups: FollowUpRepository = Depends(get_followup_repository),
) -> PortalReferralOut:
    out = list_my_referrals(request, p, followups)
    item = next((r for r in out.items if r.referral_id == referral_id), None)
    if item is None:
        raise _not_found("Referral", referral_id)
    return item


# --- requests ------------------------------------------------------------------------------


def _request_out(r: PatientRequest, loc: str) -> dict[str, Any]:
    return dict(
        request_id=r.request_id, request_type=r.request_type,
        request_type_label=label("request_type", r.request_type, loc), status=r.status,
        status_label=label("request_status", r.status, loc), status_hint=t(f"request_hint.{r.status}", loc),
        follow_up_id=r.task_id, recommendation_id=r.care_gap_id, appointment_id=r.appointment_id,
        change_action=r.change_action, change_action_label=label("change_action", r.change_action, loc),
        preferred_dates=list(r.preferred_dates or []), preferred_time_of_day=r.preferred_time_of_day,
        message=r.message, staff_response=r.staff_response, created_at=r.created_at,
        created_display=format_datetime(r.created_at, loc), updated_at=r.updated_at,
        updated_display=format_datetime(r.updated_at, loc),
    )


def _own_task(s, p: Principal, task_id: str) -> FollowUpTask:
    task = s.get(FollowUpTask, task_id)
    if task is None or task.patient_id != p.patient_id or task.organization_id != p.organization_id \
            or not task.patient_visible:
        raise _not_found("Follow-up", task_id)
    return task


def _submit_request(
    request: Request, p: Principal, *, request_type: str, task_id: str | None = None,
    care_gap_id: str | None = None, appointment_id: str | None = None, change_action: str | None = None,
    preferred_dates: list[date] | None = None, preferred_time_of_day: str | None = None,
    message: str | None = None,
) -> PatientRequestDetailOut:
    check_rate_limit(f"portal_request:user:{p.user_id}", limit=20)
    loc, meta = _loc(request, p)
    with identity_session() as s:
        task = _own_task(s, p, task_id) if task_id else None
        r = engagement.create_request(
            s, organization_id=p.organization_id, patient_id=p.patient_id, user_id=p.user_id,
            request_type=request_type, language=loc, task=task, care_gap_id=care_gap_id,
            appointment_id=appointment_id, change_action=change_action,
            preferred_dates=[d.isoformat() for d in preferred_dates or []],
            preferred_time_of_day=preferred_time_of_day, message=message,
        )
        out = PatientRequestDetailOut(**_request_out(r, loc), **meta, confirmation=t("workflow.request_submitted", loc))
    record_event(p, f"patient_request.{request_type}", "patient_request", resource_id=out.request_id,
                 patient_id=p.patient_id, status_code=201, permission="patient_requests.create",
                 details={"follow_up_id": task_id, "care_gap_id": care_gap_id, "appointment_id": appointment_id})
    return out


@router.post("/appointment-requests", response_model=PatientRequestDetailOut, status_code=201)
def request_appointment(
    req: AppointmentRequestIn, request: Request, p: Principal = Depends(portal_patient),
    repo: ReadRepository = Depends(get_read_repository),
) -> PatientRequestDetailOut:
    gap_id = None
    if req.recommendation_id:
        gap = _own_gap(repo, p.patient_id, req.recommendation_id)
        if gap.status != "open":
            raise AppError(422, "workflow.care_gap_not_open")
        gap_id = gap.care_gap_id
    return _submit_request(request, p, request_type="appointment", task_id=req.follow_up_id, care_gap_id=gap_id,
                           preferred_dates=req.preferred_dates, preferred_time_of_day=req.preferred_time_of_day,
                           message=req.message)


@router.post("/appointments/{appointment_id}/change-requests", response_model=PatientRequestDetailOut,
             status_code=201)
def request_appointment_change(
    appointment_id: str, req: AppointmentChangeIn, request: Request, p: Principal = Depends(portal_patient),
    followups: FollowUpRepository = Depends(get_followup_repository),
) -> PatientRequestDetailOut:
    """Ask the care team to cancel/reschedule; the appointment itself is changed only by staff.
    Allowed while the appointment is scheduled and more than 24 hours away."""
    loc, _ = _loc(request, p)
    if not _appointment_out(_own_appointment(followups, p.patient_id, appointment_id), loc).can_request_change:
        raise AppError(422, "workflow.appointment_change_not_allowed")
    return _submit_request(request, p, request_type="appointment_change", appointment_id=appointment_id,
                           change_action=req.action, preferred_dates=req.preferred_dates,
                           preferred_time_of_day=req.preferred_time_of_day, message=req.message)


@router.post("/assistance", response_model=PatientRequestDetailOut, status_code=201)
def request_assistance(req: AssistanceIn, request: Request, p: Principal = Depends(portal_patient)) -> PatientRequestDetailOut:
    return _submit_request(request, p, request_type="assistance", message=req.message,
                           preferred_time_of_day=req.preferred_time_of_day)


@router.get("/requests", response_model=PatientRequestsOut)
def list_my_requests(request: Request, p: Principal = Depends(portal_patient)) -> PatientRequestsOut:
    loc, meta = _loc(request, p)
    with identity_session() as s:
        total, rows = engagement.list_requests(s, organization_id=p.organization_id, patient_ids=None,
                                               patient_id=p.patient_id, limit=200)
        items = [PatientRequestOut(**_request_out(r, loc)) for r in rows]
    return PatientRequestsOut(total=total, items=items, **meta)


def _own_request(s, p: Principal, request_id: str) -> PatientRequest:
    r = s.get(PatientRequest, request_id)
    if r is None or r.patient_id != p.patient_id or r.organization_id != p.organization_id:
        raise _not_found("Request", request_id)
    return r


@router.get("/requests/{request_id}", response_model=PatientRequestDetailOut)
def get_my_request(request_id: str, request: Request, p: Principal = Depends(portal_patient)) -> PatientRequestDetailOut:
    loc, meta = _loc(request, p)
    with identity_session() as s:
        return PatientRequestDetailOut(**_request_out(_own_request(s, p, request_id), loc), **meta)


@router.post("/requests/{request_id}/cancel", response_model=PatientRequestDetailOut)
def cancel_my_request(request_id: str, request: Request, p: Principal = Depends(portal_patient)) -> PatientRequestDetailOut:
    loc, meta = _loc(request, p)
    with identity_session() as s:
        r = engagement.cancel_request_by_patient(s, _own_request(s, p, request_id))
        out = PatientRequestDetailOut(**_request_out(r, loc), **meta)
    record_event(p, "patient_request.cancel", "patient_request", resource_id=request_id, patient_id=p.patient_id,
                 status_code=200, permission="patient_requests.create")
    return out


# --- follow-ups ----------------------------------------------------------------------------


def _task_out(task: FollowUpTask, loc: str) -> dict[str, Any]:
    return dict(
        follow_up_id=task.task_id, recommendation_id=task.care_gap_id, status=task.status,
        status_label=label("task_status", task.status, loc), status_hint=t(f"task_hint.{task.status}", loc),
        message=t(f"task.{task.message_key}", loc),
        due_date=task.due_date, due_date_display=format_date(task.due_date, loc),
        is_overdue=engagement.is_overdue(task),
        reported_completion_pending_verification=task.patient_reported_completion and task.status != "completed",
        created_at=task.created_at, updated_at=task.updated_at, updated_display=format_datetime(task.updated_at, loc),
    )


def _event_out(ev: FollowUpTaskEvent, loc: str) -> TaskEventPatientOut:
    return TaskEventPatientOut(
        event_id=ev.event_id, event_type=ev.event_type, label=t(f"task_event.{ev.event_type}", loc),
        created_at=ev.created_at, created_display=format_datetime(ev.created_at, loc),
        from_status=ev.from_status, to_status=ev.to_status, response=ev.response_code,
        response_label=label("response", ev.response_code, loc), message=ev.message,
        from_care_team=ev.actor_role != "PATIENT",
    )


def _history(s, task: FollowUpTask, loc: str) -> list[TaskEventPatientOut]:
    return [_event_out(e, loc) for e in engagement.task_events(s, task.task_id, include_internal=False)
            if e.event_type in _PATIENT_EVENT_TYPES]


@router.get("/follow-ups", response_model=PortalFollowUpsOut)
def list_my_follow_ups(request: Request, p: Principal = Depends(portal_patient)) -> PortalFollowUpsOut:
    loc, meta = _loc(request, p)
    with identity_session() as s:
        total, rows = engagement.list_tasks(s, organization_id=p.organization_id, patient_ids=None,
                                            patient_id=p.patient_id, patient_visible_only=True, limit=200)
        items = [PortalFollowUpOut(**_task_out(tk, loc)) for tk in rows]
    return PortalFollowUpsOut(total=total, items=items, **meta)


@router.get("/follow-ups/{follow_up_id}", response_model=PortalFollowUpDetailOut)
def get_my_follow_up(follow_up_id: str, request: Request, p: Principal = Depends(portal_patient)) -> PortalFollowUpDetailOut:
    loc, meta = _loc(request, p)
    with identity_session() as s:
        task = _own_task(s, p, follow_up_id)
        return PortalFollowUpDetailOut(**_task_out(task, loc), history=_history(s, task, loc), **meta)


@router.get("/follow-ups/{follow_up_id}/history", response_model=PortalFollowUpHistoryOut)
def get_my_follow_up_history(
    follow_up_id: str, request: Request, p: Principal = Depends(portal_patient)
) -> PortalFollowUpHistoryOut:
    loc, meta = _loc(request, p)
    with identity_session() as s:
        task = _own_task(s, p, follow_up_id)
        return PortalFollowUpHistoryOut(follow_up_id=follow_up_id, items=_history(s, task, loc), **meta)


@router.post("/follow-ups/{follow_up_id}/responses", response_model=PortalFollowUpDetailOut, status_code=201)
def respond_to_follow_up(
    follow_up_id: str, req: FollowUpResponseIn, request: Request, p: Principal = Depends(portal_patient)
) -> PortalFollowUpDetailOut:
    """Record the patient's answer. `already_done` is flagged for staff verification only."""
    check_rate_limit(f"portal_request:user:{p.user_id}", limit=20)
    loc, meta = _loc(request, p)
    with identity_session() as s:
        task = _own_task(s, p, follow_up_id)
        engagement.patient_respond(s, task, user_id=p.user_id, response_code=req.response, message=req.message)
        s.flush()
        key = "workflow.reported_completion_pending" if req.response == "already_done" else "workflow.response_recorded"
        out = PortalFollowUpDetailOut(**_task_out(task, loc), history=_history(s, task, loc), **meta,
                                      confirmation=t(key, loc))
    record_event(p, "follow_up_task.patient_response", "follow_up_task", resource_id=follow_up_id,
                 patient_id=p.patient_id, status_code=201, permission="followups.respond",
                 details={"response": req.response})
    return out


@router.post("/follow-ups/{follow_up_id}/assistance", response_model=PatientRequestDetailOut, status_code=201)
def follow_up_assistance(
    follow_up_id: str, req: AssistanceIn, request: Request, p: Principal = Depends(portal_patient)
) -> PatientRequestDetailOut:
    return _submit_request(request, p, request_type="assistance", task_id=follow_up_id, message=req.message,
                           preferred_time_of_day=req.preferred_time_of_day)


@router.post("/follow-ups/{follow_up_id}/appointment-request", response_model=PatientRequestDetailOut,
             status_code=201)
def follow_up_appointment_request(
    follow_up_id: str, req: AppointmentRequestIn, request: Request, p: Principal = Depends(portal_patient)
) -> PatientRequestDetailOut:
    return _submit_request(request, p, request_type="appointment", task_id=follow_up_id,
                           preferred_dates=req.preferred_dates, preferred_time_of_day=req.preferred_time_of_day,
                           message=req.message)
