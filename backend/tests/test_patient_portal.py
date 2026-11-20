"""Patient portal, verified account linking and the patient engagement follow-up workflow."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from app.core.config import settings
from app.repositories.read_repo import get_cached_dataset, get_cached_index
from identity_fixtures import PW, client, users_mode, world  # noqa: F401


def _register_and_login(email: str) -> dict:
    client.post("/api/v1/auth/register", json={"email": email, "password": PW, "full_name": "New Patient"})
    tok = client.post("/api/v1/auth/login", json={"email": email, "password": PW}).json()
    return {"Authorization": f"Bearer {tok['access_token']}"}


def _invite(world, pid: str) -> str:
    r = client.post(f"/api/v1/patients/{pid}/portal-invitations", headers=world.h("phm_a"))
    assert r.status_code == 201, r.text
    assert r.json()["delivery"] == "out_of_band_not_sent"
    return r.json()["code"]


def _dob(pid: str) -> str:
    return get_cached_index().patients_by_id[pid]["date_of_birth"].isoformat()


# --- linking -------------------------------------------------------------------------------


def test_verified_linking_with_invitation_and_date_of_birth(world):
    pid = world.pid_a_unassigned
    h = _register_and_login("self.registered@test.pulsereach.invalid")
    code = _invite(world, pid)
    r = client.post("/api/v1/portal/link", headers=h, json={"invitation_code": code.lower().replace("-", " "),
                                                           "date_of_birth": _dob(pid)})
    assert r.status_code == 200 and r.json()["patient_id"] == pid
    # The session that linked keeps its (membership-less) scope; a new login gets the PATIENT role.
    tok = client.post("/api/v1/auth/login", json={"email": "self.registered@test.pulsereach.invalid",
                                                 "password": PW}).json()
    assert tok["role"] == "PATIENT" and tok["organization_id"] == world.org_a
    summary = client.get("/api/v1/portal/summary", headers={"Authorization": f"Bearer {tok['access_token']}"})
    assert summary.status_code == 200 and summary.json()["patient_id"] == pid
    # Single use.
    h2 = _register_and_login("second.claimant@test.pulsereach.invalid")
    assert client.post("/api/v1/portal/link", headers=h2,
                       json={"invitation_code": code, "date_of_birth": _dob(pid)}).status_code == 400


def test_wrong_date_of_birth_fails_and_locks_the_invitation(world):
    pid = world.pid_a_unassigned
    h = _register_and_login("guesser@test.pulsereach.invalid")
    code = _invite(world, pid)
    real = date.fromisoformat(_dob(pid))
    for i in range(settings.patient_invitation_max_attempts):
        r = client.post("/api/v1/portal/link", headers=h, json={
            "invitation_code": code, "date_of_birth": (real - timedelta(days=i + 1)).isoformat()})
        assert r.status_code in (400, 429)
    from app.core.rate_limit import reset_rate_limits

    reset_rate_limits()
    r = client.post("/api/v1/portal/link", headers=h, json={"invitation_code": code, "date_of_birth": real.isoformat()})
    assert r.status_code == 400  # invitation revoked after too many wrong answers
    assert r.json()["error"]["message_key"] == "link.invitation_invalid"


def test_patient_cannot_self_assign_a_record(world):
    h = _register_and_login("hopeful@test.pulsereach.invalid")
    r = client.post("/api/v1/portal/link", headers=h, json={"invitation_code": "AAAA-BBBB-CCCC",
                                                           "date_of_birth": _dob(world.pid_b)})
    assert r.status_code == 400
    assert client.get("/api/v1/portal/summary", headers=h).status_code == 404


def test_duplicate_or_conflicting_links_are_refused(world):
    code = _invite(world, world.pid_a)  # already linked to patient_a
    h = _register_and_login("duplicate@test.pulsereach.invalid")
    assert client.post("/api/v1/portal/link", headers=h,
                       json={"invitation_code": code, "date_of_birth": _dob(world.pid_a)}).status_code == 400
    code2 = _invite(world, world.pid_a_unassigned)
    r = client.post("/api/v1/portal/link", headers=world.h("patient_a"),
                    json={"invitation_code": code2, "date_of_birth": _dob(world.pid_a_unassigned)})
    assert r.status_code == 409 and r.json()["error"]["message_key"] == "link.already_linked"
    r = client.post("/api/v1/portal/link", headers=world.h("cc_a"),
                    json={"invitation_code": code2, "date_of_birth": _dob(world.pid_a_unassigned)})
    assert r.status_code == 403


def test_admin_can_revoke_a_link(world):
    links = client.get("/api/v1/admin/patient-links", headers=world.h("admin_a")).json()["items"]
    assert [x["patient_id"] for x in links] == [world.pid_a]
    r = client.post(f"/api/v1/admin/patient-links/{links[0]['link_id']}/revoke", headers=world.h("admin_a"))
    assert r.status_code == 200 and r.json()["status"] == "revoked"
    world._tokens.pop("patient_a", None)
    assert client.get("/api/v1/portal/summary", headers=world.h("patient_a")).status_code == 404


# --- own data only -------------------------------------------------------------------------


def test_patient_sees_own_profile_health_and_evaluations(world):
    h = world.h("patient_a")
    s = client.get("/api/v1/portal/summary", headers=h).json()
    assert s["patient_id"] == world.pid_a and s["is_synthetic"] is True
    assert "emirates_id_synthetic" not in s
    hs = client.get("/api/v1/portal/health-summary", headers=h).json()
    assert hs["patient_id"] == world.pid_a and hs["history"]
    ev = client.get("/api/v1/portal/evaluations", headers=h).json()
    assert ev["items"] and all(i["status"] != "not_eligible" for i in ev["items"])
    for forbidden in ("input_snapshot", "reason_code", "guard_id", "reasons", "review_origin"):
        assert forbidden not in str(ev)


def test_patient_recommendations_are_own_and_patient_friendly(world):
    h = world.h("patient_a")
    recs = client.get("/api/v1/portal/recommendations", headers=h).json()
    own_open = [g for g in get_cached_index().care_gaps_by_patient[world.pid_a] if g["status"] == "open"]
    assert recs["total"] == len(own_open)
    item = next(r for r in recs["items"] if r["recommendation_id"] == world.gap_a)
    assert item["title"] and item["next_step_text"] and item["status_label"] == "Open"
    detail = client.get(f"/api/v1/portal/recommendations/{world.gap_a}", headers=h).json()
    assert detail["evidence"] and detail["history"][0]["event"] == "identified"
    assert "disclaimer" in detail
    exp = client.get(f"/api/v1/portal/recommendations/{world.gap_a}/explanation", headers=h).json()
    assert exp["generation_mode"] == "deterministic_template" and exp["paragraphs"]
    for forbidden in ("reason_code", "guard", "input_snapshot", "recorded_by", "spec"):
        assert forbidden not in str(detail) + str(exp)


def test_patient_cannot_access_another_patients_resources(world):
    h = world.h("patient_a")
    ds = get_cached_dataset()
    other_gap = world.gap_b
    other_apt = next(a["appointment_id"] for a in ds.appointments if a["patient_id"] != world.pid_a)
    other_ref = next(r["referral_id"] for r in ds.referrals if r["patient_id"] != world.pid_a)
    for path in (f"/api/v1/portal/recommendations/{other_gap}",
                 f"/api/v1/portal/recommendations/{other_gap}/explanation",
                 f"/api/v1/portal/appointments/{other_apt}", f"/api/v1/portal/referrals/{other_ref}"):
        assert client.get(path, headers=h).status_code == 404, path
    assert client.post(f"/api/v1/portal/appointments/{other_apt}/change-requests", headers=h,
                       json={"action": "cancel"}).status_code == 404
    assert client.post("/api/v1/portal/appointment-requests", headers=h,
                       json={"recommendation_id": other_gap}).status_code == 404
    # Staff endpoints with the patient's own id are still refused.
    assert client.get(f"/api/v1/patients/{world.pid_a}", headers=h).status_code == 403
    # Query parameters cannot widen the scope.
    assert client.get(f"/api/v1/portal/appointments?patient_id={world.pid_b}", headers=h).json()["items"] == [
        x for x in client.get("/api/v1/portal/appointments", headers=h).json()["items"]]


def test_patient_appointments_referrals_and_change_requests(world):
    h = world.h("patient_a")
    apts = client.get("/api/v1/portal/appointments", headers=h).json()
    own = [a for a in get_cached_dataset().appointments if a["patient_id"] == world.pid_a]
    assert apts["total"] == len(own)
    future = (datetime.now(timezone.utc) + timedelta(days=10)).isoformat()
    soon = (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()
    a_far = client.post("/api/v1/appointments", headers=world.h("cc_a"), json={
        "patient_id": world.pid_a, "profile_id": "SYNTH-FSP-000001", "appointment_type": "ifhas_screening",
        "scheduled_datetime": future}).json()
    a_soon = client.post("/api/v1/appointments", headers=world.h("cc_a"), json={
        "patient_id": world.pid_a, "profile_id": "SYNTH-FSP-000001", "appointment_type": "other",
        "scheduled_datetime": soon}).json()
    detail = client.get(f"/api/v1/portal/appointments/{a_far['appointment_id']}", headers=h).json()
    assert detail["can_request_change"] is True and detail["status"] == "scheduled"
    r = client.post(f"/api/v1/portal/appointments/{a_far['appointment_id']}/change-requests", headers=h,
                    json={"action": "reschedule", "preferred_dates": [str(date.today() + timedelta(days=20))]})
    assert r.status_code == 201 and r.json()["request_type"] == "appointment_change"
    # The appointment itself is unchanged until staff act on the request.
    assert client.get(f"/api/v1/portal/appointments/{a_far['appointment_id']}", headers=h).json()["status"] == "scheduled"
    late = client.post(f"/api/v1/portal/appointments/{a_soon['appointment_id']}/change-requests", headers=h,
                       json={"action": "cancel"})
    assert late.status_code == 422
    refs = client.get("/api/v1/portal/referrals", headers=h).json()
    assert refs["total"] == sum(1 for x in get_cached_dataset().referrals if x["patient_id"] == world.pid_a)


def test_patient_requests_lifecycle(world):
    h = world.h("patient_a")
    r = client.post("/api/v1/portal/appointment-requests", headers=h, json={
        "recommendation_id": world.gap_a, "preferred_time_of_day": "evening", "message": "Weekday evenings"})
    assert r.status_code == 201
    req = r.json()
    assert req["status"] == "submitted" and req["recommendation_id"] == world.gap_a
    assert client.get("/api/v1/portal/requests", headers=h).json()["total"] == 1
    staff = client.patch(f"/api/v1/patient-requests/{req['request_id']}", headers=world.h("cc_a"),
                         json={"status": "acknowledged", "staff_response": "We will call you.",
                               "internal_note": "prefers evenings; check slots"})
    assert staff.status_code == 200 and staff.json()["handled_by_user_id"] == world.users["cc_a"]
    mine = client.get(f"/api/v1/portal/requests/{req['request_id']}", headers=h).json()
    assert mine["status"] == "acknowledged" and mine["staff_response"] == "We will call you."
    assert "internal_note" not in mine and "prefers evenings" not in str(mine)
    assert client.post(f"/api/v1/portal/requests/{req['request_id']}/cancel", headers=h).json()["status"] == "cancelled"
    assistance = client.post("/api/v1/portal/assistance", headers=h, json={"message": "I need help booking"})
    assert assistance.status_code == 201 and assistance.json()["request_type"] == "assistance"


# --- follow-up workflow --------------------------------------------------------------------


def _task(world, **extra) -> dict:
    r = client.post("/api/v1/follow-up-tasks", headers=world.h("cc_a"), json={
        "patient_id": world.pid_a, "care_gap_id": world.gap_a, "assigned_to_user_id": world.users["cc_a"],
        "due_date": str(date.today() + timedelta(days=14)), "staff_note": "INTERNAL: call after 5pm", **extra})
    assert r.status_code == 201, r.text
    return r.json()


def test_follow_up_workflow_end_to_end_with_verified_completion(world):
    task = _task(world)
    assert task["status"] == "awaiting_patient" and task["language"] == "en" and task["rule_id"]
    h = world.h("patient_a")
    mine = client.get("/api/v1/portal/follow-ups", headers=h).json()
    assert mine["total"] == 1 and mine["items"][0]["message"]
    detail = client.get(f"/api/v1/portal/follow-ups/{task['task_id']}", headers=h).json()
    assert "INTERNAL" not in str(detail) and "staff_note" not in detail
    # Staff send a patient-visible message and an internal note.
    client.post(f"/api/v1/follow-up-tasks/{task['task_id']}/notes", headers=world.h("cc_a"),
                json={"text": "INTERNAL: second note"})
    client.post(f"/api/v1/follow-up-tasks/{task['task_id']}/notes", headers=world.h("cc_a"),
                json={"text": "Hello, how can we help?", "patient_visible": True})
    hist = client.get(f"/api/v1/portal/follow-ups/{task['task_id']}/history", headers=h).json()["items"]
    assert any(e["message"] == "Hello, how can we help?" and e["from_care_team"] for e in hist)
    assert all("INTERNAL" not in (e["message"] or "") for e in hist)
    # Patient responds: "already done" is only a report.
    r = client.post(f"/api/v1/portal/follow-ups/{task['task_id']}/responses", headers=h,
                    json={"response": "already_done", "message": "Done at another clinic"})
    assert r.status_code == 201 and r.json()["reported_completion_pending_verification"] is True
    assert r.json()["status"] == "patient_responded"
    gap = client.get(f"/api/v1/care-gaps/{world.gap_a}", headers=world.h("cc_a")).json()
    assert gap["status"] == "open"
    # Coordinator reviews; completion without documented evidence is refused.
    staff_view = client.get(f"/api/v1/follow-up-tasks/{task['task_id']}", headers=world.h("cc_a")).json()
    assert staff_view["patient_reported_completion"] is True
    assert {e["visibility"] for e in staff_view["events"]} == {"patient", "internal"}
    refused = client.post(f"/api/v1/follow-up-tasks/{task['task_id']}/complete", headers=world.h("cc_a"), json={})
    assert refused.status_code == 422
    note = client.post(f"/api/v1/care-gaps/{world.gap_a}/follow-ups", headers=world.h("cc_a"),
                       json={"event_type": "note_recorded", "note": "not completion"}).json()
    still = client.post(f"/api/v1/follow-up-tasks/{task['task_id']}/complete", headers=world.h("cc_a"),
                        json={"completion_follow_up_id": note["follow_up_id"]})
    assert still.status_code == 422
    assert client.patch(f"/api/v1/follow-up-tasks/{task['task_id']}", headers=world.h("cc_a"),
                        json={"status": "in_progress"}).status_code == 200


def test_patient_actions_on_follow_ups(world):
    task = _task(world)
    h = world.h("patient_a")
    a = client.post(f"/api/v1/portal/follow-ups/{task['task_id']}/assistance", headers=h,
                    json={"message": "Please call me"})
    assert a.status_code == 201 and a.json()["follow_up_id"] == task["task_id"]
    b = client.post(f"/api/v1/portal/follow-ups/{task['task_id']}/appointment-request", headers=h,
                    json={"preferred_time_of_day": "morning"})
    assert b.status_code == 201 and b.json()["request_type"] == "appointment"
    history = client.get(f"/api/v1/portal/follow-ups/{task['task_id']}/history", headers=h).json()["items"]
    assert {"assistance_requested", "appointment_requested"} <= {e["event_type"] for e in history}
    client.patch(f"/api/v1/follow-up-tasks/{task['task_id']}", headers=world.h("cc_a"), json={"status": "cancelled"})
    closed = client.post(f"/api/v1/portal/follow-ups/{task['task_id']}/responses", headers=h,
                         json={"response": "will_book"})
    assert closed.status_code == 409


def test_internal_only_tasks_are_invisible_to_patients(world):
    task = _task(world, patient_visible=False)
    h = world.h("patient_a")
    assert client.get("/api/v1/portal/follow-ups", headers=h).json()["total"] == 0
    assert client.get(f"/api/v1/portal/follow-ups/{task['task_id']}", headers=h).status_code == 404


def test_overdue_and_escalation(world):
    task = _task(world, due_date=str(date.today() - timedelta(days=1)))
    assert task["is_overdue"] is True
    overdue = client.get("/api/v1/follow-up-tasks?overdue=true", headers=world.h("cc_a")).json()
    assert [t["task_id"] for t in overdue["items"]] == [task["task_id"]]
    esc = client.post(f"/api/v1/follow-up-tasks/{task['task_id']}/escalate", headers=world.h("cc_a"),
                      json={"reason": "no answer"}).json()
    assert esc["escalated_at"] is not None
    portal = client.get(f"/api/v1/portal/follow-ups/{task['task_id']}", headers=world.h("patient_a")).json()
    assert portal["is_overdue"] is True and all(e["event_type"] != "escalated" for e in portal["history"])


def test_task_assignee_must_have_access_to_the_patient(world):
    r = client.post("/api/v1/follow-up-tasks", headers=world.h("phm_a"), json={
        "patient_id": world.pid_a_unassigned, "assigned_to_user_id": world.users["cc_a"]})
    assert r.status_code == 422
    r = client.post("/api/v1/follow-up-tasks", headers=world.h("phm_a"), json={
        "patient_id": world.pid_a, "assigned_to_user_id": world.users["cc_b"]})
    assert r.status_code == 422


def test_task_on_closed_or_foreign_gap_is_refused(world):
    r = client.post("/api/v1/follow-up-tasks", headers=world.h("cc_a"), json={
        "patient_id": world.pid_a, "care_gap_id": world.gap_b})
    assert r.status_code == 422


def test_task_completes_only_with_documented_completion_on_its_care_gap(world):
    gap_id, ref_id = "SYNTH-GAP-000026", "SYNTH-REF-000001"
    owner = next(g["patient_id"] for g in get_cached_dataset().care_gaps if g["care_gap_id"] == gap_id)
    org_alias = "a" if owner in set(world.patients_a) else "b"
    cc, phm = f"cc_{org_alias}", f"phm_{org_alias}"
    assert client.post("/api/v1/admin/assignments", headers=world.h(phm),
                       json={"staff_user_id": world.users[cc], "patient_id": owner}).status_code == 201
    task = client.post("/api/v1/follow-up-tasks", headers=world.h(cc),
                       json={"patient_id": owner, "care_gap_id": gap_id}).json()
    assert client.patch(f"/api/v1/referrals/{ref_id}", headers=world.h(cc), json={
        "status": "initiated", "initiated_date": "2026-09-20"}).status_code == 200
    assert client.patch(f"/api/v1/referrals/{ref_id}", headers=world.h(cc), json={
        "status": "completed", "completed_date": "2026-10-01"}).status_code == 200
    done = client.post(f"/api/v1/care-gaps/{gap_id}/follow-ups", headers=world.h(cc), json={
        "event_type": "completion_documented", "close_gap": True, "documented_evidence": True,
        "evidence_reference": ref_id})
    assert done.status_code == 201, done.text
    assert done.json()["recorded_by"] == world.users[cc]
    r = client.post(f"/api/v1/follow-up-tasks/{task['task_id']}/complete", headers=world.h(cc),
                    json={"completion_follow_up_id": done.json()["follow_up_id"]})
    assert r.status_code == 200 and r.json()["status"] == "completed"
    assert r.json()["completion_follow_up_id"] == done.json()["follow_up_id"]
    assert client.get(f"/api/v1/care-gaps/{gap_id}", headers=world.h(cc)).json()["status"] == "closed_completed"
