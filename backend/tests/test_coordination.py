"""Phase 5 coordination additions (AUTH_MODE=users, memory mode): task priority, contact attempts,
the task summary, the care-team directory, service profiles and appointment filters, plus the
request -> appointment workflow end to end. None of it closes a care gap or sends anything."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from app.repositories.read_repo import get_cached_dataset, get_cached_index
from identity_fixtures import RULE_A, client, users_mode, world  # noqa: F401


def _task(world, alias="cc_a", **extra) -> dict:
    body = {"patient_id": world.pid_a, "care_gap_id": world.gap_a, "assigned_to_user_id": world.users["cc_a"],
            "due_date": str(date.today() + timedelta(days=14)), **extra}
    r = client.post("/api/v1/follow-up-tasks", headers=world.h(alias), json=body)
    assert r.status_code == 201, r.text
    return r.json()


# --- priority ------------------------------------------------------------------------------


def test_priority_defaults_to_routine_and_changes_are_internal_history(world):
    task = _task(world)
    assert task["priority"] == "routine" and not any(e["event_type"] == "priority_changed" for e in task["events"])
    urgent = _task(world, priority="urgent")
    assert [e["priority"] for e in urgent["events"] if e["event_type"] == "priority_changed"] == ["urgent"]
    r = client.patch(f"/api/v1/follow-up-tasks/{task['task_id']}", headers=world.h("cc_a"), json={"priority": "high"})
    assert r.status_code == 200 and r.json()["priority"] == "high"
    ev = [e for e in r.json()["events"] if e["event_type"] == "priority_changed"]
    assert len(ev) == 1 and ev[0]["visibility"] == "internal" and ev[0]["priority"] == "high"
    # Unchanged priority records nothing new.
    again = client.patch(f"/api/v1/follow-up-tasks/{task['task_id']}", headers=world.h("cc_a"),
                         json={"priority": "high"}).json()
    assert sum(e["event_type"] == "priority_changed" for e in again["events"]) == 1
    assert client.patch(f"/api/v1/follow-up-tasks/{task['task_id']}", headers=world.h("cc_a"),
                        json={"priority": "critical"}).status_code == 422
    portal = client.get(f"/api/v1/portal/follow-ups/{task['task_id']}/history", headers=world.h("patient_a")).json()
    assert all(e["event_type"] != "priority_changed" for e in portal["items"])
    high = client.get("/api/v1/follow-up-tasks?priority=high", headers=world.h("cc_a")).json()
    assert [t["task_id"] for t in high["items"]] == [task["task_id"]]


def test_clinician_cannot_update_task_priority(world):
    task = _task(world)
    assert client.patch(f"/api/v1/follow-up-tasks/{task['task_id']}", headers=world.h("clin_a"),
                        json={"priority": "urgent"}).status_code == 403


# --- contact attempts ----------------------------------------------------------------------


def test_contact_attempt_is_internal_documentation_and_changes_nothing_else(world):
    task = _task(world)
    r = client.post(f"/api/v1/follow-up-tasks/{task['task_id']}/contact-attempts", headers=world.h("cc_a"),
                    json={"channel": "phone", "outcome": "no_answer", "note": "INTERNAL: rang twice"})
    assert r.status_code == 200, r.text
    out = r.json()
    attempt = next(e for e in out["events"] if e["event_type"] == "contact_attempt")
    assert attempt["visibility"] == "internal" and attempt["contact_channel"] == "phone"
    assert attempt["response_code"] == "no_answer" and attempt["actor_user_id"] == world.users["cc_a"]
    assert out["status"] == task["status"]  # documenting a call does not move the workflow
    portal = client.get(f"/api/v1/portal/follow-ups/{task['task_id']}/history", headers=world.h("patient_a")).json()
    assert "rang twice" not in str(portal) and all(e["event_type"] != "contact_attempt" for e in portal["items"])
    gap = client.get(f"/api/v1/care-gaps/{world.gap_a}", headers=world.h("cc_a")).json()
    assert gap["status"] == "open"
    audit = client.get("/api/v1/audit-events?limit=200", headers=world.h("admin_a")).json()["items"]
    assert any(a["action"] == "follow_up_task.contact_attempt" for a in audit)


def test_contact_attempt_requires_contact_consent(world):
    idx = get_cached_index()
    from app.services.outreach.service import resolve_applicable_contact_consent

    pid = next(p for p in world.patients_a if p != world.pid_a and resolve_applicable_contact_consent(
        idx.consents_by_patient.get(p, []), rule_id="", pathway="") is None)
    assert client.post("/api/v1/admin/assignments", headers=world.h("phm_a"),
                       json={"staff_user_id": world.users["cc_a"], "patient_id": pid}).status_code == 201
    task = client.post("/api/v1/follow-up-tasks", headers=world.h("cc_a"),
                       json={"patient_id": pid, "message_key": "general_check_in"}).json()
    r = client.post(f"/api/v1/follow-up-tasks/{task['task_id']}/contact-attempts", headers=world.h("cc_a"),
                    json={"channel": "sms", "outcome": "reached"})
    assert r.status_code == 422 and "contact_consent_absent" in r.json()["error"]["message"]
    detail = client.get(f"/api/v1/follow-up-tasks/{task['task_id']}", headers=world.h("cc_a")).json()
    assert all(e["event_type"] != "contact_attempt" for e in detail["events"])


def test_contact_attempt_permissions_validation_and_closed_tasks(world):
    task = _task(world)
    url = f"/api/v1/follow-up-tasks/{task['task_id']}/contact-attempts"
    body = {"channel": "phone", "outcome": "reached"}
    assert client.post(url, headers=world.h("clin_a"), json=body).status_code == 403
    assert client.post(url, headers=world.h("patient_a"), json=body).status_code == 403
    assert client.post(url, headers=world.h("phm_b"), json=body).status_code == 404
    assert client.post(url, headers=world.h("cc_a"), json={"channel": "fax", "outcome": "reached"}).status_code == 422
    client.patch(f"/api/v1/follow-up-tasks/{task['task_id']}", headers=world.h("cc_a"), json={"status": "cancelled"})
    assert client.post(url, headers=world.h("cc_a"), json=body).status_code == 409


# --- summary and filters -------------------------------------------------------------------


def test_summary_counts_are_exact_and_scoped(world):
    overdue = _task(world, due_date=str(date.today() - timedelta(days=2)), priority="urgent")
    soon = _task(world, due_date=str(date.today() + timedelta(days=3)))
    later = _task(world, assigned_to_user_id=None)
    done = _task(world, due_date=None)
    client.patch(f"/api/v1/follow-up-tasks/{done['task_id']}", headers=world.h("cc_a"), json={"status": "cancelled"})
    client.post(f"/api/v1/follow-up-tasks/{soon['task_id']}/notes", headers=world.h("cc_a"),
                json={"text": "INTERNAL: secret"})
    s = client.get("/api/v1/follow-up-tasks/summary", headers=world.h("phm_a")).json()
    assert (s["total"], s["active"], s["overdue"], s["due_soon"], s["cancelled"]) == (4, 3, 1, 1, 1)
    assert s["unassigned_active"] == 1 and s["due_soon_days"] == 7
    assert s["by_status"]["cancelled"] == 1 and sum(s["by_status"].values()) == 4
    assert s["active_by_priority"] == {"routine": 2, "high": 0, "urgent": 1}
    cc = next(w for w in s["workload"] if w["assigned_to_user_id"] == world.users["cc_a"])
    assert (cc["active"], cc["overdue"], cc["due_soon"], cc["urgent"]) == (2, 1, 1, 1)
    assert any(w["assigned_to_user_id"] is None and w["active"] == 1 for w in s["workload"])
    assert s["recent_events"] and "secret" not in str(s) and "message" not in s["recent_events"][0]
    # Filters apply to the summary and the list alike.
    assert client.get("/api/v1/follow-up-tasks/summary?priority=urgent", headers=world.h("phm_a")).json()["total"] == 1
    un = client.get("/api/v1/follow-up-tasks?assigned_to=unassigned", headers=world.h("phm_a")).json()
    assert [t["task_id"] for t in un["items"]] == [later["task_id"]]
    act = client.get("/api/v1/follow-up-tasks?active=false", headers=world.h("phm_a")).json()
    assert [t["task_id"] for t in act["items"]] == [done["task_id"]]
    lst = client.get("/api/v1/follow-up-tasks", headers=world.h("phm_a")).json()["items"]
    assert next(t for t in lst if t["task_id"] == overdue["task_id"])["is_overdue"] is True
    assert next(t for t in lst if t["task_id"] == soon["task_id"])["is_due_soon"] is True
    # Other organization and patients see nothing.
    assert client.get("/api/v1/follow-up-tasks/summary", headers=world.h("phm_b")).json()["total"] == 0
    assert client.get("/api/v1/follow-up-tasks/summary", headers=world.h("patient_a")).status_code == 403
    assert client.get("/api/v1/follow-up-tasks/summary", headers=world.h("admin_a")).status_code == 403


def test_programme_region_and_due_window_filters(world):
    _task(world)
    general = _task(world, care_gap_id=None, message_key="general_check_in")
    ifhas = client.get("/api/v1/follow-up-tasks?pathway=ifhas", headers=world.h("cc_a")).json()
    assert ifhas["total"] == 1 and ifhas["items"][0]["rule_id"] == RULE_A
    assert client.get("/api/v1/follow-up-tasks?pathway=well_child", headers=world.h("cc_a")).json()["total"] == 0
    assert client.get(f"/api/v1/follow-up-tasks?region_id={world.region_a}",
                      headers=world.h("cc_a")).json()["total"] == 2
    other = next(r for r in {p["region_id"] for p in get_cached_dataset().patients} if r != world.region_a)
    assert client.get(f"/api/v1/follow-up-tasks?region_id={other}", headers=world.h("cc_a")).json()["total"] == 0
    window = client.get(f"/api/v1/follow-up-tasks?due_after={date.today()}&due_before={date.today() + timedelta(days=30)}",
                        headers=world.h("cc_a")).json()
    assert window["total"] == 2
    assert client.get(f"/api/v1/follow-up-tasks?due_before={date.today()}", headers=world.h("cc_a")).json()["total"] == 0
    assert general["rule_id"] is None


# --- care team -----------------------------------------------------------------------------


def test_care_team_lists_active_staff_of_own_organization_only(world):
    team = client.get("/api/v1/care-team", headers=world.h("cc_a")).json()["items"]
    ids = {m["user_id"] for m in team}
    assert ids == {world.users[a] for a in ("phm_a", "cc_a", "clin_a")}
    assert team[0]["is_self"] and team[0]["user_id"] == world.users["cc_a"]
    assert all("email" not in m for m in team) and all(m["can_be_assigned"] is None for m in team)
    flagged = client.get(f"/api/v1/care-team?patient_id={world.pid_a_unassigned}", headers=world.h("phm_a")).json()
    can = {m["user_id"]: m["can_be_assigned"] for m in flagged["items"]}
    assert can[world.users["phm_a"]] is True and can[world.users["cc_a"]] is False
    assert client.get(f"/api/v1/care-team?patient_id={world.pid_b}", headers=world.h("phm_a")).status_code == 404
    assert client.get("/api/v1/care-team", headers=world.h("patient_a")).status_code == 403


# --- service profiles and appointment filters ---------------------------------------------


def test_service_profiles_are_simulated_and_filterable(world):
    out = client.get("/api/v1/facility-service-profiles", headers=world.h("cc_a")).json()
    assert "not confirmed" in out["notice"] and out["items"]
    assert all(p["capability_basis"] == "simulated" for p in out["items"])
    wcv = client.get("/api/v1/facility-service-profiles?pathway=well_child", headers=world.h("cc_a")).json()["items"]
    assert all(p["offers_wcv"] for p in wcv)
    ifhas = client.get("/api/v1/facility-service-profiles?pathway=ifhas", headers=world.h("cc_a")).json()["items"]
    assert all(p["offers_ifhas"] for p in ifhas) and len(ifhas) < len(out["items"])


def test_appointment_filters_and_order(world):
    h = world.h("phm_a")
    all_ = client.get("/api/v1/appointments?limit=200", headers=h).json()
    times = [a["scheduled_datetime"] for a in all_["items"]]
    assert times == sorted(times, reverse=True)
    asc = client.get("/api/v1/appointments?limit=200&order=asc", headers=h).json()
    assert [a["appointment_id"] for a in asc["items"]] == [a["appointment_id"] for a in reversed(all_["items"])] or \
        [a["scheduled_datetime"] for a in asc["items"]] == sorted(times)
    active = client.get("/api/v1/appointments?limit=200&status_group=active", headers=h).json()
    assert all(a["status"] in ("scheduled", "rescheduled") for a in active["items"])
    cancelled = client.get("/api/v1/appointments?limit=200&status_group=cancelled", headers=h).json()
    assert all(a["status"].startswith("cancelled") for a in cancelled["items"])
    if all_["items"]:
        pivot = all_["items"][len(all_["items"]) // 2]["scheduled_datetime"]
        later = client.get("/api/v1/appointments", headers=h, params={"limit": 200, "scheduled_from": pivot}).json()
        earlier = client.get("/api/v1/appointments", headers=h, params={"limit": 200, "scheduled_to": pivot}).json()
        assert later["total"] + earlier["total"] == all_["total"]
        prof = all_["items"][0]["profile_id"]
        by_prof = client.get(f"/api/v1/appointments?limit=200&profile_id={prof}", headers=h).json()["items"]
        assert by_prof and all(a["profile_id"] == prof for a in by_prof)


# --- end-to-end coordination ---------------------------------------------------------------


def test_request_to_appointment_coordination_never_closes_the_gap(world):
    task = _task(world)
    ph, cc = world.h("patient_a"), world.h("cc_a")
    req = client.post(f"/api/v1/portal/follow-ups/{task['task_id']}/appointment-request", headers=ph,
                      json={"preferred_time_of_day": "morning", "preferred_dates": [str(date.today() + timedelta(days=9))]})
    assert req.status_code == 201
    rid = req.json()["request_id"]
    staff = client.get(f"/api/v1/patient-requests/{rid}", headers=cc).json()
    assert staff["care_gap_id"] == world.gap_a and staff["task_id"] == task["task_id"]
    profile = client.get("/api/v1/facility-service-profiles?pathway=ifhas", headers=cc).json()["items"][0]["profile_id"]
    when = datetime.now(timezone.utc).replace(microsecond=0, second=0, minute=0) + timedelta(days=9)
    apt = client.post("/api/v1/appointments", headers=cc, json={
        "patient_id": world.pid_a, "profile_id": profile, "care_gap_id": world.gap_a,
        "appointment_type": "ifhas_screening", "scheduled_datetime": when.isoformat(), "note": "from request"})
    assert apt.status_code == 201, apt.text
    apt_id = apt.json()["appointment_id"]
    upd = client.patch(f"/api/v1/patient-requests/{rid}", headers=cc, json={
        "status": "scheduled", "appointment_id": apt_id, "staff_response": "Booked for you.",
        "internal_note": "INTERNAL: chose morning"})
    assert upd.status_code == 200 and upd.json()["appointment_id"] == apt_id
    mine = client.get(f"/api/v1/portal/requests/{rid}", headers=ph).json()
    assert mine["status"] == "scheduled" and mine["staff_response"] == "Booked for you." and "INTERNAL" not in str(mine)
    assert any(a["appointment_id"] == apt_id for a in client.get("/api/v1/portal/appointments", headers=ph).json()["items"])
    # Attendance is recorded, but neither the appointment nor the request closes the gap.
    assert client.patch(f"/api/v1/appointments/{apt_id}", headers=cc, json={"status": "attended"}).status_code == 200
    assert client.get(f"/api/v1/care-gaps/{world.gap_a}", headers=cc).json()["status"] == "open"
    assert client.post(f"/api/v1/follow-up-tasks/{task['task_id']}/complete", headers=cc, json={}).status_code == 422
    history = client.get(f"/api/v1/appointments/{apt_id}/history", headers=cc).json()["items"]
    assert [h["to_status"] for h in history] == ["scheduled", "attended"]
    # Managers oversee but cannot schedule; other organizations cannot see the appointment.
    assert client.post("/api/v1/appointments", headers=world.h("phm_a"), json={
        "patient_id": world.pid_a, "profile_id": profile, "appointment_type": "other",
        "scheduled_datetime": when.isoformat()}).status_code == 403
    assert client.get(f"/api/v1/appointments/{apt_id}/history", headers=world.h("phm_b")).status_code == 404
