"""Staff AI copilot (`/api/v1/ai/copilot/*`): role-scoped, review-only summaries.

Each endpoint requires the permissions of the workflow it summarises and, for patient summaries,
that the patient is inside the caller's scope (other patients answer 404 exactly like missing
ones). Only structured fields the caller can already read are summarised; staff notes, internal
notes, patient free text, names, contact details and record ids never reach the model. The
copilot changes nothing and sends nothing; suggested next steps are deterministic. Every call is
recorded in the AI audit (`staff_copilot`) and the identity audit (`ai.staff_copilot`).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request

from app.api.auth import _users_mode_only
from app.api.v1 import get_followup_repository, get_read_repository, population_insight_facts
from app.core.auth import Principal, ensure_patient_access, require
from app.core.i18n import direction, resolve_locale, t
from app.core.rate_limit import check_rate_limit
from app.repositories.followup_repo import FollowUpRepository
from app.repositories.read_repo import ReadRepository, get_cached_bundle
from app.schemas.copilot import CopilotIn, CopilotOut
from app.services import copilot
from app.services.ai import LLM_GROUNDED, AIGenerationMeta, AIService, get_ai_service
from app.services.ai.service import _ai_available
from app.services.care_pathway import recommended_pathway
from app.services.identity import engagement
from app.services.identity.audit import record_event
from app.services.identity.store import identity_session

router = APIRouter(prefix="/api/v1/ai/copilot", tags=["ai"], dependencies=[Depends(_users_mode_only)])

_RATE_LIMIT_PER_MINUTE = 20


def _programme(rule_id: str | None) -> str:
    rule = next((r for r in get_cached_bundle().rules if r["rule_id"] == rule_id), None)
    return rule["pathway"] if rule else ("well_child" if (rule_id or "").startswith("WCV") else "ifhas")


def _locale(request: Request, p: Principal, body: CopilotIn | None) -> str:
    return body.language if body and body.language else resolve_locale(request, p.preferred_language)


def _not_found(patient_id: str) -> str:
    return f"Patient '{patient_id}' not found"


def _respond(
    p: Principal, ai: AIService, inp: copilot.CopilotInput, *, loc: str, subject: dict[str, Any],
    run_id: str | None, resource_type: str, resource_id: str | None, patient_id: str | None, permission: str,
) -> CopilotOut:
    result, meta = ai.staff_copilot(inp.facts, task=inp.task, language=loc, fallback=inp.fallback, subject=subject,
                                    run_id=run_id, actor=p.audit_actor())
    record_event(p, "ai.staff_copilot", resource_type, resource_id=resource_id, patient_id=patient_id,
                 status_code=200, permission=permission,
                 details={"task": inp.task, "generation_mode": meta.generation_mode, "ai_audit_id": meta.audit_id})
    grounded = meta.generation_mode == LLM_GROUNDED
    return CopilotOut(
        task=inp.task, locale=loc, direction=direction(loc), summary=result["summary"], points=result["points"],
        questions=result["questions"], suggested_next_steps=inp.steps, generation_mode=meta.generation_mode,
        ai_available=_ai_available(meta), draft_notice=t("copilot.draft_notice" if grounded else "copilot.standard_notice", loc),
        disclaimer=t("copilot.disclaimer", loc), sources=inp.sources, ai=_meta_out(meta),
    )


def _meta_out(meta: AIGenerationMeta) -> dict[str, Any]:
    return {"generation_mode": meta.generation_mode, "prompt_version": meta.prompt_version, "provider": meta.provider,
            "model": meta.model, "fallback_reason": meta.fallback_reason, "violations": list(meta.violations),
            "audit_id": meta.audit_id}


def _patient(repo: ReadRepository, p: Principal, patient_id: str) -> Any:
    ensure_patient_access(p, patient_id, _not_found(patient_id))
    patient = repo.get_patient(patient_id)
    if patient is None:
        raise HTTPException(status_code=404, detail=_not_found(patient_id))
    return patient


@router.post("/patients/{patient_id}/coordination", response_model=CopilotOut)
def coordination_summary(
    patient_id: str,
    request: Request,
    body: CopilotIn | None = Body(default=None),
    p: Principal = Depends(require("followups.read")),
    repo: ReadRepository = Depends(get_read_repository),
    followups: FollowUpRepository = Depends(get_followup_repository),
    ai: AIService = Depends(get_ai_service),
) -> CopilotOut:
    """Follow-up tasks, contact attempts, patient requests (only with `patient_requests.manage`),
    appointments and open care gaps of one in-scope patient, plus deterministic next steps."""
    check_rate_limit(f"staff_copilot:user:{p.user_id}", limit=_RATE_LIMIT_PER_MINUTE)
    loc = _locale(request, p, body)
    patient = _patient(repo, p, patient_id)
    gaps = repo.list_care_gaps(status=None, gap_type=None, rule_id=None, limit=200, offset=0, patient_id=patient_id).items
    appointments = sorted(
        followups.list_appointments(patient_id=patient_id, care_gap_id=None, status=None, limit=200, offset=0).items,
        key=lambda a: a.scheduled_datetime, reverse=True)
    with identity_session() as s:
        _, tasks = engagement.list_tasks(s, organization_id=p.organization_id or "", patient_ids=p.patient_scope(),
                                         patient_id=patient_id, limit=200)
        events = {tk.task_id: engagement.task_events(s, tk.task_id, include_internal=True) for tk in tasks}
        requests = (engagement.list_requests(s, organization_id=p.organization_id or "", patient_ids=p.patient_scope(),
                                             patient_id=patient_id, limit=200)[1]
                    if p.has("patient_requests.manage") else None)
        inp = copilot.coordination(
            loc=loc, gaps=gaps, tasks=tasks, events=events, requests=requests, appointments=appointments,
            today=engagement.now().date(), can_draft_outreach=p.has("outreach.draft"), programme_of=_programme,
        )
    return _respond(p, ai, inp, loc=loc, subject={"patient_id": patient_id}, run_id=patient.run_id,
                    resource_type="patient", resource_id=patient_id, patient_id=patient_id, permission="followups.read")


@router.post("/patients/{patient_id}/clinical-review", response_model=CopilotOut)
def clinical_review_summary(
    patient_id: str,
    request: Request,
    body: CopilotIn | None = Body(default=None),
    p: Principal = Depends(require("ai.explain", "care_gaps.read")),
    repo: ReadRepository = Depends(get_read_repository),
    ai: AIService = Depends(get_ai_service),
) -> CopilotOut:
    """Deterministic evaluation results (in-band), approved reason descriptions, open care gaps,
    history availability and documented next steps of one in-scope patient."""
    check_rate_limit(f"staff_copilot:user:{p.user_id}", limit=_RATE_LIMIT_PER_MINUTE)
    loc = _locale(request, p, body)
    patient = _patient(repo, p, patient_id)
    pe = repo.get_patient_evaluations(patient_id)
    if pe is None:
        raise HTTPException(status_code=404, detail=_not_found(patient_id))
    next_steps: dict[str, str | None] = {}
    for g in pe.care_gaps:
        if g.status == "open" and g.rule_id not in next_steps:
            rule = repo.get_rule_detail(g.rule_id)
            step = recommended_pathway(g.model_dump(), rule.model_dump()) if rule else None
            next_steps[g.rule_id] = step["next_step"] if step and step["status"] == "documented_next_step" else None
    inp = copilot.clinical_review(loc=loc, evaluations=pe.evaluations, gaps=pe.care_gaps,
                                  history_by_pathway=patient.history_by_pathway, next_steps=next_steps)
    return _respond(p, ai, inp, loc=loc, subject={"patient_id": patient_id}, run_id=patient.run_id,
                    resource_type="patient", resource_id=patient_id, patient_id=patient_id, permission="ai.explain")


@router.post("/population", response_model=CopilotOut)
def population_briefing(
    request: Request,
    body: CopilotIn | None = Body(default=None),
    p: Principal = Depends(require("insights.read")),
    repo: ReadRepository = Depends(get_read_repository),
    ai: AIService = Depends(get_ai_service),
) -> CopilotOut:
    """Aggregate counts over the caller's scope plus workflow bottlenecks (task and request
    counts, only with the matching permissions). No individual records are read."""
    check_rate_limit(f"staff_copilot:user:{p.user_id}", limit=_RATE_LIMIT_PER_MINUTE)
    loc = _locale(request, p, body)
    aggregates = population_insight_facts(repo, p)
    run_id = aggregates.pop("run_id")
    aggregates.pop("evaluation_run_id", None)
    workflow = open_requests = None
    with identity_session() as s:
        org = p.organization_id or ""
        if p.has("followups.read"):
            summary = engagement.task_summary(s, organization_id=org, patient_ids=p.patient_scope(), recent_limit=0)
            workflow = {k: v for k, v in summary.items() if k != "recent_events"}
        if p.has("patient_requests.manage"):
            open_requests = sum(engagement.list_requests(s, organization_id=org, patient_ids=p.patient_scope(),
                                                         status=st, limit=1)[0] for st in ("submitted", "acknowledged"))
    inp = copilot.population_briefing(loc=loc, aggregates=aggregates, workflow=workflow, open_requests=open_requests)
    return _respond(p, ai, inp, loc=loc, subject={"run_id": run_id}, run_id=run_id, resource_type="population",
                    resource_id=None, patient_id=None, permission="insights.read")
