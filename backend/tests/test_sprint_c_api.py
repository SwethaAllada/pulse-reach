"""Tests for Sprint C `/api/v1/*` endpoints and enhancements (T-04 through T-08)."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


# ---------------------------------------------------------------------------
# T-04: Person history & consents
# ---------------------------------------------------------------------------


def test_patient_history_adult_and_missing_history():
    # Adult with available IFHAS history
    resp = client.get("/api/v1/patients/SYNTH-PAT-000001/history")
    assert resp.status_code == 200
    body = resp.json()
    assert body["is_synthetic"] is True
    assert body["patient_id"] == "SYNTH-PAT-000001"
    assert body["guardians"] == []
    assert any(h["pathway"] == "ifhas" and h["history_status"] == "available" for h in body["history_availability"])
    assert isinstance(body["ifhas_screenings"], list)
    assert isinstance(body["well_child_visits"], list)
    assert isinstance(body["component_results"], list)
    assert isinstance(body["assessments"], list)

    # Adult with missing history -> explicitly not_available / unknown, never "not screened"
    resp_missing = client.get("/api/v1/patients/SYNTH-PAT-000007/history")
    assert resp_missing.status_code == 200
    m_body = resp_missing.json()
    ifhas_avail = [h for h in m_body["history_availability"] if h["pathway"] == "ifhas"]
    assert len(ifhas_avail) == 1
    assert ifhas_avail[0]["history_status"] == "not_available"
    assert m_body["ifhas_screenings"] == []

    # 404 for unknown patient
    assert client.get("/api/v1/patients/SYNTH-PAT-999999/history").status_code == 404


def test_patient_history_child_includes_guardian_and_wcv():
    resp = client.get("/api/v1/patients/SYNTH-PAT-000013/history")
    assert resp.status_code == 200
    body = resp.json()
    assert body["patient_id"] == "SYNTH-PAT-000013"
    assert len(body["guardians"]) >= 1
    assert body["guardians"][0]["guardian_id"].startswith("SYNTH-GDN-")
    assert len(body["well_child_visits"]) >= 1
    assert body["well_child_visits"][0]["visit_id"].startswith("SYNTH-VIS-")
    assert len(body["assessments"]) >= 1
    assert body["assessments"][0]["assessment_id"].startswith("SYNTH-ASM-")


def test_patient_consents_current_state_and_history():
    # Patient with granted contact consent
    resp_ok = client.get("/api/v1/patients/SYNTH-PAT-000001/consents")
    assert resp_ok.status_code == 200
    b_ok = resp_ok.json()
    assert b_ok["is_synthetic"] is True
    assert b_ok["patient_id"] == "SYNTH-PAT-000001"
    assert len(b_ok["current_states"]) >= 1
    assert any(c["consent_type"] == "contact" and c["state"] == "granted" for c in b_ok["current_states"])
    assert len(b_ok["history"]) >= 1

    # Patient with withdrawn contact consent -> distinct from absent/refused/granted
    resp_wd = client.get("/api/v1/patients/SYNTH-PAT-000021/consents")
    assert resp_wd.status_code == 200
    b_wd = resp_wd.json()
    contact_states = [c for c in b_wd["current_states"] if c["consent_type"] == "contact"]
    assert len(contact_states) == 1
    assert contact_states[0]["state"] == "withdrawn"

    # 404 for unknown patient
    assert client.get("/api/v1/patients/SYNTH-PAT-999999/consents").status_code == 404


# ---------------------------------------------------------------------------
# T-05: Complete evaluation evidence trace
# ---------------------------------------------------------------------------


def test_evaluations_include_complete_evidence_trace_without_pii():
    resp = client.get("/api/v1/patients/SYNTH-PAT-000001/evaluations")
    assert resp.status_code == 200
    body = resp.json()
    by_rule = {e["rule_id"]: e for e in body["evaluations"]}
    mammo = by_rule["IFHAS-PKG-MAMMOGRAPHY-40-75"]
    assert mammo["rule_version"]
    assert mammo["source_name"]
    assert mammo["source_reference"]
    assert mammo["is_authoritative"] is True
    assert mammo["requires_clinical_review"] is False
    assert mammo["engine_version"]
    assert mammo["look_ahead_days"] == 30
    assert mammo["reason_detail"]

    snap = mammo["input_snapshot"]
    assert snap["history_status"] == "available"
    assert "age_years" in snap
    for pii_key in ("given_name", "family_name", "emirates_id_synthetic", "phone_synthetic", "email_synthetic"):
        assert pii_key not in snap


def test_post_evaluations_includes_evidence_trace_with_custom_look_ahead():
    resp = client.post(
        "/api/v1/evaluations",
        json={"patient_id": "SYNTH-PAT-000018", "look_ahead_days": 120},
    )
    assert resp.status_code == 200
    by_rule = {e["rule_id"]: e for e in resp.json()["evaluations"]}
    wcv18 = by_rule["WCV-VISIT-18M"]
    assert wcv18["evaluation_status"] == "upcoming"
    assert wcv18["look_ahead_days"] == 120
    assert wcv18["engine_version"]
    assert wcv18["source_reference"]
    assert wcv18["reason_detail"]
    assert "age_months" in wcv18["input_snapshot"]


# ---------------------------------------------------------------------------
# T-06: People search, sorting, filters, and per-person roll-up
# ---------------------------------------------------------------------------


def test_patients_search_sort_filters_and_unknown_param_rejection():
    # Search by synthetic ID
    by_id = client.get("/api/v1/patients?q=SYNTH-PAT-000001")
    assert by_id.status_code == 200
    assert by_id.json()["total"] == 1
    p1 = by_id.json()["items"][0]
    assert p1["patient_id"] == "SYNTH-PAT-000001"
    assert "open_care_gaps_count" in p1
    assert "evaluation_summary" in p1
    assert isinstance(p1["evaluation_summary"], dict)

    # Search by synthetic family/given name
    by_name = client.get(f"/api/v1/patients?q={p1['given_name']}")
    assert by_name.status_code == 200
    assert any(it["patient_id"] == "SYNTH-PAT-000001" for it in by_name.json()["items"])

    # Filter by evaluation_status & has_open_care_gaps
    filtered = client.get(
        "/api/v1/patients?evaluation_status=due&has_open_care_gaps=true&limit=10"
    )
    assert filtered.status_code == 200
    f_body = filtered.json()
    assert f_body["total"] > 0
    assert all(it["open_care_gaps_count"] > 0 for it in f_body["items"])
    assert all(it["evaluation_summary"].get("due", 0) > 0 for it in f_body["items"])

    # Filter by history_status=not_available
    missing_h = client.get("/api/v1/patients?history_status=not_available&limit=10")
    assert missing_h.status_code == 200
    assert missing_h.json()["total"] > 0
    assert all(
        "not_available" in it["history_by_pathway"].values()
        for it in missing_h.json()["items"]
    )

    # Filter by age_band=child
    children = client.get("/api/v1/patients?age_band=child&limit=10")
    assert children.status_code == 200
    assert children.json()["total"] > 0

    # Stable pagination across pages when sorting by open_gaps desc
    p_page1 = client.get("/api/v1/patients?sort_by=open_gaps&sort_dir=desc&limit=5&offset=0").json()
    p_page2 = client.get("/api/v1/patients?sort_by=open_gaps&sort_dir=desc&limit=5&offset=5").json()
    ids1 = [it["patient_id"] for it in p_page1["items"]]
    ids2 = [it["patient_id"] for it in p_page2["items"]]
    assert len(set(ids1) & set(ids2)) == 0
    gaps_seq = [it["open_care_gaps_count"] for it in p_page1["items"] + p_page2["items"]]
    assert gaps_seq == sorted(gaps_seq, reverse=True)

    # Reject unsupported query parameters -> 422
    assert client.get("/api/v1/patients?unknown_param=123").status_code == 422
