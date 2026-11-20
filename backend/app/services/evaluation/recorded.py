"""Reason text and safe input snapshot recorded with an evaluation at evaluation time (F-12).

Both are computed from the engine result and the `PatientContext` the engine saw, and are stored
with the evaluation (`eligibility_evaluation.reason_detail` / `input_snapshot`,
`evaluation_reason.reason_detail`), so later changes to consents, referrals or history never
rewrite what an evaluation was based on.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from app.services.evaluation.engine import FiredReason, PatientContext, RuleEvaluationResult

SNAPSHOT_RECORDED = "recorded_at_evaluation"
SNAPSHOT_RECONSTRUCTED = "reconstructed_at_read"

REASON_DETAIL_TEMPLATES: dict[str, str] = {
    "due": "Patient meets eligibility criteria and screening/visit is due now.",
    "due_now": "Patient meets eligibility criteria and screening/visit is due now.",
    "upcoming": "Patient meets eligibility criteria and next due date falls within the look-ahead window.",
    "due_within_lookahead": "Patient meets eligibility criteria and next due date falls within the look-ahead window.",
    "overdue": "Patient meets eligibility criteria and the approved overdue window has elapsed.",
    "completed": "Screening/visit has documented completion within the active interval.",
    "eligible": "Patient meets programme eligibility criteria.",
    "not_eligible": "Patient does not meet eligibility criteria for this rule.",
    "unknown": "Screening/visit history is unavailable; status cannot be assumed due.",
    "insufficient_information": "Required patient demographic or clinical attributes are missing.",
    "requires_clinical_review": "Rule or clinical state requires clinical review before recommendation.",
    "history_not_available": "Screening/visit history for this pathway is not available; status remains unknown.",
    "missing_required_attributes": "Required patient demographic or clinical attributes are missing.",
    "rule_requires_clinical_review": "Rule or required open question is unresolved and requires clinical review.",
    "consent_refused_valid": "Valid documented refusal on file for this screening or pathway.",
    "referral_cancelled": "Linked referral was cancelled and requires clinical review.",
    "referral_status_unresolved": "Linked referral has a status that requires clinical review.",
    "missing_completion_evidence": "Linked record is marked completed without documented completion evidence.",
    "referral_pending": "Linked referral is currently pending.",
    "referral_upcoming": "Linked referral is initiated or scheduled.",
    "referral_completed": "Linked referral has documented completion.",
    "completed_within_interval": "Most recent screening/visit was completed within the active rule interval.",
    "age_out_of_range": "Patient age is outside the rule's target age range.",
    "sex_mismatch": "Rule applies to a different sex than recorded for the patient.",
    "deceased": "Patient is recorded as deceased.",
    "not_thiqa_member": "Rule requires Thiqa membership which is not recorded for the patient.",
}


def describe_reason(
    reason_code: str | None,
    guard_id: str | None = None,
    item_category: str | None = None,
    item_code: str | None = None,
    evaluation_status: str | None = None,
) -> str | None:
    """Generic template text; used only when the engine recorded no specific detail."""
    code = reason_code or evaluation_status
    if not code:
        return None
    parts = [REASON_DETAIL_TEMPLATES.get(code, f"Evaluation reason '{code.replace('_', ' ')}'.")]
    if guard_id:
        parts.append(f"guard={guard_id}")
    if item_category or item_code:
        parts.append(f"item={item_category or ''}:{item_code or ''}".strip(":"))
    return " ".join(parts)


def fired_reason_detail(r: FiredReason) -> str | None:
    return r.detail or describe_reason(r.reason_code, r.guard_id, r.item_category, r.item_code)


def evaluation_reason_detail(ev: RuleEvaluationResult) -> str | None:
    """The engine's own detail for the primary reason, else the status/reason template."""
    primary = next((r for r in ev.reasons if r.reason_code == ev.reason_code and r.detail), None)
    if primary is not None:
        return primary.detail
    return describe_reason(ev.reason_code, evaluation_status=ev.evaluation_status)


def compute_age_parts(dob: date | None, ref_date: date) -> tuple[int | None, int | None]:
    if dob is None:
        return None, None
    years = ref_date.year - dob.year - ((ref_date.month, ref_date.day) < (dob.month, dob.day))
    months = (ref_date.year - dob.year) * 12 + (ref_date.month - dob.month)
    if ref_date.day < dob.day:
        months -= 1
    return max(years, 0), max(months, 0)


def build_safe_input_snapshot_from_context(
    *,
    ctx: PatientContext,
    pathway: str,
    has_prior_activity: bool,
    has_referral: bool,
    reference_date: date,
) -> dict[str, Any]:
    """De-identified inputs the engine used (no names, ids, DOB or contact details)."""
    age_years, age_months = compute_age_parts(ctx.date_of_birth, reference_date)
    relevant_consents = [
        c
        for c in ctx.consents
        if c.consent_type == "screening_participation" and c.scope_pathway in (None, pathway)
    ]
    latest_consent = (
        max(relevant_consents, key=lambda c: (c.recorded_at, c.consent_id)).state
        if relevant_consents
        else "absent"
    )
    return {
        "pathway": pathway,
        "age_years": age_years,
        "age_months": age_months,
        "sex": ctx.sex,
        "thiqa_member": ctx.thiqa_member,
        "ever_smoked": ctx.ever_smoked,
        "history_status": ctx.history_by_pathway.get(pathway, "not_available"),
        "screening_consent_state": latest_consent,
        "has_prior_screening_or_visit": has_prior_activity,
        "has_referral": has_referral,
    }


def evaluation_snapshot(ctx: PatientContext, ev: RuleEvaluationResult, reference_date: date) -> dict[str, Any]:
    prior_rules = {s.rule_id for s in ctx.ifhas_screenings} | {v.rule_id for v in ctx.well_child_visits}
    referral_rules = {r.trigger_rule_id for r in ctx.referrals if r.trigger_rule_id}
    return build_safe_input_snapshot_from_context(
        ctx=ctx,
        pathway=ev.pathway,
        has_prior_activity=ev.rule_id in prior_rules,
        has_referral=ev.rule_id in referral_rules,
        reference_date=reference_date,
    )
