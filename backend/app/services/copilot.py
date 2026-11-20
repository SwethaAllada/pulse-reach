"""Facts, deterministic suggestions and fallback summaries for the staff AI copilot.

Every builder is pure: the API resolves the caller's permissions and patient scope, loads only
records the caller may already read, and passes them here. Facts carry structured fields only -
status codes, localized labels, rule ids, dates and counts. They never carry names, dates of birth,
contact details, record ids, staff/internal notes, patient free text or user ids. Suggested next
steps are derived deterministically from existing workflow states; the model only restates them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Iterable

from app.core.i18n import label, t
from app.models.identity import TASK_TERMINAL_STATUSES
from app.services.explanation import REASON_DESCRIPTIONS

TASKS = ("coordination_summary", "clinical_review", "population_briefing")
_OPEN_REQUESTS = frozenset({"submitted", "acknowledged", "scheduled"})
_ACTIVE_APPOINTMENTS = frozenset({"scheduled", "rescheduled"})


@dataclass(frozen=True)
class CopilotInput:
    """What the API hands to `AIService.staff_copilot` and returns to the caller."""

    task: str
    facts: dict[str, Any]
    fallback: dict[str, Any]
    steps: list[dict[str, str]]
    sources: list[str] = field(default_factory=list)


def _iso(value: date | datetime | None) -> str | None:
    if value is None:
        return None
    return (value.date() if isinstance(value, datetime) else value).isoformat()


def _steps(codes: Iterable[str], loc: str) -> list[dict[str, str]]:
    seen: list[str] = []
    for c in codes:
        if c not in seen:
            seen.append(c)
    return [{"code": c, "label": t(f"copilot.step.{c}", loc)} for c in seen]


def _sources(keys: Iterable[str], loc: str) -> list[str]:
    return [t(f"copilot.source.{k}", loc) for k in keys]


def _fallback(summary: str, points: list[str], questions: list[str]) -> dict[str, Any]:
    return {"summary": summary, "points": points[:6], "questions": questions[:5]}


# --- care coordinator ------------------------------------------------------------------------


def coordination(
    *, loc: str, gaps: list[Any], tasks: list[Any], events: dict[str, list[Any]],
    requests: list[Any] | None, appointments: list[Any], today: date, can_draft_outreach: bool,
    programme_of: Any,
) -> CopilotInput:
    """`events` maps task id -> its events (only `contact_attempt` / `patient_response` codes are
    used); `requests` is None when the caller may not manage patient requests."""
    open_gaps = [g for g in gaps if g.status == "open"]
    active = [tk for tk in tasks if tk.status not in TASK_TERMINAL_STATUSES]
    upcoming = [a for a in appointments if a.status in _ACTIVE_APPOINTMENTS]
    open_reqs = [r for r in (requests or []) if r.status in _OPEN_REQUESTS]

    def overdue(tk: Any) -> bool:
        return tk.due_date is not None and tk.due_date < today

    task_facts = []
    for tk in active:
        evs = events.get(tk.task_id, [])
        contacts = [e for e in evs if e.event_type == "contact_attempt"]
        replies = [e for e in evs if e.event_type == "patient_response"]
        task_facts.append({
            "rule_id": tk.rule_id, "status": tk.status, "status_label": label("task_status", tk.status, loc),
            "priority": tk.priority, "due_date": _iso(tk.due_date), "overdue": overdue(tk),
            "assigned": tk.assigned_to_user_id is not None, "patient_visible": tk.patient_visible,
            "patient_reported_completion": tk.patient_reported_completion,
            "contact_attempts": [{"channel": e.contact_channel, "outcome": e.response_code,
                                  "outcome_label": label("contact_outcome", e.response_code, loc),
                                  "on": _iso(e.created_at)} for e in contacts[-5:]],
            "last_patient_response": replies[-1].response_code if replies else None,
        })

    codes: list[str] = []
    for r in open_reqs:
        if r.request_type == "appointment_change":
            codes.append("review_appointment_change")
        elif r.status == "submitted":
            codes.append("acknowledge_request")
    for tk in active:
        if tk.status == "patient_responded":
            codes.append("review_patient_response")
        if tk.patient_reported_completion:
            codes.append("verify_reported_completion")
        if overdue(tk):
            codes.append("review_overdue_task")
        if tk.assigned_to_user_id is None:
            codes.append("assign_task")
    tasked_gaps = {tk.care_gap_id for tk in active}
    handled_gaps = {a.care_gap_id for a in upcoming} | {r.care_gap_id for r in open_reqs}
    for g in open_gaps:
        if g.care_gap_id not in tasked_gaps:
            codes.append("create_follow_up_task")
        if can_draft_outreach and g.care_gap_id not in handled_gaps:
            codes.append("prepare_outreach_draft")
    steps = _steps(codes, loc)

    facts: dict[str, Any] = {
        "language": loc,
        "today": today.isoformat(),
        "open_care_gaps": [{"rule_id": g.rule_id, "programme": programme_of(g.rule_id), "gap_type": g.gap_type,
                            "status": g.status, "status_label": label("care_gap_status", g.status, loc),
                            "identified_on": _iso(g.identified_date)} for g in open_gaps],
        "follow_up_tasks": task_facts,
        "appointments": [{"type": a.appointment_type, "type_label": label("appointment_type", a.appointment_type, loc),
                          "status": a.status, "status_label": label("appointment_status", a.status, loc),
                          "scheduled_on": _iso(a.scheduled_datetime)} for a in appointments[:10]],
        "counts": {"open_care_gaps": len(open_gaps), "active_tasks": len(active),
                   "overdue_tasks": sum(overdue(tk) for tk in active), "upcoming_appointments": len(upcoming),
                   "open_patient_requests": len(open_reqs) if requests is not None else None},
        "suggested_next_steps": [s["label"] for s in steps],
    }
    if requests is not None:
        facts["patient_requests"] = [
            {"type": r.request_type, "type_label": label("request_type", r.request_type, loc), "status": r.status,
             "status_label": label("request_status", r.status, loc), "change_action": r.change_action,
             "submitted_on": _iso(r.created_at), "has_message": bool(r.message)} for r in open_reqs]

    c = facts["counts"]
    points = [t("copilot.coord.gap", loc, rule_id=g["rule_id"], status=g["status_label"], date=g["identified_on"])
              for g in facts["open_care_gaps"][:3]]
    points += [t("copilot.coord.task", loc, status=tf["status_label"],
                 priority=label("task_priority", tf["priority"], loc),
                 due=tf["due_date"] or t("copilot.none_recorded", loc)) for tf in task_facts[:2]]
    attempts = [a for tf in task_facts for a in tf["contact_attempts"]]
    if attempts:
        points.append(t("copilot.coord.contacts", loc, count=len(attempts), outcome=attempts[-1]["outcome_label"]))
    points += [t("copilot.coord.request", loc, request_type=r["type_label"], status=r["status_label"])
               for r in facts.get("patient_requests", [])[:2]]
    fallback = _fallback(
        t("copilot.coord.summary", loc, gaps=c["open_care_gaps"], tasks=c["active_tasks"], overdue=c["overdue_tasks"],
          requests=c["open_patient_requests"] if requests is not None else t("copilot.none_recorded", loc),
          appointments=c["upcoming_appointments"]),
        points, [t(f"copilot.coord.q.{q}", loc) for q in ("preferred_time", "elsewhere", "contact", "help")],
    )
    sources = ["care_gaps", "tasks", "contact_attempts", "appointments"] + (["requests"] if requests is not None else [])
    return CopilotInput("coordination_summary", facts, fallback, steps, _sources(sources, loc))


# --- clinician ----------------------------------------------------------------------------------


def clinical_review(
    *, loc: str, evaluations: list[Any], gaps: list[Any], history_by_pathway: dict[str, str],
    next_steps: dict[str, str | None],
) -> CopilotInput:
    """In-band results only (out-of-band / not-eligible results say nothing about the person);
    reason codes become approved descriptions; no priority scores, snapshots or free text."""
    relevant = [e for e in evaluations if e.applicability != "out_of_band" and e.evaluation_status != "not_eligible"]
    open_gaps = [g for g in gaps if g.status == "open"]
    review = [e for e in relevant if e.evaluation_status == "requires_clinical_review"]
    items = []
    for e in relevant:
        items.append({
            "rule_id": e.rule_id, "programme": e.pathway, "evaluation_status": e.evaluation_status,
            "status_label": label("evaluation_status", e.evaluation_status, loc),
            "review_origin": e.review_origin, "rule_is_authoritative": e.is_authoritative,
            "next_due_date": _iso(e.next_due_date),
            "reasons": [REASON_DESCRIPTIONS.get(r.reason_code, r.reason_code) for r in e.reasons][:4],
            "open_care_gaps": [g.gap_type for g in open_gaps if g.rule_id == e.rule_id],
            "documented_next_step": next_steps.get(e.rule_id),
        })
    unknown = sorted(pw for pw, st in history_by_pathway.items() if st == "not_available")
    codes = (["clinical_review"] if review else []) + (["confirm_history"] if unknown else [])
    steps = _steps(codes, loc)
    facts = {
        "language": loc,
        "evaluations": items,
        "history_by_programme": dict(history_by_pathway),
        "counts": {"evaluations": len(items), "open_care_gaps": len(open_gaps), "requires_clinical_review": len(review)},
        "suggested_next_steps": [s["label"] for s in steps],
    }
    focus = sorted(items, key=lambda i: (not i["open_care_gaps"], i["evaluation_status"] != "requires_clinical_review"))
    points = [t("copilot.clin.item", loc, rule_id=i["rule_id"], status=i["status_label"],
                reasons=" ".join(i["reasons"][:2]) or t("copilot.clin.no_reasons", loc)) for i in focus[:5]]
    points += [t("copilot.clin.history_unknown", loc, programme=label("programme", pw, loc)) for pw in unknown]
    fallback = _fallback(
        t("copilot.clin.summary", loc, evaluations=len(items), gaps=len(open_gaps), review=len(review)),
        points, [t(f"copilot.clin.q.{q}", loc) for q in ("elsewhere", "history", "preferences")],
    )
    return CopilotInput("clinical_review", facts, fallback, steps, _sources(["evaluations", "care_gaps"], loc))


# --- population health manager --------------------------------------------------------------------


def population_briefing(
    *, loc: str, aggregates: dict[str, Any], workflow: dict[str, Any] | None, open_requests: int | None,
) -> CopilotInput:
    """`aggregates` are the population-insight facts (scope-limited server-side counts);
    `workflow` the task summary counts; no individual records."""
    facts: dict[str, Any] = {"language": loc, **aggregates}
    if workflow is not None:
        facts["workflow"] = {
            "active_tasks": workflow["active"], "overdue_tasks": workflow["overdue"],
            "unassigned_active_tasks": workflow["unassigned_active"],
            "waiting_for_patient": workflow["by_status"].get("awaiting_patient", 0),
            "patient_replied": workflow["by_status"].get("patient_responded", 0),
            "patient_reported_completion": workflow["patient_reported_completion"],
        }
    if open_requests is not None:
        facts["open_patient_requests"] = open_requests
    wf = facts.get("workflow") or {}
    codes = (["review_unassigned"] if wf.get("unassigned_active_tasks") else []) \
        + (["review_overdue"] if wf.get("overdue_tasks") else []) \
        + (["review_open_requests"] if open_requests else []) \
        + (["clinical_review"] if aggregates.get("review_flagged_patients_count") else []) \
        + (["confirm_history"] if aggregates.get("unknown_history_patients_count") else [])
    steps = _steps(codes, loc)
    facts["suggested_next_steps"] = [s["label"] for s in steps]
    points = [t("copilot.pop.pathway", loc, programme=label("programme", pw, loc), count=n)
              for pw, n in sorted((aggregates.get("open_gaps_by_pathway") or {}).items())]
    points.append(t("copilot.pop.history", loc, unknown=aggregates.get("unknown_history_patients_count", 0),
                    review=aggregates.get("review_flagged_patients_count", 0)))
    if wf:
        points.append(t("copilot.pop.workflow", loc, active=wf["active_tasks"], overdue=wf["overdue_tasks"],
                        unassigned=wf["unassigned_active_tasks"], waiting=wf["waiting_for_patient"]))
    if open_requests is not None:
        points.append(t("copilot.pop.requests", loc, count=open_requests))
    fallback = _fallback(
        t("copilot.pop.summary", loc, total=aggregates.get("total_patients", 0),
          gaps=aggregates.get("open_care_gaps_count", 0)),
        points, [t(f"copilot.pop.q.{q}", loc) for q in ("capacity", "unassigned", "history")],
    )
    sources = ["aggregates"] + (["workflow"] if workflow is not None else []) + (["requests"] if open_requests is not None else [])
    return CopilotInput("population_briefing", facts, fallback, steps, _sources(sources, loc))
