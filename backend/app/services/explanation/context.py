"""Deterministic evidence context for an individual explanation.

Everything here is read from the engine's stored evaluation, the person's care gaps and the
transcribed rule. Nothing is inferred: missing attributes or history are listed as missing (never
as completed, due or overdue), and conflicts between stored records are surfaced, not resolved.

`provider_facts()` is the minimal, de-identified subset that may be sent to an LLM: no patient,
evaluation or care-gap id, name, age, sex, consent state or care-gap dates.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from app.schemas.v1 import CareGapOut, EvaluationItemOut, RuleDetailOut
from app.services.care_pathway import _PATHWAY_NOTICE as PATHWAY_NOTICE
from app.services.care_pathway import recommended_pathway
from app.services.explanation.service import REASON_DESCRIPTIONS

_MISSING_REASON_CODES = frozenset(
    {
        "missing_date_of_birth",
        "missing_sex",
        "missing_required_attribute",
        "missing_screening_history",
        "rule_item_unresolved",
    }
)
_CONFLICT_REASON_CODES = frozenset({"conflicting_records"})
_PROVIDER_EVIDENCE_CODES = frozenset(
    {"engine_result", "applicability", "history_status", "documented_activity", "referral", "engine_reason"}
)
_REVIEW_NOTICE = (
    "No automated next step is offered; the evaluation routes to a healthcare professional for "
    "clinical review."
)


@dataclass(frozen=True)
class Evidence:
    code: str
    label: str
    value: str


@dataclass(frozen=True)
class ExplanationContext:
    evaluation_id: str
    rule_id: str
    pathway: str
    evaluation_status: str
    history_status: str
    next_due_date: str | None
    why_identified: str
    care_gaps: tuple[dict[str, Any], ...]
    supporting_evidence: tuple[Evidence, ...]
    missing_information: tuple[str, ...]
    conflicting_information: tuple[str, ...]
    rule_meaning: dict[str, Any]
    next_step: dict[str, Any] | None
    review_origin: str | None = None
    references: dict[str, Any] = field(default_factory=dict)

    @property
    def has_documented_completion(self) -> bool:
        return self.evaluation_status == "completed" or any(
            g["status"] == "closed_completed" for g in self.care_gaps
        )

    def provider_facts(self) -> dict[str, Any]:
        rm = self.rule_meaning
        return {
            "rule_description": rm["description"],
            "eligibility_as_printed": rm["eligibility_as_printed"],
            "frequency_as_printed": rm["frequency_as_printed"],
            "rule_requires_clinical_review": rm["requires_clinical_review"],
            "review_origin": self.review_origin,
            "care_gaps": [{"gap_type": g["gap_type"], "status": g["status"]} for g in self.care_gaps],
            "documented_evidence": [
                f"{e.label}: {e.value}" for e in self.supporting_evidence if e.code in _PROVIDER_EVIDENCE_CODES
            ],
            "missing_information": list(self.missing_information),
            "conflicting_information": list(self.conflicting_information),
            "documented_next_step": (self.next_step or {}).get("description"),
        }


def _yes_no(v: bool | None) -> str:
    return "not recorded" if v is None else ("yes" if v else "no")


def build_explanation_context(
    evaluation: EvaluationItemOut,
    rule: RuleDetailOut,
    care_gaps: list[CareGapOut],
) -> ExplanationContext:
    snap = evaluation.input_snapshot or {}
    status = evaluation.evaluation_status
    history = snap.get("history_status") or "not_available"
    rid = f"{rule.rule_id} v{rule.rule_version}"
    spec = rule.spec or {}
    gaps = [g.model_dump(include={"care_gap_id", "gap_type", "status", "identified_date", "closed_date"})
            for g in care_gaps]
    for g in gaps:
        for k in ("identified_date", "closed_date"):
            g[k] = g[k].isoformat() if g[k] is not None else None

    evidence: list[Evidence] = [
        Evidence("engine_result", "Deterministic engine result",
                 f"{status}" + (f" ({evaluation.reason_detail})" if evaluation.reason_detail else "")),
    ]
    missing: list[str] = []
    conflicts: list[str] = []

    if evaluation.applicability == "not_determined":
        missing.append("Whether the person is inside the rule's printed age/sex band could not be determined.")
    else:
        evidence.append(Evidence("applicability", "Inside the rule's printed age/sex band",
                                 "yes" if evaluation.applicability == "in_band" else "no"))
    if snap.get("age_years") is None:
        missing.append("Date of birth is not recorded.")
    else:
        age = (f"{snap['age_months']} months" if evaluation.pathway == "well_child" and snap.get("age_months") is not None
               else f"{snap['age_years']} years")
        evidence.append(Evidence("age", "Age at the evaluation reference date", age))
    if snap.get("sex") in (None, "unknown"):
        missing.append("Sex is not recorded.")
    else:
        evidence.append(Evidence("sex", "Recorded sex", str(snap["sex"])))
    if evaluation.pathway == "ifhas":
        if snap.get("thiqa_member") is None:
            missing.append("Thiqa membership is not recorded.")
        else:
            evidence.append(Evidence("thiqa_member", "Thiqa member", _yes_no(snap["thiqa_member"])))
    if "smok" in json.dumps(spec.get("eligibility") or {}).lower() and snap.get("ever_smoked") is None:
        missing.append("Smoking history is not recorded.")

    evidence.append(Evidence("history_status", f"Screening/visit history ({evaluation.pathway})", history))
    if history == "not_available":
        missing.append(
            f"Screening/visit history for the {evaluation.pathway} pathway is not available; completion "
            "is unknown and is not assumed to be completed, due or overdue."
        )
    else:
        if history == "partial":
            missing.append(
                f"Screening/visit history for the {evaluation.pathway} pathway is partial; earlier "
                "events may be missing from the record."
            )
        evidence.append(Evidence(
            "documented_activity", "Documented screening/visit for this rule",
            "yes" if snap.get("has_prior_screening_or_visit")
            else f"none found in the {'partial ' if history == 'partial' else ''}available history",
        ))
    if snap.get("has_referral"):
        evidence.append(Evidence("referral", "Linked referral on record", "yes"))
    if snap.get("screening_consent_state"):
        evidence.append(Evidence("screening_consent", "Screening participation consent",
                                 str(snap["screening_consent_state"])))

    for r in evaluation.reasons:
        if r.reason_code == "missing_screening_history" and history == "not_available":
            continue  # already stated above
        text = REASON_DESCRIPTIONS.get(r.reason_code) or r.reason_detail or r.reason_code
        if r.reason_code in _MISSING_REASON_CODES:
            missing.append(text)
        elif r.reason_code in _CONFLICT_REASON_CODES:
            conflicts.append(text)
        else:
            evidence.append(Evidence("engine_reason", "Engine reason", text))

    non_evaluable = [c for c in (spec.get("eligibility") or {}).get("conditions") or []
                     if c.get("machine_evaluable") is False]
    if non_evaluable:
        missing.append(
            f"The rule prints {len(non_evaluable)} eligibility condition(s) that cannot be evaluated "
            "from structured data; they need professional review."
        )
    if rule.open_question_ids:
        missing.append(f"Unresolved open questions affect this rule: {', '.join(rule.open_question_ids)}.")

    if evaluation.superseded_by_completion:
        conflicts.append(
            "A care gap from this evaluation was later closed as completed (see care_gaps); the "
            f"'{status}' result is the historical evaluation for its reference date."
        )
    if status == "completed" and history != "available":
        conflicts.append(f"The engine recorded a completion while pathway history is '{history}'.")
    if any(g["status"] == "closed_refused" for g in gaps):
        evidence.append(Evidence("engine_reason", "Care gap status", "closed after a documented refusal"))

    open_gaps = [g for g in care_gaps if g.status == "open"]
    if open_gaps:
        why = (
            f"Identified because evaluation {evaluation.evaluation_id} under {rid} returned "
            f"'{status}' and {len(open_gaps)} open care gap(s) were recorded: "
            + ", ".join(f"{g.care_gap_id} ({g.gap_type}, identified {g.identified_date.isoformat()})"
                        for g in open_gaps) + "."
        )
    else:
        why = (
            f"Evaluation {evaluation.evaluation_id} under {rid} returned '{status}'; no open care gap "
            "is recorded for this rule."
        )
    if status == "requires_clinical_review" and evaluation.review_origin:
        why += (" The rule itself requires clinical review." if evaluation.review_origin == "rule"
                else " The person's records require clinical review.")

    # A next step is only offered for an open gap; closed gaps (completed/refused) need none.
    if open_gaps:
        next_step: dict[str, Any] | None = recommended_pathway(open_gaps[0].model_dump(), rule.model_dump())
    elif status == "requires_clinical_review":
        next_step = {
            "status": "requires_clinical_review",
            "next_step": None,
            "description": _REVIEW_NOTICE,
            "rule_id": rule.rule_id,
            "rule_version": rule.rule_version,
            "source_reference": rule.source_reference,
            "details": {},
            "related_rule_ids": [],
            "notice": PATHWAY_NOTICE,
        }
    else:
        next_step = None

    rule_meaning = {
        "description": rule.description,
        "eligibility_as_printed": ((spec.get("eligibility") or {}).get("age") or {}).get("as_printed"),
        "frequency_as_printed": (spec.get("frequency") or {}).get("as_printed"),
        "verification_status": rule.verification_status,
        "is_authoritative": rule.is_authoritative,
        "requires_clinical_review": rule.requires_clinical_review,
        "open_question_ids": list(rule.open_question_ids),
        "citation": f"{rule.source_name} — {rule.source_reference} ({rid})",
    }
    return ExplanationContext(
        evaluation_id=evaluation.evaluation_id,
        rule_id=rule.rule_id,
        pathway=evaluation.pathway,
        evaluation_status=status,
        history_status=history,
        next_due_date=evaluation.next_due_date.isoformat() if evaluation.next_due_date else None,
        why_identified=why,
        care_gaps=tuple(gaps),
        supporting_evidence=tuple(evidence),
        missing_information=tuple(missing),
        conflicting_information=tuple(conflicts),
        rule_meaning=rule_meaning,
        next_step=next_step,
        review_origin=evaluation.review_origin,
        references={
            "evaluation_id": evaluation.evaluation_id,
            "care_gap_ids": [g["care_gap_id"] for g in gaps],
        },
    )
