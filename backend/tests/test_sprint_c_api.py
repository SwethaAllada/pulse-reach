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
