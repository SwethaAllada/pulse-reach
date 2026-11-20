"""Shared care-gap completion evidence validation (`F-01`).

Every code path that marks a care gap `closed_completed` must call
`validate_completion_evidence`. Two layers are applied:

1. Evidence-specific checks: same patient, evidence type appropriate for the gap, same rule and
   version as the gap's evaluation (the composite evidence FKs of `synthetic.care_gap`), completed
   status, and a documented, non-future date not preceding the gap.
2. Evaluation consistency: the deterministic `EvaluationEngine` is re-run for the gap's rule on
   the patient's current records (`evaluate_current_rule`). Completion is accepted only if the
   engine itself reports the rule satisfied, relying on this evidence. Interval, conflicting
   records (`GUARD-CONFLICTING-RECORDS`), history and clinical-review guards are therefore the
   engine's own; nothing is re-implemented or invented here.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

from app.services.evaluation.engine import EvaluationEngine, PatientContext, RuleEvaluationResult

# Evaluation statuses in which the engine reports the rule satisfied by a documented completion
# (`upcoming` = completed within the interval, next due inside the look-ahead window).
_SATISFIED_EVALUATION_STATUSES = frozenset({"completed", "upcoming"})

EVIDENCE_IFHAS_SCREENING = "ifhas_screening"
EVIDENCE_WELL_CHILD_VISIT = "well_child_visit"
EVIDENCE_REFERRAL = "referral"

# Only these statuses document a completed event (engine: screening `complete`,
# visit `attended`, referral `completed`). Everything else (partial, pending, initiated,
# cancelled, declined, refused, not_attended, unknown) cannot establish completion.
_COMPLETED_STATUS: dict[str, str] = {
    EVIDENCE_IFHAS_SCREENING: "complete",
    EVIDENCE_WELL_CHILD_VISIT: "attended",
    EVIDENCE_REFERRAL: "completed",
}

# Column on `care_gap` that records the closing evidence for each evidence kind.
CLOSED_BY_FIELD: dict[str, str] = {
    EVIDENCE_IFHAS_SCREENING: "closed_by_ifhas_screening_id",
    EVIDENCE_WELL_CHILD_VISIT: "closed_by_well_child_visit_id",
    EVIDENCE_REFERRAL: "closed_by_referral_id",
}


@dataclass(frozen=True)
class CompletionEvidence:
    """A normalised candidate completion event (screening, well-child visit or referral)."""

    kind: str
    evidence_id: str
    patient_id: str
    rule_id: str | None
    rule_version: str | None
    status: str | None
    evidence_date: date | None

    @classmethod
    def from_screening(cls, row: Mapping[str, Any]) -> "CompletionEvidence":
        return cls(
            kind=EVIDENCE_IFHAS_SCREENING,
            evidence_id=row["screening_id"],
            patient_id=row["patient_id"],
            rule_id=row.get("rule_id"),
            rule_version=row.get("rule_version"),
            status=row.get("completion_status"),
            evidence_date=row.get("performed_date"),
        )

    @classmethod
    def from_visit(cls, row: Mapping[str, Any]) -> "CompletionEvidence":
        return cls(
            kind=EVIDENCE_WELL_CHILD_VISIT,
            evidence_id=row["visit_id"],
            patient_id=row["patient_id"],
            rule_id=row.get("rule_id"),
            rule_version=row.get("rule_version"),
            status=row.get("attendance_status"),
            evidence_date=row.get("performed_date"),
        )

    @classmethod
    def from_referral(cls, row: Mapping[str, Any]) -> "CompletionEvidence":
        return cls(
            kind=EVIDENCE_REFERRAL,
            evidence_id=row["referral_id"],
            patient_id=row["patient_id"],
            rule_id=row.get("trigger_rule_id"),
            rule_version=row.get("trigger_rule_version"),
            status=row.get("status"),
            evidence_date=row.get("completed_date"),
        )


@dataclass(frozen=True)
class CompletionValidationResult:
    """Explicit accept/reject outcome of a completion-evidence check."""

    accepted: bool
    reason_code: str
    detail: str
    evidence_kind: str | None = None
    evidence_id: str | None = None

    @property
    def message(self) -> str:
        return f"{self.detail} (reason_code: {self.reason_code})"

    @property
    def closed_by_field(self) -> str | None:
        return CLOSED_BY_FIELD.get(self.evidence_kind or "") if self.accepted else None


def _reject(
    reason_code: str, detail: str, evidence: CompletionEvidence | None = None
) -> CompletionValidationResult:
    return CompletionValidationResult(
        accepted=False,
        reason_code=reason_code,
        detail=detail,
        evidence_kind=evidence.kind if evidence else None,
        evidence_id=evidence.evidence_id if evidence else None,
    )


def expected_evidence_kind(gap: Mapping[str, Any], rule: Mapping[str, Any]) -> str | None:
    """Evidence kind able to complete `gap`, following the engine rule branch that opened it."""
    if gap["gap_type"] == "referral_not_initiated":
        return EVIDENCE_REFERRAL
    rule_type = rule.get("rule_type")
    if rule_type == "screening_package":
        return EVIDENCE_IFHAS_SCREENING
    if rule_type == "visit_schedule":
        return EVIDENCE_WELL_CHILD_VISIT
    return None


def _screening_frequency_resolved(rule: Mapping[str, Any]) -> bool:
    """True if the rule's configured frequency is one the engine evaluates without a fallback.

    The engine interprets a recurring screening interval in years; a recurring rule without an
    interval, or in another unit, would be evaluated against a default rather than its source.
    """
    ftype = rule.get("frequency_type")
    if ftype == "once_per_lifetime":
        return True
    return (
        ftype == "recurring"
        and rule.get("interval_value") is not None
        and rule.get("interval_unit") == "years"
    )


def completion_as_of(
    reference_date: date, evidence: CompletionEvidence | None, *, today: date | None = None
) -> date:
    """The date a completion is validated, and its rule re-evaluated (`evaluate_current_rule`), as of.

    The evaluation run's reference date, advanced to the documentation date (today, UTC) only when
    the cited evidence postdates the run: a referral or screening recorded after the evaluation is
    judged by re-running the engine on the day it is documented. Never later than today, so evidence
    dated in the future is still rejected (`evidence_date_in_future`).
    """
    if evidence is None or evidence.evidence_date is None or evidence.evidence_date <= reference_date:
        return reference_date
    return max(reference_date, today or datetime.now(timezone.utc).date())


def evaluate_current_rule(
    engine: EvaluationEngine,
    ctx: PatientContext | None,
    *,
    rule_id: str,
    rule_version: str,
    as_of: date,
    look_ahead_days: int | None,
) -> RuleEvaluationResult | None:
    """Re-run the engine on the patient's current records and return the result for one rule.

    The result is used only to validate completion; it is never persisted, so historical
    evaluation runs are not rewritten.
    """
    if ctx is None:
        return None
    summary = engine.evaluate_patient(ctx, reference_date=as_of, look_ahead_days=look_ahead_days)
    return next(
        (
            ev
            for ev in summary.evaluations
            if ev.rule_id == rule_id and ev.rule_version == rule_version
        ),
        None,
    )


def validate_completion_evidence(
    *,
    gap: Mapping[str, Any],
    rule: Mapping[str, Any] | None,
    evidence: CompletionEvidence | None,
    documented_evidence: bool,
    evidence_reference: str | None,
    as_of: date,
    current_evaluation: RuleEvaluationResult | None,
) -> CompletionValidationResult:
    """Decide whether `evidence` documents completion of this specific care gap as of `as_of`.

    `current_evaluation` is the engine's result for the gap's rule on the patient's current
    records (see `evaluate_current_rule`), including the cited evidence.
    """
    gap_id = gap["care_gap_id"]
    if gap["status"] != "open":
        return _reject(
            "care_gap_not_open", f"Cannot close care gap '{gap_id}' with status '{gap['status']}'."
        )
    ref = (evidence_reference or "").strip()
    if not documented_evidence or not ref:
        return _reject(
            "evidence_missing",
            "Closing a care gap as 'closed_completed' requires documented completion evidence "
            "(documented_evidence=True and non-empty evidence_reference).",
        )
    if evidence is None:
        return _reject(
            "evidence_not_found",
            f"evidence_reference '{ref}' must reference an existing screening, "
            f"well-child visit, or referral for patient '{gap['patient_id']}'.",
        )
    if evidence.patient_id != gap["patient_id"]:
        return _reject(
            "evidence_patient_mismatch",
            f"Evidence '{evidence.evidence_id}' does not belong to patient '{gap['patient_id']}'.",
            evidence,
        )
    if (
        rule is None
        or rule.get("rule_id") != gap["rule_id"]
        or rule.get("rule_version") != gap["rule_version"]
    ):
        return _reject(
            "rule_not_found",
            f"Rule '{gap['rule_id']}' v'{gap['rule_version']}' for care gap '{gap_id}' is not "
            "available; completion cannot be established.",
            evidence,
        )
    if rule.get("verification_status") != "verified" or rule.get("requires_clinical_review"):
        return _reject(
            "rule_not_authoritative",
            f"Rule '{gap['rule_id']}' is not verified or requires clinical review; completion "
            "cannot be established.",
            evidence,
        )
    expected = expected_evidence_kind(gap, rule)
    if expected is None:
        return _reject(
            "no_completion_evidence_mapping",
            f"No documented completion evidence type exists for gap type '{gap['gap_type']}' on "
            f"rule '{gap['rule_id']}' (rule_type '{rule.get('rule_type')}').",
            evidence,
        )
    if evidence.kind != expected:
        return _reject(
            "evidence_type_mismatch",
            f"Evidence '{evidence.evidence_id}' is a {evidence.kind}; care gap '{gap_id}' "
            f"requires {expected} evidence.",
            evidence,
        )
    if evidence.rule_id != gap["rule_id"] or evidence.rule_version != gap["rule_version"]:
        return _reject(
            "evidence_rule_mismatch",
            f"Evidence '{evidence.evidence_id}' is for rule '{evidence.rule_id}' "
            f"v'{evidence.rule_version}', not '{gap['rule_id']}' v'{gap['rule_version']}'.",
            evidence,
        )
    subject_ref = gap.get("subject_referral_id")
    if expected == EVIDENCE_REFERRAL and subject_ref and evidence.evidence_id != subject_ref:
        return _reject(
            "evidence_subject_mismatch",
            f"Care gap '{gap_id}' concerns referral '{subject_ref}', not '{evidence.evidence_id}'.",
            evidence,
        )
    required_status = _COMPLETED_STATUS[evidence.kind]
    if evidence.status != required_status:
        return _reject(
            "evidence_not_completed",
            f"Evidence '{evidence.evidence_id}' has status '{evidence.status}'; only "
            f"'{required_status}' documents completion.",
            evidence,
        )
    ev_date = evidence.evidence_date
    if ev_date is None:
        return _reject(
            "evidence_date_missing",
            f"Evidence '{evidence.evidence_id}' has no documented completion date.",
            evidence,
        )
    if ev_date > as_of:
        return _reject(
            "evidence_date_in_future",
            f"Evidence '{evidence.evidence_id}' is dated {ev_date}, after {as_of}.",
            evidence,
        )
    # `no_documented_screening` gaps are identified on the evaluation reference date (when the
    # absence was observed), so their identified_date is not a lower bound for the event.
    identified = gap.get("identified_date")
    if gap["gap_type"] != "no_documented_screening" and identified and ev_date < identified:
        return _reject(
            "evidence_predates_gap",
            f"Evidence '{evidence.evidence_id}' is dated {ev_date}, before care gap '{gap_id}' "
            f"was identified on {identified}.",
            evidence,
        )
    if evidence.kind == EVIDENCE_IFHAS_SCREENING and not _screening_frequency_resolved(rule):
        return _reject(
            "rule_interval_unresolved",
            f"Rule '{gap['rule_id']}' has no resolvable screening interval; completion "
            "cannot be established.",
            evidence,
        )
    current = current_evaluation
    if (
        current is None
        or current.rule_id != gap["rule_id"]
        or current.rule_version != gap["rule_version"]
    ):
        return _reject(
            "evaluation_unavailable",
            f"No current evaluation of rule '{gap['rule_id']}' is available for patient "
            f"'{gap['patient_id']}'; completion cannot be established.",
            evidence,
        )
    if current.evaluation_status == "requires_clinical_review":
        return _reject(
            "evaluation_requires_clinical_review",
            f"Evaluating rule '{gap['rule_id']}' on current records requires clinical review "
            f"(reason '{current.reason_code}'); the gap cannot be closed as completed through "
            "the follow-up path.",
            evidence,
        )
    if (
        current.evaluation_status not in _SATISFIED_EVALUATION_STATUSES
        or current.last_completed_date is None
    ):
        return _reject(
            "evaluation_not_completed",
            f"Evaluating rule '{gap['rule_id']}' on current records gives "
            f"'{current.evaluation_status}' (reason '{current.reason_code}'), not completed.",
            evidence,
        )
    if current.last_completed_date != ev_date:
        return _reject(
            "evidence_not_relied_on",
            f"The current evaluation of rule '{gap['rule_id']}' relies on a completion dated "
            f"{current.last_completed_date}, not evidence '{evidence.evidence_id}' dated {ev_date}.",
            evidence,
        )
    return CompletionValidationResult(
        accepted=True,
        reason_code="evidence_accepted",
        detail=f"Evidence '{evidence.evidence_id}' documents completion of care gap '{gap_id}'.",
        evidence_kind=evidence.kind,
        evidence_id=evidence.evidence_id,
    )
