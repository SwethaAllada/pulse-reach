"""Organization isolation: Org A never reads, counts or changes Org B data (and vice versa)."""

from __future__ import annotations

import pytest

from app.repositories.read_repo import get_cached_dataset
from app.services.identity import directory
from app.services.identity.store import identity_session
from identity_fixtures import client, users_mode, world  # noqa: F401


def _dataset_counts(patient_ids):
    ds = get_cached_dataset()
    return {
        "patients": len(patient_ids),
        "gaps": sum(1 for g in ds.care_gaps if g["patient_id"] in patient_ids),
        "appointments": sum(1 for a in ds.appointments if a["patient_id"] in patient_ids),
        "referrals": sum(1 for r in ds.referrals if r["patient_id"] in patient_ids),
    }


def test_list_totals_and_pagination_only_cover_own_organization(world):
    a, b = _dataset_counts(set(world.patients_a)), _dataset_counts(set(world.patients_b))
    for alias, expected, own in (("phm_a", a, set(world.patients_a)), ("phm_b", b, set(world.patients_b))):
        h = world.h(alias)
        pats = client.get("/api/v1/patients?limit=200&offset=0", headers=h).json()
        assert pats["total"] == expected["patients"] and {p["patient_id"] for p in pats["items"]} <= own
        last = client.get(f"/api/v1/patients?limit=200&offset={max(0, expected['patients'] - 5)}", headers=h).json()
        assert len(last["items"]) == min(5, expected["patients"]) and {p["patient_id"] for p in last["items"]} <= own
        gaps = client.get("/api/v1/care-gaps?limit=200", headers=h).json()
        assert gaps["total"] == expected["gaps"] and {g["patient_id"] for g in gaps["items"]} <= own
        apts = client.get("/api/v1/appointments?limit=200", headers=h).json()
        assert apts["total"] == expected["appointments"] and {x["patient_id"] for x in apts["items"]} <= own
        refs = client.get("/api/v1/referrals?limit=200", headers=h).json()
        assert refs["total"] == expected["referrals"] and {x["patient_id"] for x in refs["items"]} <= own


def test_search_and_filters_cannot_reach_other_organization(world):
    h = world.h("phm_a")
    assert client.get(f"/api/v1/patients?q={world.pid_b}", headers=h).json()["total"] == 0
    assert client.get(f"/api/v1/care-gaps?patient_id={world.pid_b}", headers=h).json()["total"] == 0
    assert client.get(f"/api/v1/appointments?patient_id={world.pid_b}", headers=h).json()["total"] == 0
    assert client.get(f"/api/v1/referrals?patient_id={world.pid_b}", headers=h).json()["total"] == 0
    other_region = next(r for r in (1, 2, 3) if r != world.region_a)
    assert client.get(f"/api/v1/patients?region_id={other_region}", headers=h).json()["total"] == 0


def test_dashboard_and_insights_aggregate_only_own_patients(world):
    da = client.get("/api/v1/dashboard/summary", headers=world.h("phm_a")).json()
    db = client.get("/api/v1/dashboard/summary", headers=world.h("phm_b")).json()
    assert da["total_patients"] == len(world.patients_a) and db["total_patients"] == len(world.patients_b)
    assert da["n_adults"] + da["n_children"] == da["total_patients"]
    assert {r["region_id"] for r in da["region_breakdown"]} == {world.region_a}
    assert world.region_a not in {r["region_id"] for r in db["region_breakdown"]}
    a = _dataset_counts(set(world.patients_a))
    ds = get_cached_dataset()
    assert da["open_care_gaps_count"] == sum(
        1 for g in ds.care_gaps if g["patient_id"] in set(world.patients_a) and g["status"] == "open")
    assert a["gaps"] >= da["open_care_gaps_count"]
    ins = client.get("/api/v1/insights/population", headers=world.h("phm_a")).json()
    assert ins["facts"]["total_patients"] == len(world.patients_a)
    cc = client.get("/api/v1/dashboard/summary", headers=world.h("cc_a")).json()
    assert cc["total_patients"] == 1


@pytest.mark.parametrize("path", [
    "/api/v1/patients/{pid}", "/api/v1/patients/{pid}/evaluations", "/api/v1/patients/{pid}/history",
    "/api/v1/patients/{pid}/consents", "/api/v1/patients/{pid}/activity", "/api/v1/care-gaps/{gap}",
    "/api/v1/care-gaps/{gap}/follow-ups", "/api/v1/care-gaps/{gap}/reviews",
])
def test_cross_organization_ids_are_concealed_as_not_found(world, path):
    url = path.format(pid=world.pid_b, gap=world.gap_b)
    r = client.get(url, headers=world.h("phm_a"))
    assert r.status_code == 404
    missing = client.get(path.format(pid="SYNTH-PAT-999999", gap="SYNTH-GAP-999999"), headers=world.h("phm_a"))
    assert missing.status_code == 404
    # Same shape for "exists elsewhere" and "does not exist" (no existence oracle).
    assert r.json()["detail"].replace(world.pid_b, "X").replace(world.gap_b, "X") == \
        missing.json()["detail"].replace("SYNTH-PAT-999999", "X").replace("SYNTH-GAP-999999", "X")


def test_cross_organization_writes_are_refused_and_change_nothing(world):
    h = world.h("phm_a")
    before = client.get(f"/api/v1/care-gaps/{world.gap_b}/follow-ups", headers=world.h("phm_b")).json()["total"]
    assert client.post(f"/api/v1/care-gaps/{world.gap_b}/follow-ups", headers=h,
                       json={"event_type": "note_recorded", "note": "cross"}).status_code == 404
    assert client.post(f"/api/v1/care-gaps/{world.gap_b}/reviews", headers=h,
                       json={"action": "confirmed", "reason": "cross"}).status_code == 404
    assert client.get(f"/api/v1/care-gaps/{world.gap_b}/follow-ups", headers=world.h("phm_b")).json()["total"] == before
    assert client.get(f"/api/v1/care-gaps/{world.gap_b}/reviews", headers=world.h("phm_b")).json()["items"] == []
    ds = get_cached_dataset()
    created = client.post("/api/v1/appointments", headers=world.h("cc_b"), json={
        "patient_id": world.pid_b, "profile_id": "SYNTH-FSP-000001", "appointment_type": "ifhas_screening",
        "scheduled_datetime": "2026-12-02T09:00:00+00:00"})
    assert created.status_code == 201, created.text
    apt_b = next(a for a in ds.appointments if a["appointment_id"] == created.json()["appointment_id"])
    r = client.patch(f"/api/v1/appointments/{apt_b['appointment_id']}", headers=world.h("cc_a"),
                     json={"status": "attended"})
    assert r.status_code == 404 and apt_b["status"] == "scheduled"
    assert client.get(f"/api/v1/appointments/{apt_b['appointment_id']}/history",
                      headers=world.h("cc_a")).status_code == 404
    ref_b = next((x for x in ds.referrals if x["patient_id"] in set(world.patients_b)), None)
    if ref_b is not None:
        assert client.patch(f"/api/v1/referrals/{ref_b['referral_id']}", headers=world.h("cc_a"),
                            json={"status": "declined"}).status_code == 404
    apt = {"patient_id": world.pid_b, "profile_id": "SYNTH-FSP-000001", "appointment_type": "ifhas_screening",
           "scheduled_datetime": "2026-12-01T09:00:00+00:00"}
    assert client.post("/api/v1/appointments", headers=world.h("cc_a"), json=apt).status_code == 404


def test_ai_features_respect_organization_scope(world):
    body = {"patient_id": world.pid_b, "rule_id": "IFHAS-PKG-MAJOR-40-64"}
    assert client.post("/api/v1/explanations", headers=world.h("phm_a"), json=body).status_code == 404
    assert client.post("/api/v1/outreach/draft", headers=world.h("cc_a"),
                       json={**body, "channel": "phone"}).status_code == 404
    assert client.post("/api/v1/evaluations", headers=world.h("phm_a"),
                       json={"patient_id": world.pid_b, "look_ahead_days": 90}).status_code == 404
    # AI audit records carry the initiating user and organization and are filtered by organization.
    ok = client.post("/api/v1/explanations", headers=world.h("phm_a"),
                     json={"patient_id": world.pid_a, "rule_id": "IFHAS-PKG-MAJOR-40-64"})
    assert ok.status_code == 200
    client.get("/api/v1/insights/population", headers=world.h("phm_b"))
    audit_a = client.get("/api/v1/ai/audit", headers=world.h("admin_a")).json()["items"]
    audit_b = client.get("/api/v1/ai/audit", headers=world.h("admin_b")).json()["items"]
    assert audit_a and all(r["extra"]["organization_id"] == world.org_a for r in audit_a)
    assert audit_b and all(r["extra"]["organization_id"] == world.org_b for r in audit_b)
    explanation = next(r for r in audit_a if r["feature"] == "explanation")
    assert explanation["extra"]["actor_user_id"] == world.users["phm_a"]
    assert explanation["extra"]["actor_role"] == "POPULATION_HEALTH_MANAGER"


def test_outreach_draft_from_another_organization_cannot_be_reviewed(world):
    draft = client.post("/api/v1/outreach/draft", headers=world.h("cc_a"), json={
        "patient_id": world.pid_a, "rule_id": "IFHAS-PKG-MAJOR-40-64", "channel": "phone"}).json()
    review = {"draft_audit_id": draft["ai"]["audit_id"], "patient_id": world.pid_a,
              "rule_id": "IFHAS-PKG-MAJOR-40-64", "care_gap_id": draft["care_gap_id"], "channel": "phone",
              "language": "en", "decision": "rejected"}
    assert client.post("/api/v1/outreach/draft/review", headers=world.h("cc_b"), json=review).status_code == 404


def test_audit_events_are_organization_scoped(world):
    client.get(f"/api/v1/patients/{world.pid_a}", headers=world.h("patient_a"))  # denied, audited in A
    a = client.get("/api/v1/audit-events?limit=500", headers=world.h("admin_a")).json()
    b = client.get("/api/v1/audit-events?limit=500", headers=world.h("admin_b")).json()
    assert a["total"] > 0 and all(e["organization_id"] == world.org_a for e in a["items"])
    assert all(e["organization_id"] == world.org_b for e in b["items"])


def test_admin_users_and_assignments_are_organization_scoped(world):
    users_a = client.get("/api/v1/admin/users?limit=200", headers=world.h("admin_a")).json()
    assert world.users["cc_b"] not in {u["user_id"] for u in users_a["items"]}
    assert client.get(f"/api/v1/admin/users/{world.users['cc_b']}", headers=world.h("admin_a")).status_code == 404
    assert client.post(f"/api/v1/admin/users/{world.users['cc_b']}/deactivate",
                       headers=world.h("admin_a")).status_code == 404
    # Cannot assign a patient of another organization, or staff of another organization.
    assert client.post("/api/v1/admin/assignments", headers=world.h("phm_a"),
                       json={"staff_user_id": world.users["cc_a"], "patient_id": world.pid_b}).status_code == 404
    assert client.post("/api/v1/admin/assignments", headers=world.h("phm_a"),
                       json={"staff_user_id": world.users["cc_b"], "patient_id": world.pid_a}).status_code == 422


def test_patient_ownership_cannot_be_taken_from_another_organization(world):
    r = client.post("/api/v1/admin/patient-ownership", headers=world.h("admin_a"),
                    json={"patient_ids": [world.pid_b]})
    assert r.status_code == 409 and r.json()["error"]["message_key"] == "admin.patient_in_other_organization"
    with identity_session() as s:
        assert directory.patient_organization_id(s, world.pid_b) == world.org_b
    released = client.post("/api/v1/admin/patient-ownership/release", headers=world.h("admin_a"),
                           json={"patient_ids": [world.pid_b]})
    assert released.json()["released"] == 0


def test_releasing_a_patient_removes_all_access(world):
    assert client.get(f"/api/v1/patients/{world.pid_a}", headers=world.h("cc_a")).status_code == 200
    r = client.post("/api/v1/admin/patient-ownership/release", headers=world.h("admin_a"),
                    json={"patient_ids": [world.pid_a]})
    assert r.json()["released"] == 1
    assert client.get(f"/api/v1/patients/{world.pid_a}", headers=world.h("phm_a")).status_code == 404
    world._tokens.clear()
    assert client.get("/api/v1/portal/summary", headers=world.h("patient_a")).status_code == 404


def test_follow_up_tasks_and_requests_are_isolated(world):
    t = client.post("/api/v1/follow-up-tasks", headers=world.h("cc_a"),
                    json={"patient_id": world.pid_a, "care_gap_id": world.gap_a}).json()
    assert client.get(f"/api/v1/follow-up-tasks/{t['task_id']}", headers=world.h("phm_b")).status_code == 404
    assert client.get("/api/v1/follow-up-tasks", headers=world.h("phm_b")).json()["total"] == 0
    assert client.post("/api/v1/follow-up-tasks", headers=world.h("cc_a"),
                       json={"patient_id": world.pid_b}).status_code == 404
    req = client.post("/api/v1/portal/assistance", headers=world.h("patient_a"), json={"message": "help"}).json()
    assert client.get(f"/api/v1/patient-requests/{req['request_id']}", headers=world.h("phm_b")).status_code == 404
    assert client.get("/api/v1/patient-requests", headers=world.h("phm_b")).json()["total"] == 0
    assert client.get("/api/v1/patient-requests", headers=world.h("phm_a")).json()["total"] == 1
