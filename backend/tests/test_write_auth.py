"""Shared-key write protection (`X-PulseReach-Write-Key`, `WRITE_API_KEY`), memory mode."""

from __future__ import annotations

import logging

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core.config import settings
from app.core.write_auth import READ_ONLY_POSTS, WRITE_KEY_HEADER
from app.main import app
from app.repositories.followup_repo import reset_memory_writes
from app.repositories.read_repo import get_cached_dataset, get_cached_index

client = TestClient(app)
KEY = "demo-access-code-7f3a9c1e"
PID, GAP, RULE = "SYNTH-PAT-000001", "SYNTH-GAP-000001", "IFHAS-PKG-MAJOR-40-64"
WHO = "judge.demo"


@pytest.fixture(autouse=True)
def protected(monkeypatch):
    get_cached_index.cache_clear()
    get_cached_dataset.cache_clear()
    reset_memory_writes()
    monkeypatch.setattr(settings, "write_api_key", SecretStr(KEY))
    monkeypatch.setattr(settings, "allow_unprotected_writes", False)
    yield
    reset_memory_writes()
    get_cached_index.cache_clear()
    get_cached_dataset.cache_clear()


def _apt():
    return {"patient_id": PID, "profile_id": "SYNTH-FSP-000001", "care_gap_id": GAP,
            "appointment_type": "ifhas_screening", "scheduled_datetime": "2026-12-01T09:00:00+00:00",
            "recorded_by": WHO}


# Every state-changing endpoint, with a body that would succeed (or fail validation) if allowed.
PROTECTED = [
    ("post", f"/api/v1/care-gaps/{GAP}/follow-ups", {"event_type": "note_recorded", "recorded_by": WHO, "note": "n"}),
    ("post", "/api/v1/care-gaps/SYNTH-GAP-000026/follow-ups",
     {"event_type": "completion_documented", "close_gap": True, "documented_evidence": True,
      "evidence_reference": "SYNTH-REF-000001", "recorded_by": WHO}),
    ("post", f"/api/v1/care-gaps/{GAP}/reviews", {"reviewer": WHO, "action": "confirmed", "reason": "ok"}),
    ("post", "/api/v1/appointments", _apt()),
    ("patch", "/api/v1/appointments/SYNTH-APT-000001", {"status": "attended", "recorded_by": WHO}),
    ("post", "/api/v1/referrals", {"patient_id": "SYNTH-PAT-000008", "ifhas_screening_id": "SYNTH-SCR-000002",
                                   "trigger_rule_id": RULE, "trigger_rule_version": "1.0.0",
                                   "referral_target": "diagnostics", "trigger_date": "2026-11-16",
                                   "recorded_by": WHO}),
    ("patch", "/api/v1/referrals/SYNTH-REF-000001", {"status": "declined", "recorded_by": WHO}),
    ("post", "/api/v1/outreach/draft", {"patient_id": PID, "rule_id": RULE, "channel": "phone"}),
    ("post", "/api/v1/outreach/draft/review", {"draft_audit_id": "x", "patient_id": PID, "rule_id": RULE,
                                               "care_gap_id": GAP, "channel": "phone", "language": "en",
                                               "decision": "rejected", "reviewed_by": WHO}),
]


def _call(method, path, body, key=None):
    headers = {WRITE_KEY_HEADER: key} if key is not None else {}
    return getattr(client, method)(path, json=body, headers=headers)


def test_every_non_get_route_is_either_protected_here_or_explicitly_read_only():
    # The shared key guards the legacy `/api/v1` router. Identity/portal/admin routers only exist in
    # AUTH_MODE=users (404 here); their authorization is covered by tests/test_rbac.py.
    from app.api.v1 import router as v1_router

    writes = {(m.lower(), r.path) for r in v1_router.routes if isinstance(r, APIRoute)
              for m in r.methods if m not in ("GET", "HEAD")}
    covered = {(m, p.replace(GAP, "{gap_id}").replace("SYNTH-GAP-000026", "{gap_id}")
                .replace("SYNTH-APT-000001", "{appointment_id}").replace("SYNTH-REF-000001", "{referral_id}"))
               for m, p, _ in PROTECTED}
    assert writes - covered == {("post", p) for p in READ_ONLY_POSTS}


@pytest.mark.parametrize("method,path,body", PROTECTED)
@pytest.mark.parametrize("key", [None, "", "wrong-key", KEY + "x", KEY.upper()])
def test_missing_or_invalid_key_is_401_and_writes_nothing(method, path, body, key):
    resp = _call(method, path, body, key)
    assert resp.status_code == 401, resp.text
    assert resp.json()["error"]["code"] == "unauthorized"
    assert KEY not in resp.text
    assert client.get(f"/api/v1/care-gaps/{GAP}/follow-ups").json()["total"] == 0
    assert client.get(f"/api/v1/patients/{PID}/activity").json()["workflow_events"] == []


def test_invalid_body_without_key_is_still_401():
    assert client.post("/api/v1/appointments", json={}).status_code == 401


def test_valid_key_allows_writes():
    apt = _call("post", "/api/v1/appointments", _apt(), KEY)
    assert apt.status_code == 201, apt.text
    apt_id = apt.json()["appointment_id"]
    assert _call("patch", f"/api/v1/appointments/{apt_id}", {"status": "attended", "recorded_by": WHO}, KEY).status_code == 200
    fu = _call("post", f"/api/v1/care-gaps/{GAP}/follow-ups", {"event_type": "note_recorded", "recorded_by": WHO, "note": "n"}, KEY)
    assert fu.status_code == 201
    assert _call("post", f"/api/v1/care-gaps/{GAP}/reviews", {"reviewer": WHO, "action": "confirmed", "reason": "ok"}, KEY).status_code == 201
    draft = _call("post", "/api/v1/outreach/draft", {"patient_id": PID, "rule_id": RULE, "channel": "phone"}, KEY).json()
    assert draft["allowed"] is True
    review = _call("post", "/api/v1/outreach/draft/review", {
        "draft_audit_id": draft["ai"]["audit_id"], "patient_id": PID, "rule_id": RULE, "care_gap_id": draft["care_gap_id"],
        "channel": "phone", "language": "en", "decision": "approved", "final_message": draft["draft_body"],
        "reviewed_by": WHO}, KEY)
    assert review.status_code == 200 and review.json()["review_status"] == "approved"


@pytest.mark.parametrize("path", [
    "/health", "/api/v1/dashboard/summary", "/api/v1/patients?limit=2", f"/api/v1/patients/{PID}",
    f"/api/v1/patients/{PID}/evaluations", f"/api/v1/care-gaps/{GAP}", "/api/v1/rules", "/api/v1/facilities?limit=1",
    "/api/v1/insights/population", "/api/v1/ai/status", "/api/v1/ai/audit", "/api/v1/appointments",
])
def test_get_endpoints_stay_public(path):
    assert client.get(path).status_code == 200


@pytest.mark.parametrize("path,body", [
    ("/api/v1/evaluations", {"patient_id": PID, "look_ahead_days": 90}),
    ("/api/v1/outreach/preview", {"patient_id": PID, "rule_id": RULE, "channel": "phone"}),
    ("/api/v1/explanations", {"patient_id": PID, "rule_id": RULE}),
])
def test_read_oriented_posts_are_exempt_and_store_no_workflow_state(path, body):
    assert client.post(path, json=body).status_code == 200
    assert client.get(f"/api/v1/care-gaps/{GAP}/follow-ups").json()["total"] == 0
    assert client.get(f"/api/v1/patients/{PID}/activity").json() == {
        "is_synthetic": True, "patient_id": PID, "follow_up_events": [], "workflow_events": []}


def test_unconfigured_key_fails_closed(monkeypatch):
    monkeypatch.setattr(settings, "write_api_key", None)
    resp = client.post("/api/v1/appointments", json=_apt(), headers={WRITE_KEY_HEADER: "anything"})
    assert resp.status_code == 503 and "WRITE_API_KEY" in resp.json()["detail"]
    monkeypatch.setattr(settings, "write_api_key", SecretStr(""))
    assert client.post("/api/v1/appointments", json=_apt()).status_code == 503
    assert client.get("/api/v1/dashboard/summary").status_code == 200  # reads unaffected
    assert client.post("/api/v1/explanations", json={"patient_id": PID, "rule_id": RULE}).status_code == 200


def test_unprotected_writes_only_when_explicitly_allowed(monkeypatch):
    monkeypatch.setattr(settings, "write_api_key", None)
    monkeypatch.setattr(settings, "allow_unprotected_writes", True)
    assert client.post("/api/v1/appointments", json=_apt()).status_code == 201


def test_key_is_never_logged_or_returned(caplog):
    caplog.set_level(logging.DEBUG)
    _call("post", "/api/v1/appointments", _apt(), "wrong-key")
    _call("post", "/api/v1/appointments", _apt(), KEY)
    for path in ("/api/v1/ai/status", "/api/v1/ai/audit", "/health"):
        assert KEY not in client.get(path).text
    assert KEY not in caplog.text and "wrong-key" not in caplog.text
    assert KEY not in repr(settings) and KEY not in str(settings.model_dump())


def test_cors_preflight_allows_the_write_key_header():
    resp = client.options("/api/v1/appointments", headers={
        "Origin": "http://localhost:3000", "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": f"content-type,{WRITE_KEY_HEADER.lower()}"})
    assert resp.status_code == 200
    assert WRITE_KEY_HEADER.lower() in resp.headers["access-control-allow-headers"].lower()
