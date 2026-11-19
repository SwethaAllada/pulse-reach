"""Regression tests for F-01 / BE-01A: care-gap completion evidence validation.

A care gap may only become `closed_completed` with completion evidence that belongs to the same
patient, is the right evidence type for the gap, is for the gap's own rule, is documented as
completed, has a valid date, and on which the evaluation engine itself - re-run on the patient's
current records - reports the rule satisfied. Cases the engine routes to clinical review (e.g.
partial + complete records for one rule) cannot be closed as completed. Historical evaluations are
never rewritten; the API flags evaluations superseded by a later completion.

Covers the shared domain validator (with the real engine), the memory API path and the PostgreSQL
repository path (exercised on SQLite with constraints stripped - not a real PostgreSQL test).
"""

from __future__ import annotations

import copy
import dataclasses
from datetime import date

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import JSON, CheckConstraint, ForeignKeyConstraint, MetaData, create_engine, event, select
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Session

from app.main import app
from app.models.clinical import Rule, Standard
from app.models.synthetic import (
    Assessment,
    CareGap,
    CareGapFollowUpEvent,
    ComponentResult,
    Consent,
    EligibilityEvaluation,
    EvaluationReason,
    EvaluationRun,
    GenerationRun,
    HistoryAvailability,
    IfhasScreening,
    Patient,
    Referral,
    WellChildVisit,
    WorkflowStatusEvent,
)
from app.repositories.followup_repo import (
    reset_memory_writes,
    PostgresFollowUpRepository,
    get_memory_follow_up_events,
)
from app.repositories.read_repo import (
    MemoryReadRepository,
    PostgresReadRepository,
    get_cached_bundle,
    get_cached_dataset,
    get_cached_engine,
    get_cached_index,
)
from app.schemas.v1 import FollowUpCreateIn
from app.services.evaluation import ReferralFact, ScreeningEventFact, VisitEventFact
from app.services.followup import (
    CompletionEvidence,
    evaluate_current_rule,
    validate_completion_evidence,
)

client = TestClient(app)

# Fixed facts of the deterministic synthetic dataset (seed 20261116, reference date 2026-11-16).
REF_DATE = date(2026, 11, 16)
VISION_RULE = "IFHAS-PKG-VISION-40-75"
MAJOR_RULE = "IFHAS-PKG-MAJOR-40-64"
F01_PATIENT = "SYNTH-PAT-000008"
F01_VISION_GAP = "SYNTH-GAP-000017"  # open no_documented_screening gap on VISION
F01_PARTIAL_SCREENING = "SYNTH-SCR-000002"  # partial screening for IFHAS-PKG-MAJOR-40-64
PARTIAL_GAP = "SYNTH-GAP-000016"  # MAJOR-40-64 partial_completion, subject SYNTH-SCR-000002
REFERRAL_GAP = "SYNTH-GAP-000026"  # referral_not_initiated, subject SYNTH-REF-000001 (pending)
REFERRAL_PATIENT = "SYNTH-PAT-000009"
REFERRAL_ID = "SYNTH-REF-000001"
OTHER_PATIENT_REFERRAL = "SYNTH-REF-000002"  # belongs to SYNTH-PAT-000029
VISIT_GAP = "SYNTH-GAP-000048"  # visit_not_attended, WCV-VISIT-12M, subject SYNTH-VIS-000005
VISIT_PATIENT = "SYNTH-PAT-000017"
NOT_ATTENDED_VISIT = "SYNTH-VIS-000005"
OTHER_PATIENT_VISIT = "SYNTH-VIS-000001"  # belongs to SYNTH-PAT-000013
VISIT_DUE_GAP = "SYNTH-GAP-000049"  # no_documented_screening on WCV-VISIT-15M, no visit records
VISIT_DUE_PATIENT = "SYNTH-PAT-000018"


@pytest.fixture(autouse=True)
def _reset_memory_dataset():
    get_cached_index.cache_clear()
    get_cached_dataset.cache_clear()
    yield
    reset_memory_writes()
    get_cached_index.cache_clear()
    get_cached_dataset.cache_clear()


def _gap(gap_id: str) -> dict:
    return next(g for g in get_cached_dataset().care_gaps if g["care_gap_id"] == gap_id)


def _rule(rule_id: str) -> dict:
    return next(r for r in get_cached_bundle().rules if r["rule_id"] == rule_id)


def _close_body(evidence_reference: str | None, documented: bool = True) -> dict:
    return {
        "event_type": "completion_documented",
        "close_gap": True,
        "documented_evidence": documented,
        "evidence_reference": evidence_reference,
        "recorded_by": "clinician_ui",
    }


def _evaluation(patient_id: str, rule_id: str) -> dict:
    evals = client.get(f"/api/v1/patients/{patient_id}/evaluations").json()["evaluations"]
    return next(e for e in evals if e["rule_id"] == rule_id)


def _evaluation_status(patient_id: str, rule_id: str) -> str:
    return _evaluation(patient_id, rule_id)["evaluation_status"]


def _add_screening(screening_id: str, *, patient_id: str, rule_id: str, status: str, performed: date | None):
    """Document a new screening in the memory dataset (dataset list and patient index)."""
    ds, idx = get_cached_dataset(), get_cached_index()
    row = {
        "screening_id": screening_id,
        "run_id": ds.generation_run["run_id"],
        "patient_id": patient_id,
        "rule_id": rule_id,
        "rule_version": _rule(rule_id)["rule_version"],
        "performed_date": performed,
        "completion_status": status,
    }
    ds.ifhas_screenings.append(row)
    idx.ifhas_by_patient.setdefault(patient_id, []).append(row)


def _add_visit(visit_id: str, *, patient_id: str, rule_id: str, status: str, performed: date | None):
    ds, idx = get_cached_dataset(), get_cached_index()
    row = {
        "visit_id": visit_id,
        "run_id": ds.generation_run["run_id"],
        "patient_id": patient_id,
        "rule_id": rule_id,
        "rule_version": _rule(rule_id)["rule_version"],
        "performed_date": performed,
        "attendance_status": status,
    }
    ds.well_child_visits.append(row)
    idx.wcv_by_patient.setdefault(patient_id, []).append(row)


def _assert_gap_untouched(gap_id: str, before: dict) -> None:
    after = _gap(gap_id)
    assert after == before
    assert after["status"] == "open"
    assert after["closed_date"] is None
    assert after["closed_by_ifhas_screening_id"] is None
    assert after["closed_by_well_child_visit_id"] is None
    assert after["closed_by_referral_id"] is None
    # Workflow writes (e.g. referral status changes) are logged on the gap; no completion is.
    assert [
        e for e in get_memory_follow_up_events(gap_id) if e["event_type"] == "completion_documented"
    ] == []


# ---------------------------------------------------------------------------
# 1. Shared domain validator, with the real engine on real patient contexts
# ---------------------------------------------------------------------------


def _screening_evidence(**overrides) -> CompletionEvidence:
    base = {
        "kind": "ifhas_screening",
        "evidence_id": "SYNTH-SCR-999001",
        "patient_id": F01_PATIENT,
        "rule_id": VISION_RULE,
        "rule_version": _rule(VISION_RULE)["rule_version"],
        "status": "complete",
        "evidence_date": date(2026, 11, 10),
    }
    base.update(overrides)
    return CompletionEvidence(**base)


def _context_with(patient_id: str, evidence: list[CompletionEvidence], history: dict | None = None):
    """Patient's current records plus the given evidence (only evidence of that patient)."""
    ctx = MemoryReadRepository().get_patient_context(patient_id)
    own = [e for e in evidence if e.patient_id == patient_id]
    screenings = tuple(
        ScreeningEventFact(e.evidence_id, e.rule_id, e.rule_version, e.status, e.evidence_date)
        for e in own
        if e.kind == "ifhas_screening"
    )
    visits = tuple(
        VisitEventFact(e.evidence_id, e.rule_id, e.rule_version, e.status, e.evidence_date)
        for e in own
        if e.kind == "well_child_visit"
    )
    replaced = {e.evidence_id: e for e in own if e.kind == "referral"}
    referrals = tuple(
        dataclasses.replace(
            r,
            status=replaced[r.referral_id].status,
            initiated_date=r.initiated_date or r.trigger_date,
            completed_date=replaced[r.referral_id].evidence_date,
        )
        if r.referral_id in replaced
        else r
        for r in ctx.referrals
    )
    return dataclasses.replace(
        ctx,
        ifhas_screenings=ctx.ifhas_screenings + screenings,
        well_child_visits=ctx.well_child_visits + visits,
        referrals=referrals,
        history_by_pathway=history if history is not None else ctx.history_by_pathway,
    )


def _validate(gap=None, evidence=None, rule=None, *, extra=(), history=None, documented=True, reference="SYNTH-SCR-999001"):
    gap = gap if gap is not None else _gap(F01_VISION_GAP)
    records = [*extra, *([evidence] if evidence is not None else [])]
    current = evaluate_current_rule(
        get_cached_engine(),
        _context_with(gap["patient_id"], records, history),
        rule_id=gap["rule_id"],
        rule_version=gap["rule_version"],
        as_of=REF_DATE,
        look_ahead_days=30,
    )
    return validate_completion_evidence(
        gap=gap,
        rule=rule if rule is not None else _rule(gap["rule_id"]),
        evidence=evidence,
        documented_evidence=documented,
        evidence_reference=reference,
        as_of=REF_DATE,
        current_evaluation=current,
    )


def test_validator_accepts_complete_evidence_only():
    res = _validate(evidence=_screening_evidence())
    assert res.accepted is True
    assert res.reason_code == "evidence_accepted"
    assert res.closed_by_field == "closed_by_ifhas_screening_id"
    assert res.evidence_id == "SYNTH-SCR-999001"


@pytest.mark.parametrize(
    ("evidence_overrides", "reason_code"),
    [
        ({"patient_id": "SYNTH-PAT-000001"}, "evidence_patient_mismatch"),
        ({"rule_id": MAJOR_RULE}, "evidence_rule_mismatch"),
        ({"rule_version": "0.0.1"}, "evidence_rule_mismatch"),
        ({"status": "partial"}, "evidence_not_completed"),
        ({"status": "pending"}, "evidence_not_completed"),
        ({"status": "cancelled"}, "evidence_not_completed"),
        ({"status": "refused"}, "evidence_not_completed"),
        ({"status": "not_attended"}, "evidence_not_completed"),
        ({"status": None}, "evidence_not_completed"),
        ({"status": "something_unknown"}, "evidence_not_completed"),
        ({"evidence_date": None}, "evidence_date_missing"),
        ({"evidence_date": date(2026, 11, 17)}, "evidence_date_in_future"),
        # VISION is annual: the engine reports `due` for a screening one year before REF_DATE.
        ({"evidence_date": date(2025, 11, 16)}, "evaluation_not_completed"),
        ({"kind": "referral", "evidence_id": "SYNTH-REF-999001", "status": "completed"}, "evidence_type_mismatch"),
        ({"kind": "well_child_visit", "evidence_id": "SYNTH-VIS-999001", "status": "attended"}, "evidence_type_mismatch"),
    ],
)
def test_validator_rejects_invalid_screening_evidence(evidence_overrides, reason_code):
    res = _validate(evidence=_screening_evidence(**evidence_overrides))
    assert res.accepted is False
    assert res.reason_code == reason_code
    assert res.closed_by_field is None


def test_validator_accepts_evidence_just_inside_interval():
    res = _validate(evidence=_screening_evidence(evidence_date=date(2025, 11, 17)))
    assert res.accepted is True  # engine: `upcoming`, completed within the interval


def test_validator_rejects_partial_evidence_only():
    gap = _gap(PARTIAL_GAP)
    partial = _screening_evidence(
        evidence_id=F01_PARTIAL_SCREENING, rule_id=MAJOR_RULE,
        rule_version=gap["rule_version"], status="partial", evidence_date=date(2026, 10, 10),
    )
    res = _validate(gap, partial, reference=F01_PARTIAL_SCREENING)
    assert res.accepted is False and res.reason_code == "evidence_not_completed"


def test_validator_rejects_partial_plus_complete_evidence_as_clinical_review():
    gap = _gap(PARTIAL_GAP)
    complete = _screening_evidence(
        rule_id=MAJOR_RULE, rule_version=gap["rule_version"], evidence_date=date(2026, 11, 12)
    )
    res = _validate(gap, complete)
    assert res.accepted is False
    assert res.reason_code == "evaluation_requires_clinical_review"
    assert "conflicting_records" in res.detail


def test_validator_rejects_when_engine_requires_clinical_review():
    ctx = MemoryReadRepository().get_patient_context(F01_PATIENT)
    res = _validate(evidence=_screening_evidence(), history={**ctx.history_by_pathway, "ifhas": "partial"})
    assert res.accepted is False and res.reason_code == "evaluation_requires_clinical_review"


def test_validator_requires_evidence_the_evaluation_relies_on():
    older = _screening_evidence(evidence_id="SYNTH-SCR-999002", evidence_date=date(2026, 11, 1))
    newer = _screening_evidence(evidence_id="SYNTH-SCR-999003", evidence_date=date(2026, 11, 10))
    assert _validate(evidence=older, extra=[newer]).reason_code == "evidence_not_relied_on"
    assert _validate(evidence=newer, extra=[older]).accepted is True


def test_validator_rejects_missing_unknown_evidence_and_missing_evaluation():
    assert _validate(evidence=None, documented=False).reason_code == "evidence_missing"
    assert _validate(evidence=None, reference="  ").reason_code == "evidence_missing"
    assert _validate(evidence=None, reference=None).reason_code == "evidence_missing"
    assert _validate(evidence=None, reference="DOC-FREE-TEXT-1").reason_code == "evidence_not_found"
    no_eval = validate_completion_evidence(
        gap=_gap(F01_VISION_GAP), rule=_rule(VISION_RULE), evidence=_screening_evidence(),
        documented_evidence=True, evidence_reference="SYNTH-SCR-999001", as_of=REF_DATE,
        current_evaluation=None,
    )
    assert no_eval.reason_code == "evaluation_unavailable"


def test_validator_rejects_closed_gap_and_non_authoritative_rule():
    closed = {**_gap(F01_VISION_GAP), "status": "closed_completed"}
    assert _validate(closed, _screening_evidence()).reason_code == "care_gap_not_open"
    unverified = {**_rule(VISION_RULE), "verification_status": "reported_not_verified"}
    assert _validate(evidence=_screening_evidence(), rule=unverified).reason_code == "rule_not_authoritative"
    review = {**_rule(VISION_RULE), "requires_clinical_review": True}
    assert _validate(evidence=_screening_evidence(), rule=review).reason_code == "rule_not_authoritative"
    other_rule = _rule(MAJOR_RULE)
    assert _validate(evidence=_screening_evidence(), rule=other_rule).reason_code == "rule_not_found"


def test_validator_rejects_unresolvable_interval():
    no_interval = {**_rule(VISION_RULE), "interval_value": None}
    assert (
        _validate(evidence=_screening_evidence(), rule=no_interval).reason_code
        == "rule_interval_unresolved"
    )


def test_validator_requires_evidence_on_or_after_identified_date_for_event_gaps():
    gap = {**_gap(F01_VISION_GAP), "gap_type": "interval_elapsed", "identified_date": date(2026, 11, 1)}
    assert _validate(gap, _screening_evidence(evidence_date=date(2026, 10, 31))).reason_code == (
        "evidence_predates_gap"
    )
    assert _validate(gap, _screening_evidence(evidence_date=date(2026, 11, 1))).accepted is True


def test_validator_has_no_evidence_mapping_for_workflow_timing_gap():
    gap = _gap("SYNTH-GAP-000032")  # IFHAS-WF-RESULTS-COMMUNICATION-10D partial_completion
    ev = _screening_evidence(
        patient_id=gap["patient_id"], rule_id=gap["rule_id"], rule_version=gap["rule_version"]
    )
    res = _validate(gap, ev)
    assert res.accepted is False and res.reason_code == "no_completion_evidence_mapping"


def test_validator_referral_semantics():
    gap = _gap(REFERRAL_GAP)
    base = {
        "kind": "referral",
        "evidence_id": REFERRAL_ID,
        "patient_id": REFERRAL_PATIENT,
        "rule_id": gap["rule_id"],
        "rule_version": gap["rule_version"],
        "status": "completed",
        "evidence_date": date(2026, 10, 1),
    }
    assert _validate(gap, CompletionEvidence(**base), reference=REFERRAL_ID).accepted is True
    for status in ("pending", "initiated", "declined", "cancelled"):
        res = _validate(gap, CompletionEvidence(**{**base, "status": status}), reference=REFERRAL_ID)
        assert res.reason_code == "evidence_not_completed", status
    other = CompletionEvidence(**{**base, "evidence_id": "SYNTH-REF-999009"})
    assert _validate(gap, other).reason_code == "evidence_subject_mismatch"
    no_date = CompletionEvidence(**{**base, "evidence_date": None})
    assert _validate(gap, no_date).reason_code == "evidence_date_missing"


def test_validator_visit_semantics():
    gap = _gap(VISIT_DUE_GAP)
    base = {
        "kind": "well_child_visit",
        "evidence_id": "SYNTH-VIS-999001",
        "patient_id": VISIT_DUE_PATIENT,
        "rule_id": gap["rule_id"],
        "rule_version": gap["rule_version"],
        "status": "attended",
        "evidence_date": date(2026, 11, 10),
    }
    assert _validate(gap, CompletionEvidence(**base)).accepted is True
    not_att = CompletionEvidence(**{**base, "status": "not_attended"})
    assert _validate(gap, not_att).reason_code == "evidence_not_completed"

    # A not-attended visit plus a later attended visit for the same rule: the engine reports
    # conflicting attendance records, so the gap is routed to review, not closed as completed.
    na_gap = _gap(VISIT_GAP)
    makeup = CompletionEvidence(
        **{**base, "patient_id": VISIT_PATIENT, "rule_id": na_gap["rule_id"], "rule_version": na_gap["rule_version"]}
    )
    assert _validate(na_gap, makeup).reason_code == "evaluation_requires_clinical_review"
    early = CompletionEvidence(**{**base, "patient_id": VISIT_PATIENT, "rule_id": na_gap["rule_id"],
                                  "rule_version": na_gap["rule_version"], "evidence_date": date(2026, 9, 1)})
    assert _validate(na_gap, early).reason_code == "evidence_predates_gap"


# ---------------------------------------------------------------------------
# 2. Memory-mode API path (POST /care-gaps/{id}/follow-ups)
# ---------------------------------------------------------------------------


def test_f01_partial_screening_for_other_rule_cannot_close_vision_gap():
    gap = _gap(F01_VISION_GAP)
    assert (gap["patient_id"], gap["rule_id"], gap["status"]) == (F01_PATIENT, VISION_RULE, "open")
    scr = next(s for s in get_cached_dataset().ifhas_screenings if s["screening_id"] == F01_PARTIAL_SCREENING)
    assert scr["patient_id"] == F01_PATIENT
    assert scr["completion_status"] == "partial" and scr["rule_id"] != VISION_RULE
    assert _evaluation_status(F01_PATIENT, VISION_RULE) == "due"
    before = copy.deepcopy(gap)

    resp = client.post(f"/api/v1/care-gaps/{F01_VISION_GAP}/follow-ups", json=_close_body(F01_PARTIAL_SCREENING))

    assert resp.status_code == 422
    assert "evidence_rule_mismatch" in resp.json()["detail"]
    _assert_gap_untouched(F01_VISION_GAP, before)
    assert client.get(f"/api/v1/care-gaps/{F01_VISION_GAP}").json()["status"] == "open"
    vision_eval = _evaluation(F01_PATIENT, VISION_RULE)
    assert vision_eval["evaluation_status"] == "due"
    assert vision_eval["superseded_by_completion"] is False


@pytest.mark.parametrize("status", ["partial", "pending", "cancelled", "refused", "not_attended"])
def test_api_rejects_non_completed_screening_for_same_rule(status):
    _add_screening("SYNTH-SCR-900010", patient_id=F01_PATIENT, rule_id=VISION_RULE, status=status, performed=date(2026, 11, 10))
    before = copy.deepcopy(_gap(F01_VISION_GAP))
    resp = client.post(f"/api/v1/care-gaps/{F01_VISION_GAP}/follow-ups", json=_close_body("SYNTH-SCR-900010"))
    assert resp.status_code == 422
    assert "evidence_not_completed" in resp.json()["detail"]
    _assert_gap_untouched(F01_VISION_GAP, before)


@pytest.mark.parametrize(
    ("performed", "reason"),
    [
        (None, "evidence_date_missing"),
        (date(2026, 11, 20), "evidence_date_in_future"),
        (date(2025, 6, 1), "evaluation_not_completed"),
    ],
)
def test_api_rejects_completed_screening_with_invalid_date(performed, reason):
    _add_screening("SYNTH-SCR-900011", patient_id=F01_PATIENT, rule_id=VISION_RULE, status="complete", performed=performed)
    before = copy.deepcopy(_gap(F01_VISION_GAP))
    resp = client.post(f"/api/v1/care-gaps/{F01_VISION_GAP}/follow-ups", json=_close_body("SYNTH-SCR-900011"))
    assert resp.status_code == 422
    assert reason in resp.json()["detail"]
    _assert_gap_untouched(F01_VISION_GAP, before)


def test_api_rejects_evidence_of_another_patient_unknown_and_missing_evidence():
    _add_screening("SYNTH-SCR-900012", patient_id="SYNTH-PAT-000001", rule_id=VISION_RULE, status="complete", performed=date(2026, 11, 10))
    before = copy.deepcopy(_gap(F01_VISION_GAP))
    other = client.post(f"/api/v1/care-gaps/{F01_VISION_GAP}/follow-ups", json=_close_body("SYNTH-SCR-900012"))
    assert other.status_code == 422 and "evidence_patient_mismatch" in other.json()["detail"]
    unknown = client.post(f"/api/v1/care-gaps/{F01_VISION_GAP}/follow-ups", json=_close_body("SYNTH-XYZ-000001"))
    assert unknown.status_code == 422 and "evidence_not_found" in unknown.json()["detail"]
    missing = client.post(f"/api/v1/care-gaps/{F01_VISION_GAP}/follow-ups", json=_close_body(None))
    assert missing.status_code == 422 and "evidence_missing" in missing.json()["detail"]
    undocumented = client.post(
        f"/api/v1/care-gaps/{F01_VISION_GAP}/follow-ups", json=_close_body("SYNTH-SCR-900012", documented=False)
    )
    assert undocumented.status_code == 422
    _assert_gap_untouched(F01_VISION_GAP, before)


def test_api_partial_only_and_partial_plus_complete_cannot_close_gap():
    before = copy.deepcopy(_gap(PARTIAL_GAP))
    partial_only = client.post(f"/api/v1/care-gaps/{PARTIAL_GAP}/follow-ups", json=_close_body(F01_PARTIAL_SCREENING))
    assert partial_only.status_code == 422 and "evidence_not_completed" in partial_only.json()["detail"]

    _add_screening("SYNTH-SCR-900015", patient_id=F01_PATIENT, rule_id=MAJOR_RULE, status="complete", performed=date(2026, 11, 12))
    both = client.post(f"/api/v1/care-gaps/{PARTIAL_GAP}/follow-ups", json=_close_body("SYNTH-SCR-900015"))
    assert both.status_code == 422
    assert "evaluation_requires_clinical_review" in both.json()["detail"]
    _assert_gap_untouched(PARTIAL_GAP, before)
    assert _evaluation_status(F01_PATIENT, MAJOR_RULE) == "due"


def test_api_rejects_completion_when_engine_requires_clinical_review():
    _add_screening("SYNTH-SCR-900016", patient_id=F01_PATIENT, rule_id=VISION_RULE, status="complete", performed=date(2026, 11, 12))
    get_cached_index().history_by_patient[F01_PATIENT]["ifhas"] = "partial"
    before = copy.deepcopy(_gap(F01_VISION_GAP))
    resp = client.post(f"/api/v1/care-gaps/{F01_VISION_GAP}/follow-ups", json=_close_body("SYNTH-SCR-900016"))
    assert resp.status_code == 422 and "evaluation_requires_clinical_review" in resp.json()["detail"]
    _assert_gap_untouched(F01_VISION_GAP, before)


def test_api_valid_completion_then_retrieval_preserves_historical_evaluation():
    _add_screening("SYNTH-SCR-900013", patient_id=F01_PATIENT, rule_id=VISION_RULE, status="complete", performed=date(2026, 11, 12))
    before = client.get(f"/api/v1/patients/{F01_PATIENT}/evaluations").json()
    vision_before = next(e for e in before["evaluations"] if e["rule_id"] == VISION_RULE)
    assert vision_before["evaluation_status"] == "due"
    assert vision_before["superseded_by_completion"] is False

    ok = client.post(f"/api/v1/care-gaps/{F01_VISION_GAP}/follow-ups", json=_close_body("SYNTH-SCR-900013"))
    assert ok.status_code == 201
    assert ok.json()["outcome_status"] == "completed"
    gap = _gap(F01_VISION_GAP)
    assert gap["status"] == "closed_completed"
    assert gap["closed_by_ifhas_screening_id"] == "SYNTH-SCR-900013"
    assert gap["closed_by_well_child_visit_id"] is None and gap["closed_by_referral_id"] is None
    assert gap["closed_date"] == REF_DATE

    after = client.get(f"/api/v1/patients/{F01_PATIENT}/evaluations").json()
    assert after["evaluation_run_id"] == before["evaluation_run_id"]
    assert after["reference_date"] == before["reference_date"]
    vision_after = next(e for e in after["evaluations"] if e["rule_id"] == VISION_RULE)
    # Historical evaluation is unchanged except for the explicit supersession marker.
    unchanged = {k: v for k, v in vision_after.items() if not k.startswith("superseded_by")}
    assert unchanged == {k: v for k, v in vision_before.items() if not k.startswith("superseded_by")}
    assert vision_after["evaluation_status"] == "due"
    assert vision_after["superseded_by_completion"] is True
    assert vision_after["superseded_by_care_gap_id"] == F01_VISION_GAP
    assert vision_after["evaluation_id"] == gap["evaluation_id"]
    gap_after = next(g for g in after["care_gaps"] if g["care_gap_id"] == F01_VISION_GAP)
    assert gap_after["status"] == "closed_completed"
    others = [e for e in after["evaluations"] if e["rule_id"] != VISION_RULE]
    assert not any(e["superseded_by_completion"] for e in others)

    # A fresh (non-persisted) evaluation on current records reports the rule completed.
    fresh = client.post("/api/v1/evaluations", json={"patient_id": F01_PATIENT, "look_ahead_days": 31}).json()
    fresh_vision = next(e for e in fresh["evaluations"] if e["rule_id"] == VISION_RULE)
    assert fresh_vision["evaluation_status"] == "completed"
    assert _evaluation_status(F01_PATIENT, VISION_RULE) == "due"


def test_api_duplicate_completion_request_is_rejected():
    _add_screening("SYNTH-SCR-900017", patient_id=F01_PATIENT, rule_id=VISION_RULE, status="complete", performed=date(2026, 11, 12))
    ok = client.post(f"/api/v1/care-gaps/{F01_VISION_GAP}/follow-ups", json=_close_body("SYNTH-SCR-900017"))
    assert ok.status_code == 201
    closed_snapshot = copy.deepcopy(_gap(F01_VISION_GAP))
    dup = client.post(f"/api/v1/care-gaps/{F01_VISION_GAP}/follow-ups", json=_close_body("SYNTH-SCR-900017"))
    assert dup.status_code == 422 and "care_gap_not_open" in dup.json()["detail"]
    assert _gap(F01_VISION_GAP) == closed_snapshot
    assert [e["follow_up_id"] for e in get_memory_follow_up_events(F01_VISION_GAP)] == [ok.json()["follow_up_id"]]


def test_api_referral_evidence_path():
    gap = _gap(REFERRAL_GAP)
    assert gap["gap_type"] == "referral_not_initiated" and gap["subject_referral_id"] == REFERRAL_ID
    before = copy.deepcopy(gap)

    pending = client.post(f"/api/v1/care-gaps/{REFERRAL_GAP}/follow-ups", json=_close_body(REFERRAL_ID))
    assert pending.status_code == 422 and "evidence_not_completed" in pending.json()["detail"]
    other = client.post(f"/api/v1/care-gaps/{REFERRAL_GAP}/follow-ups", json=_close_body(OTHER_PATIENT_REFERRAL))
    assert other.status_code == 422 and "evidence_patient_mismatch" in other.json()["detail"]
    assert client.patch(f"/api/v1/referrals/{REFERRAL_ID}", json={"status": "initiated", "initiated_date": "2026-09-20", "recorded_by": "t"}).status_code == 200
    initiated = client.post(f"/api/v1/care-gaps/{REFERRAL_GAP}/follow-ups", json=_close_body(REFERRAL_ID))
    assert initiated.status_code == 422 and "evidence_not_completed" in initiated.json()["detail"]
    _assert_gap_untouched(REFERRAL_GAP, before)

    assert client.patch(f"/api/v1/referrals/{REFERRAL_ID}", json={"status": "completed", "completed_date": "2026-10-01", "recorded_by": "t"}).status_code == 200
    ok = client.post(f"/api/v1/care-gaps/{REFERRAL_GAP}/follow-ups", json=_close_body(REFERRAL_ID))
    assert ok.status_code == 201
    assert _gap(REFERRAL_GAP)["closed_by_referral_id"] == REFERRAL_ID


def test_api_cancelled_and_declined_referrals_cannot_close_gap():
    for status in ("cancelled", "declined"):
        get_cached_index.cache_clear()
        get_cached_dataset.cache_clear()
        before = copy.deepcopy(_gap(REFERRAL_GAP))
        assert client.patch(f"/api/v1/referrals/{REFERRAL_ID}", json={"status": status, "recorded_by": "t"}).status_code == 200
        resp = client.post(f"/api/v1/care-gaps/{REFERRAL_GAP}/follow-ups", json=_close_body(REFERRAL_ID))
        assert resp.status_code == 422 and "evidence_not_completed" in resp.json()["detail"]
        _assert_gap_untouched(REFERRAL_GAP, before)


def test_api_visit_evidence_path():
    before = copy.deepcopy(_gap(VISIT_GAP))
    for ref, reason in (
        (NOT_ATTENDED_VISIT, "evidence_not_completed"),
        (OTHER_PATIENT_VISIT, "evidence_patient_mismatch"),
        (F01_PARTIAL_SCREENING, "evidence_patient_mismatch"),
    ):
        resp = client.post(f"/api/v1/care-gaps/{VISIT_GAP}/follow-ups", json=_close_body(ref))
        assert resp.status_code == 422 and reason in resp.json()["detail"], ref

    # Make-up attended visit after a not-attended visit: engine routes to clinical review.
    _add_visit("SYNTH-VIS-900001", patient_id=VISIT_PATIENT, rule_id=before["rule_id"], status="attended", performed=date(2026, 11, 10))
    makeup = client.post(f"/api/v1/care-gaps/{VISIT_GAP}/follow-ups", json=_close_body("SYNTH-VIS-900001"))
    assert makeup.status_code == 422 and "evaluation_requires_clinical_review" in makeup.json()["detail"]
    _assert_gap_untouched(VISIT_GAP, before)

    # Unambiguous attended visit for a due visit with no prior records: accepted.
    due_gap = _gap(VISIT_DUE_GAP)
    _add_visit("SYNTH-VIS-900002", patient_id=VISIT_DUE_PATIENT, rule_id=due_gap["rule_id"], status="attended", performed=date(2026, 11, 10))
    ok = client.post(f"/api/v1/care-gaps/{VISIT_DUE_GAP}/follow-ups", json=_close_body("SYNTH-VIS-900002"))
    assert ok.status_code == 201
    assert _gap(VISIT_DUE_GAP)["closed_by_well_child_visit_id"] == "SYNTH-VIS-900002"


def test_api_screening_cannot_close_visit_gap():
    _add_screening("SYNTH-SCR-900014", patient_id=VISIT_PATIENT, rule_id=VISION_RULE, status="complete", performed=date(2026, 11, 10))
    resp = client.post(f"/api/v1/care-gaps/{VISIT_GAP}/follow-ups", json=_close_body("SYNTH-SCR-900014"))
    assert resp.status_code == 422 and "evidence_type_mismatch" in resp.json()["detail"]


def test_generator_completed_gaps_are_flagged_as_superseding_their_evaluation():
    ds = get_cached_dataset()
    for g in (g for g in ds.care_gaps if g["status"] == "closed_completed"):
        ev = next(e for e in _all_evaluations(g["patient_id"]) if e["evaluation_id"] == g["evaluation_id"])
        assert ev["superseded_by_completion"] is True
        assert ev["superseded_by_care_gap_id"] == g["care_gap_id"]


def _all_evaluations(patient_id: str) -> list[dict]:
    return client.get(f"/api/v1/patients/{patient_id}/evaluations").json()["evaluations"]


# ---------------------------------------------------------------------------
# 3. PostgreSQL repository path (same validator and engine; SQLite with constraints stripped)
# ---------------------------------------------------------------------------

_PG_TABLES = [
    Rule, Standard, GenerationRun, EvaluationRun, Patient, HistoryAvailability, Consent,
    IfhasScreening, WellChildVisit, ComponentResult, Assessment, Referral,
    EligibilityEvaluation, EvaluationReason, CareGap, CareGapFollowUpEvent, WorkflowStatusEvent,
]


def _cols(model_cls, row: dict) -> dict:
    valid = {c.name for c in model_cls.__table__.columns if c.computed is None}
    return {k: v for k, v in row.items() if k in valid}


@pytest.fixture
def pg_session():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _attach(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        cur.execute("ATTACH DATABASE ':memory:' AS clinical")
        cur.execute("ATTACH DATABASE ':memory:' AS synthetic")
        cur.close()

    meta = MetaData()
    for model in _PG_TABLES:
        copied = model.__table__.to_metadata(meta)
        copied.constraints = {
            c for c in copied.constraints if not isinstance(c, (CheckConstraint, ForeignKeyConstraint))
        }
        copied.foreign_keys.clear()
        for col in copied.columns:
            col.foreign_keys.clear()
            col.server_default = None
            col.computed = None
            if not col.primary_key:
                col.nullable = True
            if isinstance(col.type, (JSONB, ARRAY)):
                col.type = JSON()
    meta.create_all(bind=engine)

    ds = get_cached_dataset()
    pids = {F01_PATIENT, REFERRAL_PATIENT, VISIT_PATIENT, "SYNTH-PAT-000029"}
    with Session(engine) as session:
        for r in get_cached_bundle().rules:
            row = {**_cols(Rule, r), "standard_id": 1, "load_id": 1, "is_authoritative": r["is_authoritative"]}
            session.execute(meta.tables["clinical.rule"].insert().values(**row))
        session.add(GenerationRun(**_cols(GenerationRun, ds.generation_run)))
        session.add(EvaluationRun(**_cols(EvaluationRun, ds.evaluation_run)))
        for model, rows in (
            (Patient, ds.patients),
            (HistoryAvailability, ds.history_availabilities),
            (Consent, ds.consents),
            (IfhasScreening, ds.ifhas_screenings),
            (WellChildVisit, ds.well_child_visits),
            (ComponentResult, ds.component_results),
            (Assessment, ds.assessments),
            (Referral, ds.referrals),
            (EligibilityEvaluation, ds.eligibility_evaluations),
            (CareGap, ds.care_gaps),
        ):
            for row in rows:
                if row["patient_id"] in pids:
                    session.add(model(**_cols(model, row)))
        session.commit()
        yield session


def _pg_gap(session: Session, gap_id: str) -> CareGap:
    session.expire_all()
    return session.scalars(select(CareGap).where(CareGap.care_gap_id == gap_id)).one()


def _pg_eval(session: Session, patient_id: str, rule_id: str) -> EligibilityEvaluation:
    return session.scalars(
        select(EligibilityEvaluation).where(
            EligibilityEvaluation.patient_id == patient_id, EligibilityEvaluation.rule_id == rule_id
        )
    ).one()


def _pg_event_count(session: Session, gap_id: str) -> int:
    return len(session.scalars(select(CareGapFollowUpEvent).where(CareGapFollowUpEvent.care_gap_id == gap_id)).all())


def _pg_add_screening(session: Session, screening_id: str, rule_id: str, performed: date) -> None:
    session.add(
        IfhasScreening(
            screening_id=screening_id,
            run_id=get_cached_dataset().generation_run["run_id"],
            patient_id=F01_PATIENT,
            is_synthetic=True,
            profile_id="SYNTH-FSP-000001",
            rule_id=rule_id,
            rule_version=_rule(rule_id)["rule_version"],
            performed_date=performed,
            completion_status="complete",
        )
    )
    session.commit()


def test_pg_repo_rejects_f01_reproduction_without_side_effects(pg_session):
    repo = PostgresFollowUpRepository(pg_session)
    assert _pg_eval(pg_session, F01_PATIENT, VISION_RULE).evaluation_status == "due"
    with pytest.raises(HTTPException) as exc:
        repo.create_follow_up(F01_VISION_GAP, FollowUpCreateIn(**_close_body(F01_PARTIAL_SCREENING)))
    assert exc.value.status_code == 422
    assert "evidence_rule_mismatch" in exc.value.detail
    gap = _pg_gap(pg_session, F01_VISION_GAP)
    assert gap.status == "open" and gap.closed_date is None
    assert gap.closed_by_ifhas_screening_id is None
    assert _pg_event_count(pg_session, F01_VISION_GAP) == 0
    assert _pg_eval(pg_session, F01_PATIENT, VISION_RULE).evaluation_status == "due"


@pytest.mark.parametrize(
    ("gap_id", "evidence_ref", "reason"),
    [
        (F01_VISION_GAP, "SYNTH-XYZ-000001", "evidence_not_found"),
        (PARTIAL_GAP, F01_PARTIAL_SCREENING, "evidence_not_completed"),  # partial only
        (REFERRAL_GAP, REFERRAL_ID, "evidence_not_completed"),  # pending referral
        (REFERRAL_GAP, OTHER_PATIENT_REFERRAL, "evidence_patient_mismatch"),
        (VISIT_GAP, NOT_ATTENDED_VISIT, "evidence_not_completed"),
        (VISIT_GAP, OTHER_PATIENT_VISIT, "evidence_not_found"),  # patient not seeded in subset
    ],
)
def test_pg_repo_rejects_invalid_evidence(pg_session, gap_id, evidence_ref, reason):
    repo = PostgresFollowUpRepository(pg_session)
    with pytest.raises(HTTPException) as exc:
        repo.create_follow_up(gap_id, FollowUpCreateIn(**_close_body(evidence_ref)))
    assert exc.value.status_code == 422 and reason in exc.value.detail
    assert _pg_gap(pg_session, gap_id).status == "open"
    assert _pg_event_count(pg_session, gap_id) == 0


def test_pg_repo_rejects_partial_plus_complete_as_clinical_review(pg_session):
    _pg_add_screening(pg_session, "SYNTH-SCR-900021", MAJOR_RULE, date(2026, 11, 12))
    repo = PostgresFollowUpRepository(pg_session)
    with pytest.raises(HTTPException) as exc:
        repo.create_follow_up(PARTIAL_GAP, FollowUpCreateIn(**_close_body("SYNTH-SCR-900021")))
    assert exc.value.status_code == 422
    assert "evaluation_requires_clinical_review" in exc.value.detail
    gap = _pg_gap(pg_session, PARTIAL_GAP)
    assert gap.status == "open" and gap.closed_by_ifhas_screening_id is None
    assert _pg_event_count(pg_session, PARTIAL_GAP) == 0


def test_pg_repo_valid_completion_duplicate_and_historical_evaluation(pg_session):
    _pg_add_screening(pg_session, "SYNTH-SCR-900020", VISION_RULE, date(2026, 11, 12))
    ev_row = _pg_eval(pg_session, F01_PATIENT, VISION_RULE)
    ev_before = (ev_row.evaluation_id, ev_row.evaluation_status, ev_row.evaluated_at, ev_row.next_due_date)
    read_repo = PostgresReadRepository(pg_session)
    api_before = next(e for e in read_repo.get_patient_evaluations(F01_PATIENT).evaluations if e.rule_id == VISION_RULE)
    assert api_before.superseded_by_completion is False

    repo = PostgresFollowUpRepository(pg_session)
    out = repo.create_follow_up(F01_VISION_GAP, FollowUpCreateIn(**_close_body("SYNTH-SCR-900020")))
    assert out.outcome_status == "completed"
    gap = _pg_gap(pg_session, F01_VISION_GAP)
    assert gap.status == "closed_completed"
    assert gap.closed_by_ifhas_screening_id == "SYNTH-SCR-900020"
    assert gap.closed_date == REF_DATE

    with pytest.raises(HTTPException) as exc:
        repo.create_follow_up(F01_VISION_GAP, FollowUpCreateIn(**_close_body("SYNTH-SCR-900020")))
    assert exc.value.status_code == 422 and "care_gap_not_open" in exc.value.detail
    assert _pg_event_count(pg_session, F01_VISION_GAP) == 1
    assert _pg_gap(pg_session, F01_VISION_GAP).closed_by_ifhas_screening_id == "SYNTH-SCR-900020"

    ev_row = _pg_eval(pg_session, F01_PATIENT, VISION_RULE)
    assert (ev_row.evaluation_id, ev_row.evaluation_status, ev_row.evaluated_at, ev_row.next_due_date) == ev_before
    evals = read_repo.get_patient_evaluations(F01_PATIENT)
    api_after = next(e for e in evals.evaluations if e.rule_id == VISION_RULE)
    assert api_after.evaluation_status == "due"
    assert api_after.superseded_by_completion is True
    assert api_after.superseded_by_care_gap_id == F01_VISION_GAP
    assert next(g for g in evals.care_gaps if g.care_gap_id == F01_VISION_GAP).status == "closed_completed"
