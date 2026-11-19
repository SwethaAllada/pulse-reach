"""Deterministic care-gap pathway, rule applicability and review origin (BE-18, BE-19, BE-21).

Everything returned here is read from the transcribed rule specification (`spec`, as printed in
the source standard) and the gap type. Nothing is inferred clinically: when the rule does not
document a next step, the result says so; when the rule is not authoritative, the next step is
withheld and clinical review is required.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date
from typing import Any

# Engine reason codes meaning the *rule* (not the patient's records) needs review.
RULE_ORIGIN_REVIEW_CODES = frozenset({"rule_requires_clinical_review", "rule_unresolved"})

# Programme-scope rules whose printed bounds apply to every rule of their pathway.
_PROGRAMME_SCOPE_RULES = {"well_child": "WCV-PROG-SCOPE", "ifhas": "IFHAS-PROG-ELIG-MIN-AGE"}

_PATHWAY_NOTICE = (
    "Next step transcribed from the cited standard (clinical_review_status=not_reviewed); "
    "it is not a clinical recommendation for this person and requires professional judgement."
)


def review_origin(evaluation_status: str, reason_code: str | None) -> str | None:
    """`rule` when the rule itself needs review, `record` when the person's records do."""
    if evaluation_status != "requires_clinical_review":
        return None
    return "rule" if reason_code in RULE_ORIGIN_REVIEW_CODES else "record"


def _age_months(dob: date, ref: date) -> int:
    months = (ref.year - dob.year) * 12 + (ref.month - dob.month)
    return months - (1 if ref.day < dob.day else 0)


def _bound_months(bound: Mapping[str, Any] | None) -> int | None:
    if not bound or bound.get("value") is None:
        return None
    unit = bound.get("unit")
    if unit == "years":
        return int(bound["value"]) * 12
    if unit == "months":
        return int(bound["value"])
    return None


def _rule_band(rule: Mapping[str, Any]) -> tuple[int | None, int | None, tuple[str, ...] | None]:
    """Printed age band in months and sexes of a rule.

    Same convention as the engine: completed years compared inclusively, so `40-64 years`
    covers 40y0m .. 64y11m. Programme-scope rules print their bounds in `spec`
    (`age_min`/`age_max` with units, or `min_years`/`max_years`).
    """
    spec = rule.get("spec") or {}
    lo_y = rule.get("age_min_years", spec.get("min_years"))
    hi_y = rule.get("age_max_years", spec.get("max_years"))
    if lo_y is None:
        lo_y = spec.get("min_years")
    if hi_y is None:
        hi_y = spec.get("max_years")
    lo = int(lo_y) * 12 if lo_y is not None else _bound_months(spec.get("age_min"))
    if hi_y is not None:
        hi = (int(hi_y) + 1) * 12 - 1
    else:
        top = spec.get("age_max")
        hi = _bound_months(top)
        if hi is not None and top.get("unit") == "years":
            hi += 11
    sexes = rule.get("sexes")
    return lo, hi, tuple(sexes) if sexes else None


def rule_applicability(
    rule: Mapping[str, Any] | None,
    rules_by_id: Mapping[str, Mapping[str, Any]],
    *,
    date_of_birth: date | None,
    sex: str | None,
    reference_date: date,
) -> tuple[str, str | None]:
    """Return `(applicability, basis)`: is the person inside the rule's printed band?

    `basis` is `rule_band` (the rule's own age/sex band) or `programme_scope` (the pathway's
    scope rule). Without a printed band, or without the needed person attributes, the result is
    `not_determined` - never assumed in band. Age uses completed months as of the reference date
    (the engine's convention; OQ-COMMON-AGE-CALC remains open).
    """
    if rule is None:
        return "not_determined", None
    lo, hi, sexes = _rule_band(rule)
    basis = "rule_band"
    if lo is None and hi is None and sexes is None:
        scope = rules_by_id.get(_PROGRAMME_SCOPE_RULES.get(str(rule.get("pathway")), ""))
        if scope is None or scope.get("rule_id") == rule.get("rule_id"):
            return "not_determined", None
        lo, hi, sexes = _rule_band(scope)
        basis = "programme_scope"
        if lo is None and hi is None and sexes is None:
            return "not_determined", None
    if sexes is not None:
        if sex is None:
            return "not_determined", basis
        if sex not in sexes:
            return "out_of_band", basis
    if lo is not None or hi is not None:
        if date_of_birth is None:
            return "not_determined", basis
        months = _age_months(date_of_birth, reference_date)
        if (lo is not None and months < lo) or (hi is not None and months > hi):
            return "out_of_band", basis
    return "in_band", basis


def recommended_pathway(gap: Mapping[str, Any], rule: Mapping[str, Any]) -> dict[str, Any]:
    """Next documented step for a care gap, taken verbatim from the rule spec."""
    spec: Mapping[str, Any] = rule.get("spec") or {}
    base = {
        "rule_id": rule["rule_id"],
        "rule_version": rule["rule_version"],
        "source_reference": rule.get("source_reference"),
        "notice": _PATHWAY_NOTICE,
    }
    if not rule.get("is_authoritative") or rule.get("requires_clinical_review"):
        return {
            **base,
            "status": "requires_clinical_review",
            "next_step": None,
            "description": "The rule is not authoritative or is flagged for clinical review; "
            "no next step is offered until it is reviewed.",
            "details": {},
            "related_rule_ids": [],
        }

    gap_type, rule_type = gap["gap_type"], rule.get("rule_type")
    related: list[str] = []
    for req in spec.get("follow_up_requirements") or []:
        related.extend(req.get("rule_refs") or [])
    details: dict[str, Any] = {}
    if gap_type == "referral_not_initiated":
        step = "initiate_referral"
        desc = "Initiate the follow-up referral documented for this result."
        details = {
            "timing_as_printed": spec.get("as_printed"),
            "timing": spec.get("timing"),
            "follow_up_requirements": [
                {"code": r.get("code"), "description": r.get("description")}
                for r in spec.get("follow_up_requirements") or []
            ],
        }
    elif rule_type == "screening_package":
        step = "complete_outstanding_components" if gap_type == "partial_completion" else "offer_screening_package"
        desc = (
            "Complete the outstanding package components."
            if gap_type == "partial_completion"
            else "Offer the screening package printed in the standard."
        )
        details = {
            "package_name": spec.get("package_name"),
            "frequency_as_printed": (spec.get("frequency") or {}).get("as_printed"),
            "components": list(spec.get("components") or []),
        }
    elif rule_type == "visit_schedule":
        step = "schedule_well_child_visit"
        desc = "Schedule the well-child visit printed in the standard."
        timing = spec.get("timing") or {}
        details = {
            "visit_label": spec.get("visit_label"),
            "recommended_age_as_printed": (timing.get("recommended_age") or {}).get("as_printed"),
            "due_window_status": timing.get("due_window_status"),
            "preventive_assessments": [a.get("code") for a in spec.get("preventive_assessments") or []],
        }
    else:
        return {
            **base,
            "status": "no_documented_pathway",
            "next_step": None,
            "description": f"The standard documents no next step for a '{gap_type}' gap on a "
            f"'{rule_type}' rule.",
            "details": {},
            "related_rule_ids": sorted(set(related)),
        }
    return {
        **base,
        "status": "documented_next_step",
        "next_step": step,
        "description": desc,
        "details": {k: v for k, v in details.items() if v not in (None, [], {})},
        "related_rule_ids": sorted(set(related)),
    }


def rules_index(rules: Iterable[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    return {r["rule_id"]: r for r in rules}
