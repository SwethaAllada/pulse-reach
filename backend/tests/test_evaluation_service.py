"""Table-driven tests for the deterministic clinical rule evaluation service (`app.services.evaluation`).

Verifies every clinical and safety boundary in Workstream C (`pulse-reach-backend-execution-plan.md`):
- Programme eligibility, preventive-care package/visit eligibility, care gaps, history availability,
  and evaluation statuses remain distinct.
- Missing attributes (`date_of_birth`, `sex`, `thiqa_member`, `ever_smoked`) -> `insufficient_information`.
- Missing screening history (`not_available`) -> `unknown`, never `due` or `overdue`, and never a care gap.
- Partial history (`partial`) -> `requires_clinical_review`, never guessing `due`.
- Unresolved or review-flagged rules -> `requires_clinical_review`, never authoritative `eligible`/`due`.
- Well-Child rules never produce `overdue` while `OQ-WCV-DUE-WINDOW` is unresolved.
- Documented, signed refusal closes a care gap as `closed_refused` with evidence, distinct from `open` or `closed_completed`.
- Uninitiated referrals past their deadline yield `referral_not_initiated` care gaps.
"""

from datetime import date, datetime, timezone

import pytest

from app.services.clinical_loader.parse import parse_clinical_bundle
from app.services.evaluation import (
    ComponentResultFact,
    ConsentFact,
    EvaluationEngine,
    PatientContext,
    ReferralFact,
    ScreeningEventFact,
    VisitEventFact,
)


@pytest.fixture(scope="module")
def bundle():
    return parse_clinical_bundle()


@pytest.fixture(scope="module")
def engine(bundle):
    return EvaluationEngine(bundle)


REF_DATE = date(2026, 11, 16)


def test_adult_eligible_and_due_when_history_available_and_no_prior_screening(engine):
    # 45yo female, Thiqa member, IFHAS history available, no prior screenings
    patient = PatientContext(
        patient_id="SYNTH-PAT-000001",
        date_of_birth=date(1981, 5, 10),
        sex="female",
        thiqa_member=True,
        ever_smoked=False,
        history_by_pathway={"ifhas": "available"},
    )
    res = engine.evaluate_patient(patient, reference_date=REF_DATE)
    by_rule = {e.rule_id: e for e in res.evaluations}

    # Programme gate rules
    assert by_rule["IFHAS-PROG-ELIG-THIQA"].evaluation_status == "eligible"
    assert by_rule["IFHAS-PROG-ELIG-MIN-AGE"].evaluation_status == "eligible"

    # Applicable packages for 45yo female -> due
    for pkg in (
        "IFHAS-PKG-MAJOR-40-64",
        "IFHAS-PKG-VISION-40-75",
        "IFHAS-PKG-ORAL-18-75",
        "IFHAS-PKG-MAMMOGRAPHY-40-75",
        "IFHAS-PKG-FIT-40-75",
        "IFHAS-PKG-COLONOSCOPY-40-75",
    ):
        assert by_rule[pkg].evaluation_status == "due", pkg

    # Care gaps created for due packages with available history
    gap_rules = {g.rule_id: g for g in res.care_gaps}
    assert gap_rules["IFHAS-PKG-MAMMOGRAPHY-40-75"].gap_type == "no_documented_screening"
    assert gap_rules["IFHAS-PKG-MAMMOGRAPHY-40-75"].status == "open"


def test_adult_completed_and_interval_elapsed_and_upcoming(engine):
    # 45yo male, Thiqa member, IFHAS history available
    # - Major package completed 1 year ago (3-year interval) -> completed
    # - Vision package completed 2 years ago (1-year interval) -> due + interval_elapsed gap
    # - Oral package completed 350 days ago (1-year interval, due in 15 days <= 30d look-ahead) -> upcoming
    patient = PatientContext(
        patient_id="SYNTH-PAT-000002",
        date_of_birth=date(1981, 5, 10),
        sex="male",
        thiqa_member=True,
        ever_smoked=False,
        history_by_pathway={"ifhas": "available"},
        ifhas_screenings=(
            ScreeningEventFact(
                screening_id="SYNTH-SCR-000001",
                rule_id="IFHAS-PKG-MAJOR-40-64",
                rule_version="1.0.0",
                completion_status="complete",
                performed_date=date(2025, 11, 16),
            ),
            ScreeningEventFact(
                screening_id="SYNTH-SCR-000002",
                rule_id="IFHAS-PKG-VISION-40-75",
                rule_version="1.0.0",
                completion_status="complete",
                performed_date=date(2024, 10, 1),
            ),
            ScreeningEventFact(
                screening_id="SYNTH-SCR-000003",
                rule_id="IFHAS-PKG-ORAL-18-75",
                rule_version="1.0.0",
                completion_status="complete",
                performed_date=date(2025, 12, 1),
            ),
        ),
    )
    res = engine.evaluate_patient(patient, reference_date=REF_DATE, look_ahead_days=30)
    by_rule = {e.rule_id: e for e in res.evaluations}
    gaps_by_rule = {g.rule_id: g for g in res.care_gaps}

    assert by_rule["IFHAS-PKG-MAJOR-40-64"].evaluation_status == "completed"
    assert by_rule["IFHAS-PKG-MAJOR-40-64"].next_due_date == date(2028, 11, 16)
    assert "IFHAS-PKG-MAJOR-40-64" not in gaps_by_rule

    assert by_rule["IFHAS-PKG-VISION-40-75"].evaluation_status == "due"
    assert gaps_by_rule["IFHAS-PKG-VISION-40-75"].gap_type == "interval_elapsed"

    assert by_rule["IFHAS-PKG-ORAL-18-75"].evaluation_status == "upcoming"
    assert by_rule["IFHAS-PKG-ORAL-18-75"].next_due_date == date(2026, 12, 1)
    assert "IFHAS-PKG-ORAL-18-75" not in gaps_by_rule


def test_missing_history_yields_unknown_and_never_creates_care_gap(engine):
    patient = PatientContext(
        patient_id="SYNTH-PAT-000003",
        date_of_birth=date(1976, 3, 15),
        sex="female",
        thiqa_member=True,
        ever_smoked=False,
        history_by_pathway={"ifhas": "not_available"},
    )
    res = engine.evaluate_patient(patient, reference_date=REF_DATE)
    by_rule = {e.rule_id: e for e in res.evaluations}

    mammo = by_rule["IFHAS-PKG-MAMMOGRAPHY-40-75"]
    assert mammo.evaluation_status == "unknown"
    assert mammo.reason_code == "missing_screening_history"
    assert any(r.guard_id == "GUARD-MISSING-HISTORY" for r in mammo.reasons)
    # Missing history must NEVER create a care gap
    assert res.care_gaps == ()


def test_partial_history_yields_requires_clinical_review_never_due(engine):
    patient = PatientContext(
        patient_id="SYNTH-PAT-000030",
        date_of_birth=date(1976, 3, 15),
        sex="female",
        thiqa_member=True,
        ever_smoked=False,
        history_by_pathway={"ifhas": "partial"},
    )
    res = engine.evaluate_patient(patient, reference_date=REF_DATE)
    by_rule = {e.rule_id: e for e in res.evaluations}
    assert by_rule["IFHAS-PKG-MAMMOGRAPHY-40-75"].evaluation_status == "requires_clinical_review"
    assert res.care_gaps == ()


@pytest.mark.parametrize(
    "dob,sex,thiqa,smoked,target_rule,expected_reason,expected_guard",
    [
        (
            None,
            "female",
            True,
            False,
            "IFHAS-PKG-MAMMOGRAPHY-40-75",
            "missing_date_of_birth",
            "GUARD-MISSING-DOB",
        ),
        (
            date(1976, 1, 1),
            None,
            True,
            False,
            "IFHAS-PKG-MAMMOGRAPHY-40-75",
            "missing_sex",
            "GUARD-MISSING-ATTRIBUTE",
        ),
        (
            date(1976, 1, 1),
            "female",
            None,
            False,
            "IFHAS-PROG-ELIG-THIQA",
            "missing_required_attribute",
            "GUARD-MISSING-ATTRIBUTE",
        ),
        (
            date(1956, 1, 1),
            "male",
            True,
            None,
            "IFHAS-PKG-AAA-M-65-75",
            "missing_required_attribute",
            "GUARD-MISSING-ATTRIBUTE",
        ),
    ],
)
def test_missing_attributes_yield_insufficient_information(
    engine, dob, sex, thiqa, smoked, target_rule, expected_reason, expected_guard
):
    patient = PatientContext(
        patient_id="SYNTH-PAT-000004",
        date_of_birth=dob,
        sex=sex,
        thiqa_member=thiqa,
        ever_smoked=smoked,
        history_by_pathway={"ifhas": "available"},
    )
    res = engine.evaluate_patient(patient, reference_date=REF_DATE)
    by_rule = {e.rule_id: e for e in res.evaluations}
    ev = by_rule[target_rule]
    assert ev.evaluation_status == "insufficient_information"
    assert ev.reason_code == expected_reason
    assert any(r.guard_id == expected_guard for r in ev.reasons)


def test_positive_exclusion_and_out_of_band_yield_not_eligible(engine):
    # 68yo male who never smoked -> not_eligible for AAA, not_eligible for female packages
    patient = PatientContext(
        patient_id="SYNTH-PAT-000007",
        date_of_birth=date(1958, 1, 1),
        sex="male",
        thiqa_member=True,
        ever_smoked=False,
        history_by_pathway={"ifhas": "available"},
    )
    res = engine.evaluate_patient(patient, reference_date=REF_DATE)
    by_rule = {e.rule_id: e for e in res.evaluations}
    assert by_rule["IFHAS-PKG-AAA-M-65-75"].evaluation_status == "not_eligible"
    assert by_rule["IFHAS-PKG-MAMMOGRAPHY-40-75"].evaluation_status == "not_eligible"
    assert by_rule["IFHAS-PKG-MAJOR-18-39"].evaluation_status == "not_eligible"


def test_unresolved_and_review_flagged_rules_route_to_clinical_review(engine):
    # 58yo female: hits Cervical HPV (flagged), Liquid Biopsy (flagged), Lung LDCT (flagged), Age Ceiling (unresolved)
    patient = PatientContext(
        patient_id="SYNTH-PAT-000008",
        date_of_birth=date(1968, 4, 1),
        sex="female",
        thiqa_member=True,
        ever_smoked=True,
        history_by_pathway={"ifhas": "available"},
    )
    res = engine.evaluate_patient(patient, reference_date=REF_DATE)
    by_rule = {e.rule_id: e for e in res.evaluations}

    for flagged in (
        "IFHAS-PKG-CERVICAL-HPV-30-65",
        "IFHAS-PKG-LIQUID-BIOPSY-40-75",
        "IFHAS-PKG-LUNG-LDCT-55-75",
    ):
        ev = by_rule[flagged]
        assert ev.evaluation_status == "requires_clinical_review", flagged
        assert ev.reason_code == "rule_requires_clinical_review"
        assert any(r.guard_id == "GUARD-RULE-REVIEW-FLAG" for r in ev.reasons)
        # Non-authoritative rules must never create authoritative care gaps
        assert all(g.rule_id != flagged for g in res.care_gaps)

    ceiling = by_rule["IFHAS-PROG-AGE-CEILING"]
    assert ceiling.evaluation_status == "requires_clinical_review"
    assert ceiling.reason_code == "rule_unresolved"
    assert any(r.guard_id == "GUARD-RULE-NOT-VERIFIED" for r in ceiling.reasons)


def test_well_child_never_produces_overdue_and_tracks_unresolved_items(engine):
    # Child aged 15 months (born 2025-08-16) with history available, 12M visit missed, 15M due now
    child = PatientContext(
        patient_id="SYNTH-PAT-000012",
        date_of_birth=date(2025, 8, 16),
        sex="female",
        thiqa_member=True,
        ever_smoked=None,
        history_by_pathway={"well_child": "available"},
        well_child_visits=(
            VisitEventFact(
                visit_id="SYNTH-VIS-000001",
                rule_id="WCV-VISIT-12M",
                rule_version="1.0.0",
                attendance_status="not_attended",
                performed_date=None,
            ),
        ),
    )
    res = engine.evaluate_patient(child, reference_date=REF_DATE)
    by_rule = {e.rule_id: e for e in res.evaluations}

    # No Well-Child evaluation may ever be 'overdue'
    assert all(
        e.evaluation_status != "overdue"
        for e in res.evaluations
        if e.rule_id.startswith("WCV-")
    )

    # 12M missed visit yields visit_not_attended gap
    gaps_by_rule = {g.rule_id: g for g in res.care_gaps}
    assert gaps_by_rule["WCV-VISIT-12M"].gap_type == "visit_not_attended"
    assert gaps_by_rule["WCV-VISIT-12M"].subject_well_child_visit_id == "SYNTH-VIS-000001"

    # 15M visit is due and records the unresolved item `oral_examination` in reasons
    ev_15m = by_rule["WCV-VISIT-15M"]
    assert ev_15m.evaluation_status == "due"
    assert any(
        r.guard_id == "GUARD-ITEM-UNRESOLVED" and r.item_code == "oral_examination"
        for r in ev_15m.reasons
    )


def test_documented_refusal_closes_gap_as_closed_refused_and_overdue_referral_opens_gap(engine):
    # Adult female 45yo who has a valid documented & signed consent refusal for Mammography,
    # and an overdue uninitiated referral from IFHAS-WF-REFERRAL-15WD
    patient = PatientContext(
        patient_id="SYNTH-PAT-000015",
        date_of_birth=date(1981, 5, 10),
        sex="female",
        thiqa_member=True,
        ever_smoked=False,
        history_by_pathway={"ifhas": "available"},
        consents=(
            ConsentFact(
                consent_id="SYNTH-CNS-000001",
                consent_type="screening_participation",
                state="refused",
                applies_to="self",
                scope_pathway="ifhas",
                scope_rule_id="IFHAS-PKG-MAMMOGRAPHY-40-75",
                scope_rule_version="1.0.0",
                recorded_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
                documented_in_record=True,
                signature_on_file=True,
            ),
        ),
        referrals=(
            ReferralFact(
                referral_id="SYNTH-REF-000001",
                trigger_rule_id="IFHAS-WF-REFERRAL-15WD",
                trigger_rule_version="1.0.0",
                trigger_date=date(2026, 9, 1),
                initiated_date=None,
                completed_date=None,
                status="pending",
            ),
        ),
    )
    res = engine.evaluate_patient(patient, reference_date=REF_DATE)
    gaps_by_rule = {g.rule_id: g for g in res.care_gaps}

    mammo_gap = gaps_by_rule["IFHAS-PKG-MAMMOGRAPHY-40-75"]
    assert mammo_gap.status == "closed_refused"
    assert mammo_gap.closed_by_consent_id == "SYNTH-CNS-000001"
    assert mammo_gap.closed_date == date(2026, 10, 1)

    ref_gap = gaps_by_rule["IFHAS-WF-REFERRAL-15WD"]
    assert ref_gap.gap_type == "referral_not_initiated"
    assert ref_gap.subject_referral_id == "SYNTH-REF-000001"
    assert ref_gap.status == "open"


def test_refusal_evidence_requires_signature_and_guardian_for_well_child(engine):
    # 1. Adult with unsigned consent refusal -> must NOT close gap as closed_refused
    adult_unsigned = PatientContext(
        patient_id="SYNTH-PAT-000901",
        date_of_birth=date(1981, 5, 10),
        sex="female",
        thiqa_member=True,
        ever_smoked=False,
        history_by_pathway={"ifhas": "available"},
        consents=(
            ConsentFact(
                consent_id="SYNTH-CNS-000901",
                consent_type="screening_participation",
                state="refused",
                applies_to="self",
                scope_pathway="ifhas",
                scope_rule_id="IFHAS-PKG-MAMMOGRAPHY-40-75",
                scope_rule_version="1.0.0",
                recorded_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
                documented_in_record=True,
                signature_on_file=False,
            ),
        ),
        component_results=(
            ComponentResultFact(
                component_result_id="SYNTH-CMP-000901",
                rule_id="IFHAS-PKG-VISION-40-75",
                rule_version="1.0.0",
                item_category="preventive_assessments",
                item_code="visual_acuity_assessment",
                status="refused",
                recorded_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
            ),
        ),
    )
    res_unsigned = engine.evaluate_patient(adult_unsigned, reference_date=REF_DATE)
    gaps_unsigned = {g.rule_id: g for g in res_unsigned.care_gaps}
    assert gaps_unsigned["IFHAS-PKG-MAMMOGRAPHY-40-75"].status == "open"
    assert gaps_unsigned["IFHAS-PKG-VISION-40-75"].status == "open"

    # 2. Child with Well-Child consent refusal where applies_to='self' instead of 'child_by_guardian' -> open
    child_non_guardian = PatientContext(
        patient_id="SYNTH-PAT-000902",
        date_of_birth=date(2025, 5, 16),
        sex="female",
        thiqa_member=True,
        ever_smoked=None,
        history_by_pathway={"well_child": "available"},
        consents=(
            ConsentFact(
                consent_id="SYNTH-CNS-000902",
                consent_type="screening_participation",
                state="refused",
                applies_to="self",
                scope_pathway="well_child",
                scope_rule_id="WCV-VISIT-18M",
                scope_rule_version="1.0.0",
                recorded_at=datetime(2026, 11, 1, tzinfo=timezone.utc),
                documented_in_record=True,
                signature_on_file=True,
            ),
        ),
    )
    res_child = engine.evaluate_patient(child_non_guardian, reference_date=REF_DATE)
    gaps_child = {g.rule_id: g for g in res_child.care_gaps}
    assert gaps_child["WCV-VISIT-18M"].status == "open"


def test_conflicting_screening_records_trigger_guard_conflicting_records(engine):
    patient = PatientContext(
        patient_id="SYNTH-PAT-000903",
        date_of_birth=date(1979, 2, 20),
        sex="female",
        thiqa_member=True,
        ever_smoked=False,
        history_by_pathway={"ifhas": "available"},
        ifhas_screenings=(
            ScreeningEventFact(
                screening_id="SYNTH-SCR-000901",
                rule_id="IFHAS-PKG-MAMMOGRAPHY-40-75",
                rule_version="1.0.0",
                completion_status="complete",
                performed_date=date(2026, 6, 10),
            ),
            ScreeningEventFact(
                screening_id="SYNTH-SCR-000902",
                rule_id="IFHAS-PKG-MAMMOGRAPHY-40-75",
                rule_version="1.0.0",
                completion_status="partial",
                performed_date=date(2026, 6, 10),
            ),
        ),
    )
    res = engine.evaluate_patient(patient, reference_date=REF_DATE)
    by_rule = {e.rule_id: e for e in res.evaluations}
    mammo = by_rule["IFHAS-PKG-MAMMOGRAPHY-40-75"]
    assert mammo.evaluation_status == "requires_clinical_review"
    assert mammo.reason_code == "conflicting_records"
    assert any(r.guard_id == "GUARD-CONFLICTING-RECORDS" for r in mammo.reasons)
    assert all(g.rule_id != "IFHAS-PKG-MAMMOGRAPHY-40-75" for g in res.care_gaps)


def test_workflow_results_communication_10d_and_journey_completion_15d(engine):
    # Screening performed 22 days ago with uncommunicated results and unreported journey -> due + care gap
    patient_breach = PatientContext(
        patient_id="SYNTH-PAT-000904",
        date_of_birth=date(1983, 1, 25),
        sex="female",
        thiqa_member=True,
        ever_smoked=False,
        history_by_pathway={"ifhas": "available"},
        ifhas_screenings=(
            ScreeningEventFact(
                screening_id="SYNTH-SCR-000904",
                rule_id="IFHAS-PKG-MAJOR-40-64",
                rule_version="1.0.0",
                completion_status="complete",
                performed_date=date(2026, 10, 25),
                results_communicated_date=None,
                journey_reported_date=None,
            ),
        ),
    )
    res_breach = engine.evaluate_patient(patient_breach, reference_date=REF_DATE)
    by_rule = {e.rule_id: e for e in res_breach.evaluations}
    gaps_by_rule = {g.rule_id: g for g in res_breach.care_gaps}

    assert by_rule["IFHAS-WF-RESULTS-COMMUNICATION-10D"].evaluation_status == "due"
    assert gaps_by_rule["IFHAS-WF-RESULTS-COMMUNICATION-10D"].gap_type == "partial_completion"
    assert gaps_by_rule["IFHAS-WF-RESULTS-COMMUNICATION-10D"].subject_ifhas_screening_id == "SYNTH-SCR-000904"

    assert by_rule["IFHAS-WF-JOURNEY-COMPLETION-15D"].evaluation_status == "due"
    assert gaps_by_rule["IFHAS-WF-JOURNEY-COMPLETION-15D"].gap_type == "partial_completion"
    assert gaps_by_rule["IFHAS-WF-JOURNEY-COMPLETION-15D"].subject_ifhas_screening_id == "SYNTH-SCR-000904"

    # Screening with timely communication (5d) and journey reporting (10d) -> completed, no care gap
    patient_ok = PatientContext(
        patient_id="SYNTH-PAT-000905",
        date_of_birth=date(1983, 1, 25),
        sex="female",
        thiqa_member=True,
        ever_smoked=False,
        history_by_pathway={"ifhas": "available"},
        ifhas_screenings=(
            ScreeningEventFact(
                screening_id="SYNTH-SCR-000905",
                rule_id="IFHAS-PKG-MAJOR-40-64",
                rule_version="1.0.0",
                completion_status="complete",
                performed_date=date(2026, 10, 25),
                results_communicated_date=date(2026, 10, 30),
                journey_reported_date=date(2026, 11, 4),
            ),
        ),
    )
    res_ok = engine.evaluate_patient(patient_ok, reference_date=REF_DATE)
    by_rule_ok = {e.rule_id: e for e in res_ok.evaluations}
    gaps_ok = {g.rule_id: g for g in res_ok.care_gaps}
    assert by_rule_ok["IFHAS-WF-RESULTS-COMMUNICATION-10D"].evaluation_status == "completed"
    assert by_rule_ok["IFHAS-WF-JOURNEY-COMPLETION-15D"].evaluation_status == "completed"
    assert "IFHAS-WF-RESULTS-COMMUNICATION-10D" not in gaps_ok
    assert "IFHAS-WF-JOURNEY-COMPLETION-15D" not in gaps_ok


@pytest.mark.parametrize(
    ("status", "initiated_date", "completed_date", "expected_eval_status", "expected_reason"),
    [
        ("pending", None, None, "due", None),
        ("initiated", date(2026, 10, 25), None, "upcoming", None),
        ("initiated", None, None, "upcoming", None),
        ("scheduled", date(2026, 10, 26), None, "upcoming", None),
        ("scheduled", None, None, "upcoming", None),
        ("cancelled", date(2026, 10, 26), None, "requires_clinical_review", "referral_cancelled"),
        ("completed", date(2026, 10, 26), date(2026, 11, 2), "completed", None),
        ("completed", date(2026, 10, 26), None, "requires_clinical_review", "missing_completion_evidence"),
    ],
)
def test_referral_status_mapping_never_falsely_completes(
    engine: EvaluationEngine,
    status: str,
    initiated_date: date | None,
    completed_date: date | None,
    expected_eval_status: str,
    expected_reason: str | None,
):
    patient = PatientContext(
        patient_id="SYNTH-PAT-000910",
        date_of_birth=date(1980, 5, 10),
        sex="female",
        thiqa_member=True,
        ever_smoked=False,
        history_by_pathway={"ifhas": "available"},
        referrals=(
            ReferralFact(
                referral_id="SYNTH-REF-000910",
                trigger_rule_id="IFHAS-WF-REFERRAL-15WD",
                trigger_rule_version="1.0.0",
                trigger_date=date(2026, 10, 1),
                initiated_date=initiated_date,
                completed_date=completed_date,
                status=status,
            ),
        ),
    )
    res = engine.evaluate_patient(patient, reference_date=REF_DATE)
    ev = {e.rule_id: e for e in res.evaluations}["IFHAS-WF-REFERRAL-15WD"]
    assert ev.evaluation_status == expected_eval_status
    if expected_reason is not None:
        assert ev.reason_code == expected_reason
        assert any(r.reason_code == expected_reason for r in ev.reasons)
    if expected_eval_status == "completed":
        assert ev.last_completed_date == completed_date


def test_engine_derives_age_and_month_thresholds_from_bundle(engine: EvaluationEngine):
    import copy
    from dataclasses import replace

    rules_copy = copy.deepcopy(engine.bundle.rules)
    for r in rules_copy:
        if r["rule_id"] == "IFHAS-PROG-ELIG-MIN-AGE":
            r["spec"]["min_years"] = 21
        if r.get("pathway") == "ifhas" and r.get("age_max_years") is not None:
            r["age_max_years"] = min(int(r["age_max_years"]), 70)
        if r.get("pathway") == "well_child" and r.get("recommended_age_months") is not None:
            r["recommended_age_months"] = min(int(r["recommended_age_months"]), 60)

    custom_bundle = replace(engine.bundle, rules=rules_copy)
    custom_engine = EvaluationEngine(custom_bundle)

    # 19-year-old -> not_eligible under min_years=21
    p19 = PatientContext(
        patient_id="SYNTH-PAT-000911",
        date_of_birth=date(2007, 1, 1),
        sex="female",
        thiqa_member=True,
        ever_smoked=False,
        history_by_pathway={"ifhas": "available"},
    )
    ev19 = {
        e.rule_id: e
        for e in custom_engine.evaluate_patient(p19, reference_date=REF_DATE).evaluations
    }
    assert ev19["IFHAS-PROG-ELIG-MIN-AGE"].evaluation_status == "not_eligible"

    # 72-year-old -> requires_clinical_review under max verified age=70
    p72 = PatientContext(
        patient_id="SYNTH-PAT-000912",
        date_of_birth=date(1954, 1, 1),
        sex="female",
        thiqa_member=True,
        ever_smoked=False,
        history_by_pathway={"ifhas": "available"},
    )
    ev72 = {
        e.rule_id: e
        for e in custom_engine.evaluate_patient(p72, reference_date=REF_DATE).evaluations
    }
    assert ev72["IFHAS-PROG-ELIG-MIN-AGE"].evaluation_status == "requires_clinical_review"

    # 66-month-old -> not_eligible under WCV max months=60
    p66m = PatientContext(
        patient_id="SYNTH-PAT-000913",
        date_of_birth=date(2021, 5, 16),
        sex="male",
        thiqa_member=True,
        ever_smoked=None,
        history_by_pathway={"well_child": "available"},
    )
    ev66m = {
        e.rule_id: e
        for e in custom_engine.evaluate_patient(p66m, reference_date=REF_DATE).evaluations
    }
    assert ev66m["WCV-PROG-SCOPE"].evaluation_status == "not_eligible"


def test_engine_strict_boolean_rejects_truthy_non_bool_values(engine: EvaluationEngine):
    # Non-bool thiqa_member ('false' or 1) must produce insufficient_information, never eligible
    for bad_thiqa in ("false", 1):
        p = PatientContext(
            patient_id="SYNTH-PAT-000914",
            date_of_birth=date(1985, 5, 10),
            sex="female",
            thiqa_member=bad_thiqa,  # type: ignore[arg-type]
            ever_smoked=False,
            history_by_pathway={"ifhas": "available"},
        )
        evs = {
            e.rule_id: e
            for e in engine.evaluate_patient(p, reference_date=REF_DATE).evaluations
        }
        assert evs["IFHAS-PROG-ELIG-THIQA"].evaluation_status == "insufficient_information"
        assert evs["IFHAS-PKG-MAJOR-18-39"].evaluation_status == "insufficient_information"

    # Non-bool ever_smoked=1 on AAA -> insufficient_information
    p_smoke = PatientContext(
        patient_id="SYNTH-PAT-000916",
        date_of_birth=date(1958, 5, 10),
        sex="male",
        thiqa_member=True,
        ever_smoked=1,  # type: ignore[arg-type]
        history_by_pathway={"ifhas": "available"},
    )
    evs_smoke = {
        e.rule_id: e
        for e in engine.evaluate_patient(p_smoke, reference_date=REF_DATE).evaluations
    }
    assert evs_smoke["IFHAS-PKG-AAA-M-65-75"].evaluation_status == "insufficient_information"

    # Non-bool documented_in_record=1 / signature_on_file='true' must NOT close refusal gap
    p_ref = PatientContext(
        patient_id="SYNTH-PAT-000915",
        date_of_birth=date(1981, 5, 10),
        sex="female",
        thiqa_member=True,
        ever_smoked=False,
        history_by_pathway={"ifhas": "available"},
        consents=(
            ConsentFact(
                consent_id="SYNTH-CNS-000915",
                consent_type="screening_participation",
                state="refused",
                applies_to="self",
                scope_pathway="ifhas",
                scope_rule_id="IFHAS-PKG-MAMMOGRAPHY-40-75",
                scope_rule_version="1.0.0",
                recorded_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
                documented_in_record=1,  # type: ignore[arg-type]
                signature_on_file="true",  # type: ignore[arg-type]
            ),
        ),
    )
    gaps = {
        g.rule_id: g
        for g in engine.evaluate_patient(p_ref, reference_date=REF_DATE).care_gaps
    }
    assert gaps["IFHAS-PKG-MAMMOGRAPHY-40-75"].status == "open"



