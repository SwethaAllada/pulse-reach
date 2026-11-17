"""Tests for the PulseReach `/api/v1/*` FastAPI endpoints (`app.api.v1`).

Covers Workstream D1 & D2 of `pulse-reach-backend-execution-plan.md`:
- `GET /api/v1/dashboard/summary`
- `GET /api/v1/patients`
- `GET /api/v1/patients/{patient_id}`
- `GET /api/v1/patients/{patient_id}/evaluations`
- `POST /api/v1/evaluations`
- `GET /api/v1/rules`
- `GET /api/v1/rules/{rule_id}`
- `GET /api/v1/care-gaps`
- `GET /api/v1/facilities`
- `POST /api/v1/explanations`
- `POST /api/v1/outreach/preview`
"""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_dashboard_summary():
    resp = client.get("/api/v1/dashboard/summary")
    assert resp.status_code == 200
    body = resp.json()
    assert body["is_synthetic"] is True
    assert body["run_id"] == "SYNTH-RUN-0001"
    assert body["total_patients"] >= 500
    assert body["rules_summary"]["total_rules"] == 54
    assert body["rules_summary"]["authoritative_rules"] == 47
    assert body["rules_summary"]["clinical_review_status"] == "not_reviewed"
    assert "due" in body["evaluation_status_counts"]
    assert "unknown" in body["evaluation_status_counts"]
    assert "requires_clinical_review" in body["evaluation_status_counts"]


def test_patients_list_and_detail_and_evaluations():
    resp = client.get("/api/v1/patients?limit=20&offset=0")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 500
    assert len(body["items"]) == 20
    assert body["items"][0]["is_synthetic"] is True
    assert body["items"][0]["patient_id"].startswith("SYNTH-PAT-")

    # Detail for Scenario 1 patient
    det = client.get("/api/v1/patients/SYNTH-PAT-000001")
    assert det.status_code == 200
    p1 = det.json()
    assert p1["patient_id"] == "SYNTH-PAT-000001"
    assert p1["is_synthetic"] is True
    assert p1["history_by_pathway"]["ifhas"] == "available"

    # Evaluations for Scenario 1 patient
    evals = client.get("/api/v1/patients/SYNTH-PAT-000001/evaluations")
    assert evals.status_code == 200
    ev_body = evals.json()
    assert ev_body["patient_id"] == "SYNTH-PAT-000001"
    assert len(ev_body["evaluations"]) == 54
    by_rule = {e["rule_id"]: e for e in ev_body["evaluations"]}
    assert by_rule["IFHAS-PKG-MAMMOGRAPHY-40-75"]["evaluation_status"] == "due"

    # 404 for unknown patient
    missing = client.get("/api/v1/patients/SYNTH-PAT-999999")
    assert missing.status_code == 404


def test_post_evaluations_endpoint():
    resp = client.post(
        "/api/v1/evaluations",
        json={"patient_id": "SYNTH-PAT-000007", "look_ahead_days": 30},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["patient_id"] == "SYNTH-PAT-000007"
    by_rule = {e["rule_id"]: e for e in body["evaluations"]}
    assert by_rule["IFHAS-PKG-MAMMOGRAPHY-40-75"]["evaluation_status"] == "unknown"
    assert body["care_gaps"] == []


def test_rules_list_and_detail():
    resp = client.get("/api/v1/rules?pathway=ifhas")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 29

    # Detail for WCV-VISIT-15M (includes items and open questions)
    r_det = client.get("/api/v1/rules/WCV-VISIT-15M")
    assert r_det.status_code == 200
    r_body = r_det.json()
    assert r_body["rule_id"] == "WCV-VISIT-15M"
    assert r_body["is_authoritative"] is True
    item_codes = {it["code"]: it for it in r_body["items"]}
    assert item_codes["oral_examination"]["verification_status"] == "unresolved"
    assert item_codes["oral_examination"]["effective_authority"] is False


def test_care_gaps_and_facilities():
    gaps = client.get("/api/v1/care-gaps?status=open&limit=10")
    assert gaps.status_code == 200
    g_body = gaps.json()
    assert g_body["total"] > 0
    assert all(g["status"] == "open" for g in g_body["items"])

    facs = client.get("/api/v1/facilities?limit=10")
    assert facs.status_code == 200
    f_body = facs.json()
    assert "governance_notice" in f_body
    assert len(f_body["items"]) > 0


def test_explanations_and_outreach_preview_endpoints():
    expl = client.post(
        "/api/v1/explanations",
        json={
            "patient_id": "SYNTH-PAT-000003",
            "rule_id": "IFHAS-PKG-CERVICAL-HPV-30-65",
        },
    )
    assert expl.status_code == 200
    e_body = expl.json()
    assert e_body["evaluation_status"] == "requires_clinical_review"
    assert e_body["is_synthetic"] is True

    # Allowed outreach preview for SYNTH-PAT-000001
    prev_ok = client.post(
        "/api/v1/outreach/preview",
        json={
            "patient_id": "SYNTH-PAT-000001",
            "rule_id": "IFHAS-PKG-MAMMOGRAPHY-40-75",
            "channel": "sms",
            "language": "en",
        },
    )
    assert prev_ok.status_code == 200
    assert prev_ok.json()["allowed"] is True
    assert prev_ok.json()["simulated_only"] is True

    # Blocked outreach preview for SYNTH-PAT-000021 (withdrawn contact consent)
    prev_blocked = client.post(
        "/api/v1/outreach/preview",
        json={
            "patient_id": "SYNTH-PAT-000021",
            "rule_id": "IFHAS-PKG-MAJOR-40-64",
            "channel": "sms",
            "language": "en",
        },
    )
    assert prev_blocked.status_code == 200
    assert prev_blocked.json()["allowed"] is False
    assert prev_blocked.json()["blocked_reason"] == "contact_consent_withdrawn"


def test_post_evaluations_respects_dynamic_look_ahead_days():
    # SYNTH-PAT-000018 is 15 months old on 2026-11-16 (born 2025-08-16); 18M visit is due 2027-02-16 (92 days away)
    r30 = client.post(
        "/api/v1/evaluations",
        json={"patient_id": "SYNTH-PAT-000018", "look_ahead_days": 30},
    )
    assert r30.status_code == 200
    by_rule_30 = {e["rule_id"]: e for e in r30.json()["evaluations"]}
    assert by_rule_30["WCV-VISIT-18M"]["evaluation_status"] == "not_eligible"

    r120 = client.post(
        "/api/v1/evaluations",
        json={"patient_id": "SYNTH-PAT-000018", "look_ahead_days": 120},
    )
    assert r120.status_code == 200
    by_rule_120 = {e["rule_id"]: e for e in r120.json()["evaluations"]}
    assert by_rule_120["WCV-VISIT-18M"]["evaluation_status"] == "upcoming"


def test_facilities_serves_real_sdi_facilities_with_simulated_overlay():
    resp = client.get("/api/v1/facilities?limit=50&offset=0")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] > 100
    assert len(body["items"]) == 50
    assert all(it["capability_basis"] == "simulated_overlay_only" for it in body["items"])


def test_cors_headers_and_enum_query_validation():
    cors_resp = client.get(
        "/api/v1/dashboard/summary",
        headers={"Origin": "http://localhost:3000"},
    )
    assert cors_resp.status_code == 200
    assert cors_resp.headers.get("access-control-allow-origin") == "http://localhost:3000"

    assert client.get("/api/v1/patients?sex=invalid").status_code == 422
    assert client.get("/api/v1/rules?verification_status=bogus").status_code == 422
    assert client.get("/api/v1/care-gaps?status=bogus").status_code == 422

