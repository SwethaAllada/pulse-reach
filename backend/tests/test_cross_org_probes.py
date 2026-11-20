"""Adversarial organization-isolation probes (Phase 6): identifier tampering on list filters,
task mutations, mixed-ownership writes, cross-organization assignees and the patient portal.
Complements test_tenant_isolation.py (users mode, memory data source)."""

from __future__ import annotations

import pytest

from app.repositories.read_repo import get_cached_dataset, get_cached_index
from identity_fixtures import RULE_A, client, users_mode, world  # noqa: F401


def _task(w, alias="cc_a", **body):
    r = client.post("/api/v1/follow-up-tasks", headers=w.h(alias),
                    json={"patient_id": w.pid_a, "care_gap_id": w.gap_a, **body})
    assert r.status_code == 201, r.text
    return r.json()


@pytest.mark.parametrize("path", [
    "/api/v1/care-gaps?patient_id={pid_b}",
    "/api/v1/appointments?patient_id={pid_b}",
    "/api/v1/referrals?patient_id={pid_b}",
    "/api/v1/follow-up-tasks?patient_id={pid_b}",
    "/api/v1/patient-requests?patient_id={pid_b}",
    "/api/v1/appointments?care_gap_id={gap_b}",
    "/api/v1/patients?q={pid_b}",
])
def test_list_filters_with_foreign_ids_return_nothing(world, path):
    r = client.get(path.format(pid_b=world.pid_b, gap_b=world.gap_b), headers=world.h("phm_a"))
    assert r.status_code == 200, r.text
    assert r.json()["total"] == 0


def test_task_summary_and_care_team_do_not_leak_other_organizations(world):
    _task(world, "cc_b", patient_id=world.pid_b, care_gap_id=world.gap_b)
    s = client.get("/api/v1/follow-up-tasks/summary", headers=world.h("phm_a")).json()
    assert s["total"] == 0 and s["workload"] == [] and s["recent_events"] == []
    assert client.get(f"/api/v1/care-team?patient_id={world.pid_b}", headers=world.h("phm_a")).status_code == 404
    team = client.get("/api/v1/care-team", headers=world.h("phm_a")).json()["items"]
    b_users = {world.users[a] for a in ("admin_b", "phm_b", "cc_b")}
    assert team and not {m["user_id"] for m in team} & b_users


@pytest.mark.parametrize("method,suffix,body", [
    ("patch", "", {"status": "in_progress"}),
    ("post", "/contact-attempts", {"channel": "phone", "outcome": "no_answer"}),
    ("post", "/notes", {"text": "cross-organization probe"}),
    ("post", "/escalate", {"reason": "probe"}),
    ("post", "/complete", {}),
])
def test_foreign_task_mutations_are_concealed_and_change_nothing(world, method, suffix, body):
    t = _task(world, "cc_b", patient_id=world.pid_b, care_gap_id=world.gap_b)
    url = f"/api/v1/follow-up-tasks/{t['task_id']}"
    for alias in ("phm_a", "cc_a", "clin_a"):
        r = client.request(method, url + suffix, headers=world.h(alias), json=body)
        assert r.status_code in (403, 404), (alias, r.status_code)
    after = client.get(url, headers=world.h("cc_b")).json()
    assert after["status"] == t["status"] and len(after["events"]) == len(t["events"])


def test_tasks_cannot_be_assigned_to_staff_of_another_organization(world):
    r = client.post("/api/v1/follow-up-tasks", headers=world.h("phm_a"),
                    json={"patient_id": world.pid_a, "assigned_to_user_id": world.users["cc_b"]})
    assert r.status_code == 422
    t = _task(world, "phm_a")
    r = client.patch(f"/api/v1/follow-up-tasks/{t['task_id']}", headers=world.h("phm_a"),
                     json={"assigned_to_user_id": world.users["cc_b"]})
    assert r.status_code == 422


def test_own_patient_cannot_be_linked_to_a_foreign_care_gap(world):
    h = world.h("cc_a")
    assert client.post("/api/v1/follow-up-tasks", headers=h,
                       json={"patient_id": world.pid_a, "care_gap_id": world.gap_b}).status_code == 422
    apt = {"patient_id": world.pid_a, "profile_id": "SYNTH-FSP-000001", "care_gap_id": world.gap_b,
           "appointment_type": "ifhas_screening", "scheduled_datetime": "2026-12-03T09:00:00+00:00"}
    assert client.post("/api/v1/appointments", headers=h, json=apt).status_code == 404
    ref = {"patient_id": world.pid_a, "care_gap_id": world.gap_b, "trigger_rule_id": RULE_A,
           "trigger_rule_version": "1", "referral_target": "probe"}
    assert client.post("/api/v1/referrals", headers=h, json=ref).status_code in (404, 422)


def test_outreach_and_explanations_refuse_foreign_and_unassigned_patients(world):
    body = {"rule_id": RULE_A, "channel": "phone"}
    for pid in (world.pid_b, world.pid_a_unassigned):
        for path in ("/api/v1/outreach/preview", "/api/v1/outreach/draft"):
            assert client.post(path, headers=world.h("cc_a"), json={**body, "patient_id": pid}).status_code == 404
        assert client.post("/api/v1/explanations", headers=world.h("clin_a"),
                           json={"patient_id": pid, "rule_id": RULE_A}).status_code == 404


def test_patient_portal_cannot_reach_other_patients_by_id(world):
    idx = get_cached_index()
    ds = get_cached_dataset()
    other_gap = next(g["care_gap_id"] for g in idx.care_gaps_by_patient[world.pid_a_unassigned])
    other_apt = next(a["appointment_id"] for a in ds.appointments if a["patient_id"] != world.pid_a)
    other_ref = next(r["referral_id"] for r in ds.referrals if r["patient_id"] != world.pid_a)
    t = _task(world, "phm_a", patient_id=world.pid_a_unassigned, care_gap_id=None)
    h = world.h("patient_a")
    paths = [f"/api/v1/portal/follow-ups/{t['task_id']}", f"/api/v1/portal/follow-ups/{t['task_id']}/history",
             f"/api/v1/portal/recommendations/{other_gap}", f"/api/v1/portal/recommendations/{other_gap}/explanation",
             f"/api/v1/portal/appointments/{other_apt}", f"/api/v1/portal/referrals/{other_ref}"]
    for path in paths:
        assert client.get(path, headers=h).status_code == 404, path
    r = client.post(f"/api/v1/portal/follow-ups/{t['task_id']}/responses", headers=h,
                    json={"response_type": "acknowledged"})
    assert r.status_code in (404, 422)
