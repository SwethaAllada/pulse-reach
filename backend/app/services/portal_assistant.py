"""Facts and deterministic answers for the patient-portal assistant.

Everything here is built from information the portal already shows the patient for one of their
own recommendations: localized labels, display dates, deterministic evidence lines and the
documented next step. The facts carry no names, ids, dates of birth, free text written by people
or staff-only fields; the model (when enabled) only restates them, and the deterministic answer
built from the same facts is used whenever it is not.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.core.i18n import t

TOPICS = ("why", "next_steps", "prepare_questions", "appointments")
_QUESTIONS = ("purpose", "prepare", "timing", "after", "elsewhere")


@dataclass(frozen=True)
class AssistantContext:
    """Portal facts of one recommendation, already localized for `locale`."""

    locale: str
    programme: str
    title: str
    description: str
    status: str
    status_label: str
    identified_on: str
    evidence: list[str]
    next_step_text: str
    next_step_documented: bool
    history: list[str]
    earlier_history_on_file: bool
    change_cutoff_hours: int
    appointments: list[dict[str, Any]] = field(default_factory=list)  # type/when/status labels
    open_requests: list[dict[str, str]] = field(default_factory=list)  # type/status labels
    follow_ups: list[dict[str, Any]] = field(default_factory=list)  # status label, due display


def _missing(ctx: AssistantContext) -> list[str]:
    out = []
    if not ctx.next_step_documented:
        out.append(t("assistant.missing.next_step", ctx.locale))
    if not ctx.earlier_history_on_file:
        out.append(t("explain.history_unknown", ctx.locale))
    if not ctx.appointments:
        out.append(t("assistant.appointments.none", ctx.locale))
    return out


def _pathway(loc: str) -> list[str]:
    return [t(f"assistant.pathway.{k}", loc) for k in ("request", "confirm", "record", "elsewhere")]


def _appointment_process(ctx: AssistantContext) -> list[str]:
    loc = ctx.locale
    return [t("assistant.appointments.change", loc, hours=ctx.change_cutoff_hours),
            t("assistant.appointments.staff_change", loc), t("assistant.appointments.messages", loc)]


def build_facts(ctx: AssistantContext, topic: str) -> dict[str, Any]:
    """The only data sent to the provider (minimum necessary, de-identified)."""
    return {
        "topic": topic,
        "language": ctx.locale,
        "programme": ctx.programme,
        "recommendation_title": ctx.title,
        "recommendation_description": ctx.description,
        "recommendation_status": ctx.status_label,
        "recommendation_status_code": ctx.status,
        "identified_on": ctx.identified_on,
        "evidence": ctx.evidence,
        "next_step": ctx.next_step_text if ctx.next_step_documented else None,
        "history": ctx.history,
        "missing_information": _missing(ctx),
        "pathway_steps": _pathway(ctx.locale),
        "appointments": ctx.appointments,
        "open_requests": ctx.open_requests,
        "follow_ups": ctx.follow_ups,
        "appointment_process": _appointment_process(ctx),
    }


def deterministic_answer(ctx: AssistantContext, topic: str) -> list[str]:
    loc = ctx.locale
    closed = [] if ctx.status == "open" else [t("assistant.closed", loc, status=ctx.status_label)]
    if topic == "why":
        return closed + list(ctx.evidence)
    if topic == "next_steps":
        steps = [ctx.next_step_text] if ctx.next_step_documented else [t("assistant.missing.next_step", loc)]
        return closed + steps + ([] if closed else _pathway(loc))
    if topic == "prepare_questions":
        return [t(f"assistant.question.{q}", loc, programme=ctx.programme) for q in _QUESTIONS]
    lines = [t("assistant.appointments.item", loc, appointment_type=a["type"], when=a["when"], status=a["status"])
             for a in ctx.appointments] or [t("assistant.appointments.none", loc)]
    lines += [t("assistant.requests.item", loc, request_type=r["type"], status=r["status"]) for r in ctx.open_requests]
    lines += [t("assistant.follow_ups.item", loc, status=f["status"]) for f in ctx.follow_ups]
    return closed + lines + _appointment_process(ctx)
