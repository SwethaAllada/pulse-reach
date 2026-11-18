"""Tests for T-09: FollowUpService transition validation, write endpoints, and CORS PATCH."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.repositories.followup_repo import _MEMORY_FOLLOW_UP_EVENTS
from app.repositories.read_repo import get_cached_dataset, get_cached_index
from app.services.followup.service import FollowUpService, FollowUpValidationError

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_memory_dataset():
    yield
    _MEMORY_FOLLOW_UP_EVENTS.clear()
    get_cached_index.cache_clear()
    get_cached_dataset.cache_clear()


def test_service_appointment_transitions():
    svc = FollowUpService()
    svc.validate_appointment_transition("scheduled", "attended")
    svc.validate_appointment_transition("scheduled", "cancelled_by_patient")
    svc.validate_appointment_transition("rescheduled", "attended")

    with pytest.raises(FollowUpValidationError, match="Cannot transition appointment"):
        svc.validate_appointment_transition("attended", "scheduled")
    with pytest.raises(FollowUpValidationError, match="Cannot transition appointment"):
        svc.validate_appointment_transition("cancelled_by_patient", "attended")


def test_service_referral_transitions_and_dates():
    svc = FollowUpService()
    d0 = date(2026, 11, 1)
    d1 = date(2026, 11, 5)
    d2 = date(2026, 11, 10)

    svc.validate_referral_transition(
        "pending", "initiated", trigger_date=d0, initiated_date=d1, completed_date=None
    )
    svc.validate_referral_transition(
        "initiated", "completed", trigger_date=d0, initiated_date=d1, completed_date=d2
    )
    svc.validate_referral_transition(
        "pending", "declined", trigger_date=d0, initiated_date=None, completed_date=None
    )

    with pytest.raises(FollowUpValidationError, match="completed_date"):
        svc.validate_referral_transition(
            "initiated", "completed", trigger_date=d0, initiated_date=d1, completed_date=None
        )
    with pytest.raises(FollowUpValidationError, match="Cannot transition referral"):
        svc.validate_referral_transition(
            "declined", "completed", trigger_date=d0, initiated_date=d1, completed_date=d2
        )


def test_service_gap_completion_requires_documented_evidence():
    svc = FollowUpService()
    with pytest.raises(FollowUpValidationError, match="documented completion evidence"):
        svc.validate_gap_completion(documented_evidence=False, evidence_reference="DOC-1")
    with pytest.raises(FollowUpValidationError, match="documented completion evidence"):
        svc.validate_gap_completion(documented_evidence=True, evidence_reference="")
    svc.validate_gap_completion(documented_evidence=True, evidence_reference="SYNTH-SCR-000001")


def test_cors_allows_patch_method():
    resp = client.options(
        "/api/v1/appointments/SYNTH-APT-000001",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "PATCH",
        },
    )
    assert resp.status_code == 200
    assert "PATCH" in resp.headers.get("access-control-allow-methods", "")


def test_follow_up_appointment_and_referral_write_endpoints():
    # Find an open care gap for SYNTH-PAT-000001
    gaps = client.get("/api/v1/care-gaps?patient_id=SYNTH-PAT-000001&status=open").json()["items"]
    assert len(gaps) >= 1
    gap_id = gaps[0]["care_gap_id"]

    # 1. Scheduling an appointment does NOT close the gap
    apt_resp = client.post(
        "/api/v1/appointments",
        json={
            "patient_id": "SYNTH-PAT-000001",
            "profile_id": "SYNTH-FSP-000001",
            "care_gap_id": gap_id,
            "appointment_type": "ifhas_screening",
            "scheduled_datetime": datetime(2026, 11, 25, 10, 0, tzinfo=timezone.utc).isoformat(),
            "slot_type": "weekday",
            "booked_via": "clinician_portal",
        },
    )
    assert apt_resp.status_code == 201
    apt = apt_resp.json()
    assert apt["status"] == "scheduled"
    assert client.get(f"/api/v1/care-gaps/{gap_id}").json()["status"] == "open"

    # PATCH appointment to attended
    patch_apt = client.patch(
        f"/api/v1/appointments/{apt['appointment_id']}",
        json={"status": "attended"},
    )
    assert patch_apt.status_code == 200
    assert patch_apt.json()["status"] == "attended"

    # Invalid transition attended -> scheduled -> 422
    bad_apt = client.patch(
        f"/api/v1/appointments/{apt['appointment_id']}",
        json={"status": "scheduled"},
    )
    assert bad_apt.status_code == 422

    # 2. Outreach follow-up on withdrawn contact consent patient -> suppressed (never silently sent)
    wd_gaps = client.get("/api/v1/care-gaps?patient_id=SYNTH-PAT-000021&status=open").json()["items"]
    if wd_gaps:
        wd_gap_id = wd_gaps[0]["care_gap_id"]
        fup_suppressed = client.post(
            f"/api/v1/care-gaps/{wd_gap_id}/follow-ups",
            json={
                "event_type": "outreach_attempted",
                "recorded_by": "coordinator_ui",
                "note": "Attempted reminder",
            },
        )
        assert fup_suppressed.status_code == 201
        assert fup_suppressed.json()["event_type"] == "outreach_suppressed"
        assert fup_suppressed.json()["suppression_reason"] == "contact_consent_withdrawn"

    # 3. Attempting to close gap without documented evidence -> 422
    bad_close = client.post(
        f"/api/v1/care-gaps/{gap_id}/follow-ups",
        json={
            "event_type": "completion_documented",
            "close_gap": True,
            "documented_evidence": False,
            "recorded_by": "clinician_ui",
        },
    )
    assert bad_close.status_code == 422

    # 4. Closing gap WITH documented evidence -> 201 and gap becomes closed_completed
    good_close = client.post(
        f"/api/v1/care-gaps/{gap_id}/follow-ups",
        json={
            "event_type": "completion_documented",
            "close_gap": True,
            "documented_evidence": True,
            "evidence_reference": "SYNTH-SCR-DOC-001",
            "recorded_by": "clinician_ui",
            "note": "Completed at clinic",
        },
    )
    assert good_close.status_code == 201
    gap_after = client.get(f"/api/v1/care-gaps/{gap_id}").json()
    assert gap_after["status"] == "closed_completed"
    assert any(
        ev["follow_up_id"] == good_close.json()["follow_up_id"]
        for ev in gap_after["follow_up_events"]
    )


def test_referral_list_create_and_patch_endpoints():
    # List existing referrals
    listed = client.get("/api/v1/referrals?limit=10")
    assert listed.status_code == 200
    assert listed.json()["total"] >= 1

    # Create a new pending referral linked to an existing IFHAS screening
    hist = client.get("/api/v1/patients/SYNTH-PAT-000001/history").json()
    if hist["ifhas_screenings"]:
        scr = hist["ifhas_screenings"][0]
        created = client.post(
            "/api/v1/referrals",
            json={
                "patient_id": "SYNTH-PAT-000001",
                "ifhas_screening_id": scr["screening_id"],
                "trigger_rule_id": scr["rule_id"],
                "trigger_rule_version": scr["rule_version"],
                "referral_target": "diagnostic_mammography",
                "trigger_date": "2026-11-16",
            },
        )
        assert created.status_code == 201
        ref_id = created.json()["referral_id"]
        assert created.json()["status"] == "pending"

        # Transition pending -> initiated
        init_resp = client.patch(
            f"/api/v1/referrals/{ref_id}",
            json={"status": "initiated", "initiated_date": "2026-11-17"},
        )
        assert init_resp.status_code == 200
        assert init_resp.json()["status"] == "initiated"

        # Transition initiated -> completed requires completed_date
        bad_comp = client.patch(
            f"/api/v1/referrals/{ref_id}",
            json={"status": "completed"},
        )
        assert bad_comp.status_code == 422

        # Transition initiated -> declined
        dec_resp = client.patch(
            f"/api/v1/referrals/{ref_id}",
            json={"status": "declined"},
        )
        assert dec_resp.status_code == 200
        assert dec_resp.json()["status"] == "declined"
