"""Audit attribution: actors are server-derived, denials change nothing, events are queryable."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.repositories.followup_repo import reset_memory_writes
from identity_fixtures import RULE_A, client, users_mode, world  # noqa: F401


def _events(world, **params):
    q = "&".join(f"{k}={v}" for k, v in params.items())
    return client.get(f"/api/v1/audit-events?limit=500&{q}", headers=world.h("admin_a")).json()


def test_client_supplied_actor_fields_are_ignored(world):
    h = world.h("cc_a")
    me = world.users["cc_a"]
    fu = client.post(f"/api/v1/care-gaps/{world.gap_a}/follow-ups", headers=h,
                     json={"event_type": "note_recorded", "note": "n", "recorded_by": "dr.someone.else"})
    assert fu.status_code == 201 and fu.json()["recorded_by"] == me
    rv = client.post(f"/api/v1/care-gaps/{world.gap_a}/reviews", headers=h,
                     json={"action": "confirmed", "reason": "ok", "reviewer": "impersonated"})
    assert rv.json()["reviewer"] == me
    apt = client.post("/api/v1/appointments", headers=h, json={
        "patient_id": world.pid_a, "profile_id": "SYNTH-FSP-000001", "appointment_type": "ifhas_screening",
        "scheduled_datetime": "2026-12-03T09:00:00+00:00", "recorded_by": "forged"}).json()
    hist = client.get(f"/api/v1/appointments/{apt['appointment_id']}/history", headers=h).json()["items"]
    assert {e["recorded_by"] for e in hist} == {me}
    draft = client.post("/api/v1/outreach/draft", headers=h, json={
        "patient_id": world.pid_a, "rule_id": RULE_A, "channel": "phone"}).json()
    review = client.post("/api/v1/outreach/draft/review", headers=h, json={
        "draft_audit_id": draft["ai"]["audit_id"], "patient_id": world.pid_a, "rule_id": RULE_A,
        "care_gap_id": draft["care_gap_id"], "channel": "phone", "language": "en", "decision": "approved",
        "final_message": draft["draft_body"], "reviewed_by": "not-me"}).json()
    assert review["follow_up"]["recorded_by"] == me
    ai = client.get("/api/v1/ai/audit?feature=outreach_review", headers=world.h("admin_a")).json()["items"][0]
    assert ai["extra"]["reviewed_by"] == me and ai["extra"]["actor_user_id"] == me


def test_state_changes_create_attributed_audit_events_with_correlation_id(world):
    r = client.post(f"/api/v1/care-gaps/{world.gap_a}/follow-ups", headers={**world.h("cc_a"), "X-Request-ID": "corr-123"},
                    json={"event_type": "note_recorded", "note": "SECRET CLINICAL NOTE"})
    assert r.status_code == 201
    ev = _events(world, action="follow_up.note_recorded")["items"][0]
    assert ev["actor_user_id"] == world.users["cc_a"] and ev["actor_role"] == "CARE_COORDINATOR"
    assert ev["organization_id"] == world.org_a and ev["resource_type"] == "care_gap"
    assert ev["resource_id"] == world.gap_a and ev["patient_id"] == world.pid_a
    assert ev["outcome"] == "success" and ev["status_code"] == 201 and ev["request_id"] == "corr-123"
    assert ev["permission"] == "followups.create"
    assert "SECRET CLINICAL NOTE" not in str(_events(world))


def test_failed_operations_are_audited_as_failed(world):
    apt = client.post("/api/v1/appointments", headers=world.h("cc_a"), json={
        "patient_id": world.pid_a, "profile_id": "SYNTH-FSP-000001", "appointment_type": "other",
        "scheduled_datetime": "2026-12-04T09:00:00+00:00"}).json()
    client.patch(f"/api/v1/appointments/{apt['appointment_id']}", headers=world.h("cc_a"), json={"status": "attended"})
    bad = client.patch(f"/api/v1/appointments/{apt['appointment_id']}", headers=world.h("cc_a"),
                       json={"status": "no_show"})
    assert bad.status_code == 422
    failed = _events(world, action="appointment.update", outcome="failed")
    assert failed["total"] == 1 and failed["items"][0]["status_code"] == 422


def test_denied_requests_change_nothing_and_are_audited(world):
    before = client.get(f"/api/v1/care-gaps/{world.gap_a}/follow-ups", headers=world.h("cc_a")).json()["total"]
    denied = client.post(f"/api/v1/care-gaps/{world.gap_a}/follow-ups", headers=world.h("patient_a"),
                         json={"event_type": "note_recorded", "note": "patient tries"})
    assert denied.status_code == 403
    scope = client.post(f"/api/v1/care-gaps/{world.gap_a}/follow-ups", headers=world.h("cc_b"),
                        json={"event_type": "note_recorded", "note": "other org"})
    assert scope.status_code == 404
    after = client.get(f"/api/v1/care-gaps/{world.gap_a}/follow-ups", headers=world.h("cc_a")).json()["total"]
    assert after == before
    d = _events(world, outcome="denied", action="authz.denied")["items"]
    assert any(e["actor_user_id"] == world.users["patient_a"] and e["status_code"] == 403 for e in d)
    b = client.get("/api/v1/audit-events?action=authz.scope_denied", headers=world.h("admin_b")).json()["items"]
    assert any(e["actor_user_id"] == world.users["cc_b"] and e["resource_id"] == world.gap_a for e in b)


def test_auth_events_are_audited(world):
    client.post("/api/v1/auth/login", json={"email": world.emails["cc_a"], "password": "wrong-password-1"})
    world.login("cc_a")
    logins = _events(world, action="auth.login")["items"]
    assert any(e["outcome"] == "denied" and e["actor_user_id"] == world.users["cc_a"] for e in logins)
    assert any(e["outcome"] == "success" and e["actor_user_id"] == world.users["cc_a"] for e in logins)


def test_audit_filters_apply_before_pagination(world):
    for i in range(3):
        client.post(f"/api/v1/care-gaps/{world.gap_a}/reviews", headers=world.h("cc_a"),
                    json={"action": "confirmed", "reason": f"r{i}"})
    page = client.get("/api/v1/audit-events?action=care_gap.review.confirmed&limit=2&offset=0",
                      headers=world.h("admin_a")).json()
    assert page["total"] == 3 and len(page["items"]) == 2
    rest = client.get("/api/v1/audit-events?action=care_gap.review.confirmed&limit=2&offset=2",
                      headers=world.h("admin_a")).json()
    assert len(rest["items"]) == 1
    by_patient = _events(world, patient_id=world.pid_a, action="care_gap.review.confirmed")
    assert by_patient["total"] == 3


def test_audit_log_has_no_mutation_endpoints():
    paths = [r for r in app.routes if getattr(r, "path", "").startswith("/api/v1/audit-events")]
    assert {m for r in paths for m in r.methods} <= {"GET", "HEAD"}


def test_legacy_mode_still_requires_client_actor(monkeypatch):
    # Previous contract preserved in AUTH_MODE=legacy (the default for the regression suites).
    reset_memory_writes()
    legacy = TestClient(app)
    r = legacy.post("/api/v1/care-gaps/SYNTH-GAP-000001/follow-ups", json={"event_type": "note_recorded", "note": "x"})
    assert r.status_code == 422 and r.json()["detail"][0]["loc"] == ["body", "recorded_by"]
    ok = legacy.post("/api/v1/care-gaps/SYNTH-GAP-000001/follow-ups",
                     json={"event_type": "note_recorded", "note": "x", "recorded_by": "legacy.actor"})
    assert ok.status_code == 201 and ok.json()["recorded_by"] == "legacy.actor"
    reset_memory_writes()
