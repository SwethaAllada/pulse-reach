"""Deterministic clinical rule evaluation engine (`app.services.evaluation.engine`).

Implements Workstream C of `pulse-reach-backend-execution-plan.md`:
- Evaluates patient records against the 54 rules in `ParsedClinicalBundle` (or `clinical.*` rows).
- Enforces cross-cutting missing-data and authority guards (`GUARD-*`) before status logic.
- Preserves strict separation between:
  1. Programme eligibility (`IFHAS-PROG-ELIG-*`, `WCV-PROG-SCOPE`)
  2. Package / visit eligibility (`IFHAS-PKG-*`, `WCV-VISIT-*`)
  3. Care gaps (`no_documented_screening`, `interval_elapsed`, `visit_not_attended`,
     `partial_completion`, `referral_not_initiated`)
  4. History availability (`available`, `not_available` -> `unknown`, `partial` -> `requires_clinical_review`)
  5. Evaluation statuses (`eligible`, `not_eligible`, `due`, `upcoming`, `overdue`, `completed`,
     `unknown`, `insufficient_information`, `requires_clinical_review`)
- Never uses an LLM or statistical model to decide eligibility, due dates, or care gaps.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

from app.services.clinical_loader.parse import ParsedClinicalBundle, parse_clinical_bundle

ENGINE_VERSION = "0.1.0"


def _add_years(d: date, years: int) -> date:
    target_year = d.year + years
    last_day = calendar.monthrange(target_year, d.month)[1]
    return date(target_year, d.month, min(d.day, last_day))


def _add_months(d: date, months: int) -> date:
    total_months = (d.year * 12 + (d.month - 1)) + months
    target_year = total_months // 12
    target_month = (total_months % 12) + 1
    last_day = calendar.monthrange(target_year, target_month)[1]
    return date(target_year, target_month, min(d.day, last_day))


def _completed_years(dob: date, ref: date) -> int:
    return ref.year - dob.year - ((ref.month, ref.day) < (dob.month, dob.day))


def _completed_months(dob: date, ref: date) -> int:
    return (ref.year - dob.year) * 12 + (ref.month - dob.month) - (1 if ref.day < dob.day else 0)


@dataclass(frozen=True)
class ScreeningEventFact:
    screening_id: str
    rule_id: str
    rule_version: str
    completion_status: str  # 'complete' | 'partial' | 'not_performed'
    performed_date: date | None
    results_communicated_date: date | None = None
    journey_reported_date: date | None = None


@dataclass(frozen=True)
class VisitEventFact:
    visit_id: str
    rule_id: str
    rule_version: str
    attendance_status: str  # 'attended' | 'partial' | 'not_attended'
    performed_date: date | None


@dataclass(frozen=True)
class ComponentResultFact:
    component_result_id: str
    rule_id: str
    rule_version: str
    item_category: str
    item_code: str
    status: str  # 'completed' | 'not_performed' | 'refused' | 'not_applicable'
    recorded_at: datetime
    documented_in_record: bool = False
    signature_on_file: bool = False
    refused_by_guardian_id: str | None = None


@dataclass(frozen=True)
class AssessmentFact:
    assessment_id: str
    visit_id: str
    instrument: str  # 'M-CHAT-R' | 'IDAQ'
    tier_rule_id: str
    tier_rule_version: str
    recorded_at: datetime
    mchatr_score: int | None = None


@dataclass(frozen=True)
class ReferralFact:
    referral_id: str
    trigger_rule_id: str
    trigger_rule_version: str
    trigger_date: date
    initiated_date: date | None
    completed_date: date | None
    status: str  # 'pending' | 'initiated' | 'scheduled' | 'completed' | 'cancelled'


@dataclass(frozen=True)
class ConsentFact:
    consent_id: str
    consent_type: str  # 'screening_participation' | 'contact' | 'ai_assisted_prioritisation'
    state: str  # 'granted' | 'refused' | 'withdrawn'
    applies_to: str  # 'self' | 'child'
    scope_pathway: str | None
    scope_rule_id: str | None
    scope_rule_version: str | None
    recorded_at: datetime
    documented_in_record: bool
    signature_on_file: bool


@dataclass(frozen=True)
class PatientContext:
    patient_id: str
    date_of_birth: date | None
    sex: str | None  # 'female' | 'male' | 'unknown' | None
    thiqa_member: bool | None
    ever_smoked: bool | None
    history_by_pathway: dict[str, str] = field(default_factory=dict)
    ifhas_screenings: tuple[ScreeningEventFact, ...] = ()
    well_child_visits: tuple[VisitEventFact, ...] = ()
    component_results: tuple[ComponentResultFact, ...] = ()
    developmental_assessments: tuple[AssessmentFact, ...] = ()
    referrals: tuple[ReferralFact, ...] = ()
    consents: tuple[ConsentFact, ...] = ()


@dataclass(frozen=True)
class FiredReason:
    reason_code: str
    guard_id: str | None = None
    item_category: str | None = None
    item_code: str | None = None
    detail: str | None = None


@dataclass(frozen=True)
class RuleEvaluationResult:
    patient_id: str
    rule_id: str
    rule_version: str
    pathway: str
    rule_type: str | None
    evaluation_status: str
    reason_code: str | None
    reasons: tuple[FiredReason, ...]
    evaluated_at: datetime
    look_ahead_days: int | None
    last_completed_date: date | None
    next_due_date: date | None
    input_snapshot: dict[str, Any]
    engine_version: str = ENGINE_VERSION


@dataclass(frozen=True)
class CareGapFact:
    patient_id: str
    pathway: str
    rule_id: str
    rule_version: str
    gap_type: str
    status: str  # 'open' | 'closed_completed' | 'closed_refused' | 'superseded'
    opened_date: date
    subject_ifhas_screening_id: str | None = None
    subject_well_child_visit_id: str | None = None
    subject_referral_id: str | None = None
    closed_date: date | None = None
    closed_by_ifhas_screening_id: str | None = None
    closed_by_well_child_visit_id: str | None = None
    closed_by_component_result_id: str | None = None
    closed_by_consent_id: str | None = None


@dataclass(frozen=True)
class PatientEvaluationSummary:
    patient_id: str
    reference_date: date
    look_ahead_days: int | None
    evaluations: tuple[RuleEvaluationResult, ...]
    care_gaps: tuple[CareGapFact, ...]


def _evaluate_non_pending_referral(
    latest_ref: ReferralFact,
    result_fn: Any,
) -> RuleEvaluationResult:
    """Map non-pending referral statuses without ever falsely marking incomplete referrals completed."""
    if latest_ref.status == "completed":
        if latest_ref.completed_date is None:
            r = FiredReason(
                reason_code="missing_completion_evidence",
                guard_id="GUARD-CONFLICTING-RECORDS",
                detail="Referral is marked completed without a documented completion date.",
            )
            return result_fn("requires_clinical_review", r.reason_code, (r,))
        return result_fn("completed", last_completed_date=latest_ref.completed_date)
    if latest_ref.status == "cancelled":
        r = FiredReason(
            reason_code="referral_cancelled",
            detail="Referral was cancelled; requires clinical review.",
        )
        return result_fn("requires_clinical_review", r.reason_code, (r,))
    if latest_ref.status in ("initiated", "scheduled"):
        return result_fn(
            "upcoming",
            next_due_date=latest_ref.initiated_date or latest_ref.trigger_date,
        )
    r = FiredReason(
        reason_code="referral_status_unresolved",
        detail=f"Referral status '{latest_ref.status}' requires clinical review.",
    )
    return result_fn("requires_clinical_review", r.reason_code, (r,))


class EvaluationEngine:
    """Deterministic clinical evaluation engine backed by `ParsedClinicalBundle`."""

    def __init__(self, bundle: ParsedClinicalBundle | None = None) -> None:
        self.bundle = bundle if bundle is not None else parse_clinical_bundle()
        self._rules_by_id: dict[str, dict[str, Any]] = {
            r["rule_id"]: r for r in self.bundle.rules
        }
        self._conditions_by_rule: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for cond in self.bundle.conditions:
            key = (cond["rule_id"], cond["rule_version"])
            self._conditions_by_rule.setdefault(key, []).append(cond)
        self._items_by_rule: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for item in self.bundle.items:
            key = (item["rule_id"], item["rule_version"])
            self._items_by_rule.setdefault(key, []).append(item)

        ifhas_min_rule = self._rules_by_id.get("IFHAS-PROG-ELIG-MIN-AGE", {})
        ifhas_min_spec = (ifhas_min_rule.get("spec") or {}).get("min_years")
        ifhas_pkg_mins = [
            int(r["age_min_years"])
            for r in self.bundle.rules
            if r.get("pathway") == "ifhas" and r.get("age_min_years") is not None
        ]
        self._ifhas_min_age_years: int = (
            int(ifhas_min_spec)
            if ifhas_min_spec is not None
            else (min(ifhas_pkg_mins) if ifhas_pkg_mins else 18)
        )
        ifhas_pkg_maxs = [
            int(r["age_max_years"])
            for r in self.bundle.rules
            if r.get("pathway") == "ifhas" and r.get("age_max_years") is not None
        ]
        self._ifhas_max_verified_age_years: int = max(ifhas_pkg_maxs) if ifhas_pkg_maxs else 75

        wcv_months = [
            int(r["recommended_age_months"])
            for r in self.bundle.rules
            if r.get("pathway") == "well_child" and r.get("recommended_age_months") is not None
        ]
        self._wcv_min_age_months: int = min(wcv_months) if wcv_months else 1
        self._wcv_max_age_months: int = max(wcv_months) if wcv_months else 72

    def evaluate_patient(
        self,
        patient: PatientContext,
        *,
        reference_date: date,
        look_ahead_days: int | None = 30,
        evaluated_at: datetime | None = None,
    ) -> PatientEvaluationSummary:
        eval_ts = evaluated_at or datetime(
            reference_date.year, reference_date.month, reference_date.day, 9, 0, tzinfo=timezone.utc
        )
        age_years = (
            _completed_years(patient.date_of_birth, reference_date)
            if patient.date_of_birth is not None
            else None
        )
        age_months = (
            _completed_months(patient.date_of_birth, reference_date)
            if patient.date_of_birth is not None
            else None
        )

        evaluations: list[RuleEvaluationResult] = []
        care_gaps: list[CareGapFact] = []

        for rule in self.bundle.rules:
            ev, gaps = self._evaluate_single_rule(
                rule=rule,
                patient=patient,
                reference_date=reference_date,
                look_ahead_days=look_ahead_days,
                eval_ts=eval_ts,
                age_years=age_years,
                age_months=age_months,
            )
            evaluations.append(ev)
            care_gaps.extend(gaps)

        return PatientEvaluationSummary(
            patient_id=patient.patient_id,
            reference_date=reference_date,
            look_ahead_days=look_ahead_days,
            evaluations=tuple(evaluations),
            care_gaps=tuple(care_gaps),
        )

    def _find_refusal_evidence(
        self,
        patient: PatientContext,
        pathway: str,
        rule_id: str,
    ) -> tuple[str | None, str | None, date | None]:
        """Return `(closed_by_consent_id, closed_by_component_result_id, closed_date)` if a valid refusal exists."""
        matching_consents = [
            c
            for c in patient.consents
            if c.consent_type == "screening_participation"
            and c.state == "refused"
            and c.documented_in_record is True
            and c.signature_on_file is True
            and (pathway != "well_child" or c.applies_to == "child_by_guardian")
            and (c.scope_pathway != "well_child" or c.applies_to == "child_by_guardian")
            and (
                c.scope_rule_id == rule_id
                or (c.scope_rule_id is None and c.scope_pathway == pathway)
            )
        ]
        if matching_consents:
            latest = max(matching_consents, key=lambda c: c.recorded_at)
            return (latest.consent_id, None, latest.recorded_at.date())

        matching_crs = [
            cr
            for cr in patient.component_results
            if cr.rule_id == rule_id
            and cr.status == "refused"
            and cr.documented_in_record is True
            and cr.signature_on_file is True
            and (pathway != "well_child" or cr.refused_by_guardian_id is not None)
        ]
        if matching_crs:
            latest_cr = max(matching_crs, key=lambda cr: cr.recorded_at)
            return (None, latest_cr.component_result_id, latest_cr.recorded_at.date())

        return (None, None, None)

    def _make_care_gap(
        self,
        *,
        patient: PatientContext,
        pathway: str,
        rule_id: str,
        rule_version: str,
        gap_type: str,
        opened_date: date,
        subject_ifhas_screening_id: str | None = None,
        subject_well_child_visit_id: str | None = None,
        subject_referral_id: str | None = None,
    ) -> CareGapFact:
        if gap_type != "referral_not_initiated":
            consent_id, cr_id, closed_date = self._find_refusal_evidence(patient, pathway, rule_id)
            if consent_id is not None or cr_id is not None:
                return CareGapFact(
                    patient_id=patient.patient_id,
                    pathway=pathway,
                    rule_id=rule_id,
                    rule_version=rule_version,
                    gap_type=gap_type,
                    status="closed_refused",
                    opened_date=opened_date,
                    subject_ifhas_screening_id=subject_ifhas_screening_id,
                    subject_well_child_visit_id=subject_well_child_visit_id,
                    subject_referral_id=subject_referral_id,
                    closed_date=closed_date,
                    closed_by_consent_id=consent_id,
                    closed_by_component_result_id=cr_id,
                )
        return CareGapFact(
            patient_id=patient.patient_id,
            pathway=pathway,
            rule_id=rule_id,
            rule_version=rule_version,
            gap_type=gap_type,
            status="open",
            opened_date=opened_date,
            subject_ifhas_screening_id=subject_ifhas_screening_id,
            subject_well_child_visit_id=subject_well_child_visit_id,
            subject_referral_id=subject_referral_id,
        )

    def _evaluate_single_rule(
        self,
        *,
        rule: dict[str, Any],
        patient: PatientContext,
        reference_date: date,
        look_ahead_days: int | None,
        eval_ts: datetime,
        age_years: int | None,
        age_months: int | None,
    ) -> tuple[RuleEvaluationResult, list[CareGapFact]]:
        rid = rule["rule_id"]
        rver = rule["rule_version"]
        pathway = rule["pathway"]
        rtype = rule.get("rule_type")
        vstatus = rule["verification_status"]
        req_review = rule["requires_clinical_review"]
        history_state = patient.history_by_pathway.get(pathway, "not_available")

        snapshot: dict[str, Any] = {
            "reference_date": reference_date.isoformat(),
            "age_years": age_years,
            "age_months": age_months,
            "sex": patient.sex,
            "thiqa_member": patient.thiqa_member,
            "ever_smoked": patient.ever_smoked,
            "history_state": history_state,
        }

        def _result(
            status: str,
            reason_code: str | None = None,
            reasons: tuple[FiredReason, ...] = (),
            last_completed_date: date | None = None,
            next_due_date: date | None = None,
        ) -> RuleEvaluationResult:
            return RuleEvaluationResult(
                patient_id=patient.patient_id,
                rule_id=rid,
                rule_version=rver,
                pathway=pathway,
                rule_type=rtype,
                evaluation_status=status,
                reason_code=reason_code,
                reasons=reasons,
                evaluated_at=eval_ts,
                look_ahead_days=look_ahead_days,
                last_completed_date=last_completed_date,
                next_due_date=next_due_date,
                input_snapshot=snapshot,
            )

        # 1. Cross-cutting authority guards take precedence over all status logic
        if vstatus != "verified":
            rc = "rule_unresolved" if vstatus == "unresolved" else "rule_reported_not_verified"
            reason = FiredReason(
                reason_code=rc,
                guard_id="GUARD-RULE-NOT-VERIFIED",
                detail=f"Rule {rid} has verification_status='{vstatus}' and cannot drive authoritative decisions.",
            )
            return _result("requires_clinical_review", rc, (reason,)), []

        if req_review:
            rc = "rule_requires_clinical_review"
            reason = FiredReason(
                reason_code=rc,
                guard_id="GUARD-RULE-REVIEW-FLAG",
                detail=f"Rule {rid} is flagged requires_clinical_review=True.",
            )
            return _result("requires_clinical_review", rc, (reason,)), []

        # Collect any item-level unresolved guards attached to this rule
        rule_items = self._items_by_rule.get((rid, rver), [])
        item_reasons: list[FiredReason] = [
            FiredReason(
                reason_code="rule_item_unresolved",
                guard_id="GUARD-ITEM-UNRESOLVED",
                item_category=it["category"],
                item_code=it["code"],
                detail=f"Assessment item '{it['code']}' has verification_status='{it['verification_status']}'.",
            )
            for it in rule_items
            if not it["status_is_verified"]
        ]

        # 2. Programme eligibility rules (`IFHAS-PROG-ELIG-*`)
        if rtype == "programme_eligibility":
            gate = rule.get("gate_attribute")
            if gate == "thiqa_member":
                if not isinstance(patient.thiqa_member, bool):
                    r = FiredReason(
                        reason_code="missing_required_attribute",
                        guard_id="GUARD-MISSING-ATTRIBUTE",
                        detail="Required attribute 'thiqa_member' is missing or not a boolean.",
                    )
                    return _result("insufficient_information", r.reason_code, (r,)), []
                return (
                    _result("eligible" if patient.thiqa_member is True else "not_eligible"),
                    [],
                )
            if gate == "age_years":
                if age_years is None:
                    r = FiredReason(
                        reason_code="missing_date_of_birth",
                        guard_id="GUARD-MISSING-DOB",
                        detail="Date of birth is missing.",
                    )
                    return _result("insufficient_information", r.reason_code, (r,)), []
                spec = rule.get("spec") or {}
                min_y = (
                    int(spec["min_years"])
                    if spec.get("min_years") is not None
                    else self._ifhas_min_age_years
                )
                max_y = (
                    int(spec["max_years"])
                    if spec.get("max_years") is not None
                    else self._ifhas_max_verified_age_years
                )
                if age_years < min_y:
                    return _result("not_eligible"), []
                if age_years > max_y:
                    r = FiredReason(
                        reason_code="rule_unresolved",
                        guard_id="GUARD-RULE-NOT-VERIFIED",
                        detail=(
                            f"Age > {max_y} hits unresolved IFHAS upper age boundary "
                            "(OQ-IFHAS-AGE-CEILING)."
                        ),
                    )
                    return _result("requires_clinical_review", r.reason_code, (r,)), []
                return _result("eligible"), []
            if gate == "sex":
                if patient.sex not in ("female", "male"):
                    r = FiredReason(
                        reason_code="missing_sex",
                        guard_id="GUARD-MISSING-ATTRIBUTE",
                        detail="Sex attribute is missing or unknown.",
                    )
                    return _result("insufficient_information", r.reason_code, (r,)), []
                return _result("eligible"), []

        # 3. IFHAS screening packages (`screening_package`)
        if rtype == "screening_package":
            if age_years is None:
                r = FiredReason(
                    reason_code="missing_date_of_birth",
                    guard_id="GUARD-MISSING-DOB",
                    detail="Date of birth is missing.",
                )
                return _result("insufficient_information", r.reason_code, (r,)), []
            if patient.sex not in ("female", "male"):
                r = FiredReason(
                    reason_code="missing_sex",
                    guard_id="GUARD-MISSING-ATTRIBUTE",
                    detail="Sex attribute is missing or unknown.",
                )
                return _result("insufficient_information", r.reason_code, (r,)), []

            allowed_sexes = rule.get("sexes") or []
            if patient.sex not in allowed_sexes:
                return _result("not_eligible"), []

            min_age = rule.get("age_min_years")
            max_age = rule.get("age_max_years")
            if (min_age is not None and age_years < min_age) or (
                max_age is not None and age_years > max_age
            ):
                return _result("not_eligible"), []

            if patient.thiqa_member is None:
                r = FiredReason(
                    reason_code="missing_required_attribute",
                    guard_id="GUARD-MISSING-ATTRIBUTE",
                    detail="Required programme attribute 'thiqa_member' is missing.",
                )
                return _result("insufficient_information", r.reason_code, (r,)), []
            if patient.thiqa_member is False:
                return _result("not_eligible"), []

            # Machine-evaluable rule conditions (e.g., smoking_history.ever_smoked on AAA)
            for cond in self._conditions_by_rule.get((rid, rver), []):
                if cond["machine_evaluable"]:
                    attr = cond["attribute"]
                    req_val = cond["required_value"]
                    if attr == "smoking_history.ever_smoked":
                        if patient.ever_smoked is None:
                            r = FiredReason(
                                reason_code="missing_required_attribute",
                                guard_id="GUARD-MISSING-ATTRIBUTE",
                                detail="Required attribute 'smoking_history.ever_smoked' is missing.",
                            )
                            return _result("insufficient_information", r.reason_code, (r,)), []
                        if patient.ever_smoked != req_val:
                            return _result("not_eligible"), []

            # Eligibility established; check screening history availability
            if history_state == "not_available":
                r = FiredReason(
                    reason_code="missing_screening_history",
                    guard_id="GUARD-MISSING-HISTORY",
                    detail="IFHAS screening history is not available; completion cannot be determined.",
                )
                return _result("unknown", r.reason_code, (r,)), []
            if history_state == "partial":
                r = FiredReason(
                    reason_code="conflicting_records",
                    guard_id="GUARD-CONFLICTING-RECORDS",
                    detail="IFHAS screening history is partial/incomplete; routed to clinical review.",
                )
                return _result("requires_clinical_review", r.reason_code, (r,)), []

            # History is available: inspect documented IFHAS screenings for this rule
            rule_screenings = [s for s in patient.ifhas_screenings if s.rule_id == rid]
            if len({s.completion_status for s in rule_screenings}) > 1:
                r = FiredReason(
                    reason_code="conflicting_records",
                    guard_id="GUARD-CONFLICTING-RECORDS",
                    detail=f"Conflicting screening completion records found for rule {rid}.",
                )
                return _result("requires_clinical_review", r.reason_code, (r,)), []

            completed_screenings = [
                s
                for s in rule_screenings
                if s.completion_status == "complete" and s.performed_date is not None
            ]
            if completed_screenings:
                latest = max(completed_screenings, key=lambda s: s.performed_date)  # type: ignore[arg-type]
                last_date = latest.performed_date
                assert last_date is not None
                if rule.get("frequency_type") == "once_per_lifetime":
                    return (
                        _result("completed", last_completed_date=last_date, next_due_date=None),
                        [],
                    )
                interval_years = int(rule.get("interval_value") or 1)
                next_due = _add_years(last_date, interval_years)
                if reference_date < next_due:
                    if (
                        look_ahead_days is not None
                        and (next_due - reference_date).days <= look_ahead_days
                    ):
                        return (
                            _result(
                                "upcoming",
                                last_completed_date=last_date,
                                next_due_date=next_due,
                            ),
                            [],
                        )
                    return (
                        _result(
                            "completed",
                            last_completed_date=last_date,
                            next_due_date=next_due,
                        ),
                        [],
                    )
                gap = self._make_care_gap(
                    patient=patient,
                    pathway=pathway,
                    rule_id=rid,
                    rule_version=rver,
                    gap_type="interval_elapsed",
                    opened_date=next_due,
                )
                return (
                    _result("due", last_completed_date=last_date, next_due_date=next_due),
                    [gap],
                )

            partial_screenings = [
                s for s in rule_screenings if s.completion_status == "partial"
            ]
            if partial_screenings:
                latest_p = partial_screenings[-1]
                gap = self._make_care_gap(
                    patient=patient,
                    pathway=pathway,
                    rule_id=rid,
                    rule_version=rver,
                    gap_type="partial_completion",
                    opened_date=latest_p.performed_date or reference_date,
                    subject_ifhas_screening_id=latest_p.screening_id,
                )
                return _result("due", next_due_date=reference_date), [gap]

            gap = self._make_care_gap(
                patient=patient,
                pathway=pathway,
                rule_id=rid,
                rule_version=rver,
                gap_type="no_documented_screening",
                opened_date=reference_date,
            )
            return _result("due", next_due_date=reference_date), [gap]

        # 4. Well-Child programme scope (`WCV-PROG-SCOPE`)
        if rtype == "programme_scope":
            if age_months is None:
                r = FiredReason(
                    reason_code="missing_date_of_birth",
                    guard_id="GUARD-MISSING-DOB",
                    detail="Date of birth is missing.",
                )
                return _result("insufficient_information", r.reason_code, (r,)), []
            if self._wcv_min_age_months <= age_months <= self._wcv_max_age_months:
                return _result("eligible"), []
            return _result("not_eligible"), []

        # 5. Well-Child visit schedule (`visit_schedule`, 14 visits)
        if rtype == "visit_schedule":
            if age_months is None or patient.date_of_birth is None:
                r = FiredReason(
                    reason_code="missing_date_of_birth",
                    guard_id="GUARD-MISSING-DOB",
                    detail="Date of birth is missing.",
                )
                return (
                    _result("insufficient_information", r.reason_code, (r, *item_reasons)),
                    [],
                )
            if age_months < self._wcv_min_age_months or age_months > self._wcv_max_age_months:
                return _result("not_eligible", reasons=tuple(item_reasons)), []

            if history_state == "not_available":
                r = FiredReason(
                    reason_code="missing_screening_history",
                    guard_id="GUARD-MISSING-HISTORY",
                    detail="Well-Child visit history is not available; completion cannot be determined.",
                )
                return _result("unknown", r.reason_code, (r, *item_reasons)), []
            if history_state == "partial":
                r = FiredReason(
                    reason_code="conflicting_records",
                    guard_id="GUARD-CONFLICTING-RECORDS",
                    detail="Well-Child visit history is partial/incomplete; routed to clinical review.",
                )
                return (
                    _result("requires_clinical_review", r.reason_code, (r, *item_reasons)),
                    [],
                )

            rec_months = int(rule.get("recommended_age_months") or 1)
            rec_date = _add_months(patient.date_of_birth, rec_months)
            rule_visits = [v for v in patient.well_child_visits if v.rule_id == rid]
            if len({v.attendance_status for v in rule_visits}) > 1:
                r = FiredReason(
                    reason_code="conflicting_records",
                    guard_id="GUARD-CONFLICTING-RECORDS",
                    detail=f"Conflicting visit attendance records found for rule {rid}.",
                )
                return (
                    _result("requires_clinical_review", r.reason_code, (r, *item_reasons)),
                    [],
                )

            attended = [v for v in rule_visits if v.attendance_status == "attended"]
            if attended:
                latest_v = attended[-1]
                return (
                    _result(
                        "completed",
                        reason_code=item_reasons[0].reason_code if item_reasons else None,
                        reasons=tuple(item_reasons),
                        last_completed_date=latest_v.performed_date,
                    ),
                    [],
                )

            not_attended = [v for v in rule_visits if v.attendance_status == "not_attended"]
            if not_attended:
                v = not_attended[-1]
                gap = self._make_care_gap(
                    patient=patient,
                    pathway=pathway,
                    rule_id=rid,
                    rule_version=rver,
                    gap_type="visit_not_attended",
                    opened_date=rec_date if rec_date <= reference_date else reference_date,
                    subject_well_child_visit_id=v.visit_id,
                )
                return (
                    _result(
                        "due",
                        reason_code=item_reasons[0].reason_code if item_reasons else None,
                        reasons=tuple(item_reasons),
                        next_due_date=rec_date,
                    ),
                    [gap],
                )

            partial_v = [v for v in rule_visits if v.attendance_status == "partial"]
            if partial_v:
                v = partial_v[-1]
                gap = self._make_care_gap(
                    patient=patient,
                    pathway=pathway,
                    rule_id=rid,
                    rule_version=rver,
                    gap_type="partial_completion",
                    opened_date=v.performed_date or reference_date,
                    subject_well_child_visit_id=v.visit_id,
                )
                return (
                    _result(
                        "due",
                        reason_code=item_reasons[0].reason_code if item_reasons else None,
                        reasons=tuple(item_reasons),
                        next_due_date=rec_date,
                    ),
                    [gap],
                )

            if age_months == rec_months:
                gap = self._make_care_gap(
                    patient=patient,
                    pathway=pathway,
                    rule_id=rid,
                    rule_version=rver,
                    gap_type="no_documented_screening",
                    opened_date=reference_date,
                )
                return (
                    _result(
                        "due",
                        reason_code=item_reasons[0].reason_code if item_reasons else None,
                        reasons=tuple(item_reasons),
                        next_due_date=rec_date,
                    ),
                    [gap],
                )

            if age_months < rec_months:
                if (
                    look_ahead_days is not None
                    and 0 <= (rec_date - reference_date).days <= look_ahead_days
                ):
                    return (
                        _result(
                            "upcoming",
                            reason_code=item_reasons[0].reason_code if item_reasons else None,
                            reasons=tuple(item_reasons),
                            next_due_date=rec_date,
                        ),
                        [],
                    )
                return (
                    _result(
                        "not_eligible",
                        reason_code=item_reasons[0].reason_code if item_reasons else None,
                        reasons=tuple(item_reasons),
                        next_due_date=rec_date,
                    ),
                    [],
                )

            # Past recommended visit age with no documented visit -> requires_clinical_review (never overdue)
            r = FiredReason(
                reason_code="rule_unresolved",
                guard_id="GUARD-RULE-NOT-VERIFIED",
                detail="Past recommended visit age without a verified overdue window (OQ-WCV-DUE-WINDOW).",
            )
            return (
                _result("requires_clinical_review", r.reason_code, (*item_reasons, r)),
                [],
            )

        # 6. Developmental screening tiers (`WCV-MCHATR-*`, `WCV-IDAQ-REFERRAL`)
        if rtype == "developmental_screening_tier":
            if age_months is None:
                r = FiredReason(
                    reason_code="missing_date_of_birth",
                    guard_id="GUARD-MISSING-DOB",
                    detail="Date of birth is missing.",
                )
                return _result("insufficient_information", r.reason_code, (r,)), []
            if age_months < self._wcv_min_age_months or age_months > self._wcv_max_age_months:
                return _result("not_eligible"), []

            matching_assessments = [
                a for a in patient.developmental_assessments if a.tier_rule_id == rid
            ]
            matching_referrals = [
                ref for ref in patient.referrals if ref.trigger_rule_id == rid
            ]
            pending_refs = [ref for ref in matching_referrals if ref.status == "pending"]
            if pending_refs:
                ref = max(pending_refs, key=lambda r: (r.trigger_date, r.referral_id))
                gap = self._make_care_gap(
                    patient=patient,
                    pathway=pathway,
                    rule_id=rid,
                    rule_version=rver,
                    gap_type="referral_not_initiated",
                    opened_date=ref.trigger_date,
                    subject_referral_id=ref.referral_id,
                )
                return _result("due", next_due_date=ref.trigger_date), [gap]

            if matching_assessments:
                latest_a = max(matching_assessments, key=lambda a: a.recorded_at)
                return (
                    _result("completed", last_completed_date=latest_a.recorded_at.date()),
                    [],
                )

            if matching_referrals:
                latest_ref = max(matching_referrals, key=lambda r: (r.trigger_date, r.referral_id))
                return _evaluate_non_pending_referral(latest_ref, _result), []

            target_months = (rule.get("spec") or {}).get("administered_at_months") or []
            if age_months in target_months:
                if history_state == "not_available":
                    r = FiredReason(
                        reason_code="missing_screening_history",
                        guard_id="GUARD-MISSING-HISTORY",
                        detail="Well-Child screening history is not available.",
                    )
                    return _result("unknown", r.reason_code, (r,)), []
                if history_state == "partial":
                    r = FiredReason(
                        reason_code="conflicting_records",
                        guard_id="GUARD-CONFLICTING-RECORDS",
                        detail="Well-Child screening history is partial.",
                    )
                    return _result("requires_clinical_review", r.reason_code, (r,)), []
                return _result("eligible"), []
            return _result("not_eligible"), []

        # 7. Workflow timing, follow-up windows, and policies
        if rid in ("IFHAS-WF-RESULTS-COMMUNICATION-10D", "IFHAS-WF-JOURNEY-COMPLETION-15D"):
            completed_ifhas = [
                s
                for s in patient.ifhas_screenings
                if s.completion_status == "complete" and s.performed_date is not None
            ]
            if completed_ifhas:
                latest_s = max(completed_ifhas, key=lambda s: s.performed_date)  # type: ignore[arg-type]
                perf_date = latest_s.performed_date
                assert perf_date is not None
                window_days = 10 if rid == "IFHAS-WF-RESULTS-COMMUNICATION-10D" else 15
                milestone_date = (
                    latest_s.results_communicated_date
                    if rid == "IFHAS-WF-RESULTS-COMMUNICATION-10D"
                    else latest_s.journey_reported_date
                )
                due_date = perf_date + timedelta(days=window_days)
                if milestone_date is not None and (milestone_date - perf_date).days <= window_days:
                    return _result("completed", last_completed_date=milestone_date), []
                if (reference_date - perf_date).days > window_days or (
                    milestone_date is not None and (milestone_date - perf_date).days > window_days
                ):
                    gap = self._make_care_gap(
                        patient=patient,
                        pathway=pathway,
                        rule_id=rid,
                        rule_version=rver,
                        gap_type="partial_completion",
                        opened_date=due_date,
                        subject_ifhas_screening_id=latest_s.screening_id,
                    )
                    return _result("due", next_due_date=due_date), [gap]
                return _result("upcoming", next_due_date=due_date), []

        matching_referrals = [
            ref for ref in patient.referrals if ref.trigger_rule_id == rid
        ]
        if matching_referrals:
            pending_refs = [ref for ref in matching_referrals if ref.status == "pending"]
            if pending_refs:
                ref = max(pending_refs, key=lambda r: (r.trigger_date, r.referral_id))
                t_val = rule.get("timing_value")
                t_unit = rule.get("timing_unit")
                deadline_days = 7
                if t_val is not None:
                    if t_unit == "working_days":
                        deadline_days = int(t_val) * 7 // 5
                    elif t_unit == "weeks":
                        deadline_days = int(t_val) * 7
                    else:
                        deadline_days = int(t_val)
                if (reference_date - ref.trigger_date).days >= deadline_days:
                    gap = self._make_care_gap(
                        patient=patient,
                        pathway=pathway,
                        rule_id=rid,
                        rule_version=rver,
                        gap_type="referral_not_initiated",
                        opened_date=ref.trigger_date,
                        subject_referral_id=ref.referral_id,
                    )
                    return _result("due", next_due_date=ref.trigger_date), [gap]
                return _result("upcoming", next_due_date=ref.trigger_date), []
            latest_ref = max(matching_referrals, key=lambda r: (r.trigger_date, r.referral_id))
            return _evaluate_non_pending_referral(latest_ref, _result), []

        if age_years is None or age_months is None:
            r = FiredReason(
                reason_code="missing_date_of_birth",
                guard_id="GUARD-MISSING-DOB",
                detail="Date of birth is missing.",
            )
            return _result("insufficient_information", r.reason_code, (r,)), []

        if pathway == "ifhas":
            if not isinstance(patient.thiqa_member, bool):
                r = FiredReason(
                    reason_code="missing_required_attribute",
                    guard_id="GUARD-MISSING-ATTRIBUTE",
                    detail="Required attribute 'thiqa_member' is missing or not a boolean.",
                )
                return _result("insufficient_information", r.reason_code, (r,)), []
            if patient.thiqa_member is False or age_years < self._ifhas_min_age_years:
                return _result("not_eligible"), []
            if age_years > self._ifhas_max_verified_age_years:
                r = FiredReason(
                    reason_code="rule_unresolved",
                    guard_id="GUARD-RULE-NOT-VERIFIED",
                    detail=(
                        f"Age > {self._ifhas_max_verified_age_years} hits unresolved IFHAS upper "
                        "age boundary (OQ-IFHAS-AGE-CEILING)."
                    ),
                )
                return _result("requires_clinical_review", r.reason_code, (r,)), []
            return _result("eligible"), []

        if self._wcv_min_age_months <= age_months <= self._wcv_max_age_months:
            return _result("eligible"), []
        return _result("not_eligible"), []
