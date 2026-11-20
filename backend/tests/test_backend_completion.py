"""Regression tests for the backend completion fixes (memory mode, no database).

- F-11: every reason code the engine can emit is in the versioned YAML vocabulary.
- F-12: reason text and input snapshot are recorded at evaluation time, not rebuilt at read.
- F-18: ad-hoc recomputations never reuse persisted-looking ids.
- F-10: dashboard person counts are per person and mutually exclusive.
- Duplicate requests cannot create duplicate appointments, referrals or follow-ups.

The PostgreSQL counterparts live in `test_live_backend_completion.py`.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from app.main import app
from app.repositories.followup_repo import reset_memory_writes
from app.repositories.read_repo import get_cached_dataset, get_cached_index
from app.services.clinical_loader.parse import default_rules_dir

client = TestClient(app)
BACKEND = Path(__file__).resolve().parents[1]
WHO = "coordinator.test"
PID, GAP = "SYNTH-PAT-000001", "SYNTH-GAP-000001"


@pytest.fixture(autouse=True)
def _fresh_memory():
    get_cached_index.cache_clear()
    get_cached_dataset.cache_clear()
    reset_memory_writes()
    yield
    reset_memory_writes()
    get_cached_index.cache_clear()
    get_cached_dataset.cache_clear()


# --- F-11 ------------------------------------------------------------------------------------


def test_every_engine_reason_code_is_in_the_yaml_vocabulary():
    src = (BACKEND / "app" / "services" / "evaluation" / "engine.py").read_text(encoding="utf-8")
    emitted = set(re.findall(r'reason_code="([a-z_]+)"', src)) | set(
        re.findall(r'rc = "([a-z_]+)"', src)
    ) | {"rule_reported_not_verified"}
    vocab = set(yaml.safe_load((default_rules_dir() / "common" / "status_definitions.yaml").read_text())[
        "reason_codes"])
    assert {"referral_cancelled", "referral_status_unresolved", "missing_completion_evidence"} <= emitted
    assert emitted - vocab == set()


def test_new_reason_codes_have_explanation_text():
    from app.services.explanation.service import REASON_DESCRIPTIONS

    for code in ("referral_cancelled", "referral_status_unresolved", "missing_completion_evidence"):
        assert code in REASON_DESCRIPTIONS


# --- F-12 ------------------------------------------------------------------------------------


def _evaluations(pid: str = PID) -> list[dict]:
    resp = client.get(f"/api/v1/patients/{pid}/evaluations")
    assert resp.status_code == 200
    return resp.json()["evaluations"]


def test_evaluations_expose_engine_detail_and_recorded_snapshot():
    evals = _evaluations()
    assert all(e["input_snapshot_basis"] == "recorded_at_evaluation" for e in evals)
    unresolved = next(e for e in evals if e["reason_code"] == "rule_unresolved")
    # The engine's own detail (names the rule), not the generic per-code template.
    assert unresolved["rule_id"] in unresolved["reason_detail"]
    assert unresolved["reasons"][0]["reason_detail"] == unresolved["reason_detail"]
    rows = [e for e in get_cached_dataset().eligibility_evaluations if e["patient_id"] == PID]
    assert all(r["input_snapshot"] and r["reason_detail"] for r in rows)


def test_snapshot_is_not_rewritten_by_later_record_changes():
    before = {e["evaluation_id"]: e["input_snapshot"] for e in _evaluations()}
    idx = get_cached_index()
    # A later screening-participation refusal must not change what past evaluations were based on.
    for c in list(idx.consents_by_patient[PID]):
        idx.consents_by_patient[PID].append({**c, "consent_id": "SYNTH-CNS-990001",
                                             "consent_type": "screening_participation", "state": "refused",
                                             "recorded_at": datetime(2026, 11, 18, tzinfo=timezone.utc)})
        break
    assert {e["evaluation_id"]: e["input_snapshot"] for e in _evaluations()} == before


def test_recorded_snapshot_is_de_identified():
    snap = _evaluations()[0]["input_snapshot"]
    assert set(snap) == {"pathway", "age_years", "age_months", "sex", "thiqa_member", "ever_smoked",
                         "history_status", "screening_consent_state", "has_prior_screening_or_visit",
                         "has_referral"}


# --- F-18 ------------------------------------------------------------------------------------


def test_recomputed_evaluations_use_namespaced_ephemeral_ids():
    stored_ids = {e["evaluation_id"] for e in get_cached_dataset().eligibility_evaluations}
    stored_gaps = {g["care_gap_id"] for g in get_cached_dataset().care_gaps}
    seen: set[str] = set()
    for pid in ("SYNTH-PAT-000001", "SYNTH-PAT-000201"):
        body = client.post("/api/v1/evaluations", json={"patient_id": pid, "look_ahead_days": 90}).json()
        assert body["is_persisted"] is False
        ids = [e["evaluation_id"] for e in body["evaluations"]] + [g["care_gap_id"] for g in body["care_gaps"]]
        assert all(i.startswith(f"EPHEMERAL-{pid}-") for i in ids)
        assert not (set(ids) & (stored_ids | stored_gaps | seen))
        seen |= set(ids)
        assert all(g["evaluation_id"].startswith(f"EPHEMERAL-{pid}-EVL-") for g in body["care_gaps"])
        assert all(e["input_snapshot_basis"] == "recorded_at_evaluation" for e in body["evaluations"])
        if body["care_gaps"]:
            assert client.get(f"/api/v1/care-gaps/{body['care_gaps'][0]['care_gap_id']}").status_code == 404
    default = client.post("/api/v1/evaluations", json={"patient_id": PID, "look_ahead_days": 30}).json()
    assert default["is_persisted"] is True
    assert {e["evaluation_id"] for e in default["evaluations"]} <= stored_ids


# --- F-10 ------------------------------------------------------------------------------------


def test_dashboard_person_counts_are_exclusive_and_per_person():
    d = client.get("/api/v1/dashboard/summary").json()
    total = d["total_patients"]
    assert sum(d["patient_status_counts"].values()) == total
    assert list(d["patient_status_counts"]) and set(d["patient_status_counts"]) <= set(
        d["patient_status_precedence"]) | {"no_applicable_result"}
    # Rule-level review (unresolved rules) no longer inflates "people needing review".
    assert 0 < d["review_flagged_patients_count"] < total
    assert d["rule_review_patients_count"] <= total
    ifhas, wcv = d["pathway_breakdown"]["ifhas"], d["pathway_breakdown"]["well_child"]
    # Programme eligibility is in-band only: children are not counted as IFHAS-eligible adults,
    # and adults are not counted in Well-Child.
    assert ifhas["programme_eligible_patients"] <= d["n_adults"]
    assert wcv["programme_eligible_patients"] <= d["n_children"]
    assert "eligible_or_due_patients" not in ifhas
    # Evaluation-level counts remain available and clearly separate.
    assert sum(d["evaluation_status_counts"].values()) > total


def test_population_insight_reports_record_and_rule_review_separately():
    facts = client.get("/api/v1/insights/population").json()
    assert facts["facts"]["rule_review_patients_count"] >= facts["facts"]["review_flagged_patients_count"]
    assert "awaiting clinical review" in facts["summary_text"]


# --- duplicate requests --------------------------------------------------------------------


def _apt_body(**kw):
    return {"patient_id": PID, "profile_id": "SYNTH-FSP-000001", "care_gap_id": GAP,
            "appointment_type": "ifhas_screening", "scheduled_datetime": "2026-12-01T09:00:00+00:00",
            "recorded_by": WHO, **kw}


def test_duplicate_appointment_is_rejected_with_existing_id():
    first = client.post("/api/v1/appointments", json=_apt_body())
    assert first.status_code == 201
    dup = client.post("/api/v1/appointments", json=_apt_body())
    assert dup.status_code == 409
    body = dup.json()
    assert body["detail"]["code"] == "duplicate_request"
    assert body["detail"]["existing_id"] == first.json()["appointment_id"]
    assert body["error"]["message"].startswith("An active appointment already exists")
    # One appointment, one history entry, one gap event.
    apt_id = first.json()["appointment_id"]
    assert len(client.get(f"/api/v1/appointments/{apt_id}/history").json()["items"]) == 1
    assert client.get(f"/api/v1/care-gaps/{GAP}/follow-ups").json()["total"] == 1
    # A different time, or the same slot after cancellation, is a new appointment.
    assert client.post("/api/v1/appointments", json=_apt_body(scheduled_datetime="2026-12-02T09:00:00+00:00")).status_code == 201
    client.patch(f"/api/v1/appointments/{apt_id}", json={"status": "cancelled_by_patient", "recorded_by": WHO})
    assert client.post("/api/v1/appointments", json=_apt_body()).status_code == 201


def test_duplicate_active_referral_is_rejected():
    body = {"patient_id": "SYNTH-PAT-000008", "ifhas_screening_id": "SYNTH-SCR-000002",
            "trigger_rule_id": "IFHAS-PKG-MAJOR-40-64", "trigger_rule_version": "1.0.0",
            "referral_target": "diagnostics", "trigger_date": "2026-11-16", "recorded_by": WHO}
    first = client.post("/api/v1/referrals", json=body)
    assert first.status_code == 201, first.text
    dup = client.post("/api/v1/referrals", json=body)
    assert dup.status_code == 409 and dup.json()["detail"]["existing_id"] == first.json()["referral_id"]
    client.patch(f"/api/v1/referrals/{first.json()['referral_id']}", json={"status": "declined", "recorded_by": WHO})
    assert client.post("/api/v1/referrals", json=body).status_code == 201


def test_resubmitted_follow_up_is_rejected_but_distinct_events_are_kept():
    note = {"event_type": "note_recorded", "recorded_by": WHO, "note": "Called, no answer."}
    first = client.post(f"/api/v1/care-gaps/{GAP}/follow-ups", json=note)
    assert first.status_code == 201
    dup = client.post(f"/api/v1/care-gaps/{GAP}/follow-ups", json=note)
    assert dup.status_code == 409 and dup.json()["detail"]["existing_id"] == first.json()["follow_up_id"]
    assert client.post(f"/api/v1/care-gaps/{GAP}/follow-ups", json={**note, "note": "Left voicemail."}).status_code == 201

    outreach = {"event_type": "outreach_attempted", "recorded_by": WHO}
    assert client.post(f"/api/v1/care-gaps/{GAP}/follow-ups", json=outreach).status_code == 201
    assert client.post(f"/api/v1/care-gaps/{GAP}/follow-ups", json=outreach).status_code == 409
    assert client.get(f"/api/v1/care-gaps/{GAP}/follow-ups").json()["total"] == 3


def test_concurrent_duplicate_appointments_create_one_record():
    from concurrent.futures import ThreadPoolExecutor

    body = _apt_body(scheduled_datetime="2026-12-05T09:00:00+00:00")
    with ThreadPoolExecutor(max_workers=6) as pool:
        codes = sorted(pool.map(lambda _: client.post("/api/v1/appointments", json=body).status_code, range(6)))
    assert codes == [201, 409, 409, 409, 409, 409]


def test_memory_ai_audit_is_reported_as_non_durable():
    assert client.get("/api/v1/ai/audit").json()["durable"] is False
