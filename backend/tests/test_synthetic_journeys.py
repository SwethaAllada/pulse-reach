"""Tests for T-10: Deterministic synthetic journey archetypes."""

from app.services.synthetic_generator import generate_synthetic_dataset


def test_synthetic_dataset_includes_required_journey_archetypes():
    ds = generate_synthetic_dataset(seed=20261116, total_patients=550)

    # 1. >= 5 people with follow-up in progress (granted contact consent + appointment/outreach)
    granted_contact_pids = {
        c["patient_id"]
        for c in ds.consents
        if c["consent_type"] == "contact" and c["state"] == "granted"
    }
    in_progress_pids = (
        {a["patient_id"] for a in ds.appointments}
        | {o["patient_id"] for o in ds.outreach_events if o["delivery_status"] != "suppressed"}
    ) & granted_contact_pids
    assert len(in_progress_pids) >= 5

    # 2. >= 5 people with documented completion and a gap closed by evidence
    closed_completed_pids = {
        g["patient_id"] for g in ds.care_gaps if g["status"] == "closed_completed"
    }
    assert len(closed_completed_pids) >= 5

    # 3. >= 2 declined/cancelled referral scenarios
    declined_or_cancelled_refs = [
        r for r in ds.referrals if r["status"] in ("declined", "cancelled")
    ]
    assert len(declined_or_cancelled_refs) >= 2

    # 4. >= 3 component-result examples
    assert len(ds.component_results) >= 3

    # 5. >= 30 contactable people with open gaps
    open_gap_pids = {g["patient_id"] for g in ds.care_gaps if g["status"] == "open"}
    contactable_open_pids = open_gap_pids & granted_contact_pids
    assert len(contactable_open_pids) >= 30

    # Reproducibility check
    ds2 = generate_synthetic_dataset(seed=20261116, total_patients=550)
    assert len(ds.care_gaps) == len(ds2.care_gaps)
    assert len(ds.appointments) == len(ds2.appointments)
    assert len(ds.component_results) == len(ds2.component_results)


def test_no_fabricated_priority_score_or_model_version():
    ds = generate_synthetic_dataset(seed=20261116, total_patients=60)
    assert all(g["priority_score"] is None for g in ds.care_gaps)
    assert all(g["scored_by_model_version"] is None for g in ds.care_gaps)
    open_gaps = [g for g in ds.care_gaps if g["status"] == "open"]
    assert open_gaps
    assert all(
        g["scoring_suppressed_reason"] in ("ai_consent_refused", "model_not_implemented")
        for g in open_gaps
    )
    assert any(g["scoring_suppressed_reason"] == "model_not_implemented" for g in open_gaps)
