"""Role-based access control: every route declares a permission, every role meets the matrix."""

from __future__ import annotations

import re

import pytest
from fastapi.routing import APIRoute

from app.core.permissions import ROLE_PERMISSIONS, Role, permissions_for
from app.main import app
from identity_fixtures import client, users_mode, world  # noqa: F401

ROLES = ("admin_a", "phm_a", "cc_a", "clin_a", "patient_a")
PUBLIC = {"/api/v1/auth/login", "/api/v1/auth/register", "/api/v1/auth/refresh",
          "/api/v1/auth/password-reset/request", "/api/v1/auth/password-reset/confirm"}


def _markers(dependant) -> set[str]:
    found: set[str] = set()
    for dep in dependant.dependencies:
        found |= set(getattr(dep.call, "__pulsereach_permissions__", ()))
        found |= _markers(dep)
    return found


def _api_routes():
    return [r for r in app.routes if isinstance(r, APIRoute) and r.path.startswith("/api/v1")]


def test_every_api_route_declares_a_permission_or_is_explicitly_public():
    missing = [f"{sorted(r.methods)} {r.path}" for r in _api_routes() if not _markers(r.dependant)]
    assert missing == []
    public = {r.path for r in _api_routes() if "public" in _markers(r.dependant)}
    assert public == PUBLIC


@pytest.mark.parametrize("route", [r for r in _api_routes() if r.path not in PUBLIC],
                         ids=lambda r: f"{'/'.join(sorted(r.methods))} {r.path}")
def test_every_protected_route_requires_authentication(users_mode, route):
    path = re.sub(r"\{[^}]+\}", "SYNTH-X-000001", route.path)
    for method in route.methods - {"HEAD", "OPTIONS"}:
        r = client.request(method, path, json={})
        assert r.status_code == 401, (method, path, r.status_code, r.text)


def test_permission_matrix_invariants():
    assert not {p for p in ROLE_PERMISSIONS[Role.SYSTEM_ADMIN] if p.startswith(("patients.", "care_gaps.",
                                                                                  "evaluations."))}
    assert ROLE_PERMISSIONS[Role.PATIENT] == {"patients.read_self", "followups.respond",
                                              "patient_requests.create", "facilities.read"}
    assert "patients.read" not in permissions_for("CARE_COORDINATOR")
    assert "patients.read" in permissions_for("CARE_COORDINATOR", "organization")
    assert "patients.read" not in permissions_for("PATIENT", "organization")
    assert "outreach.review" not in permissions_for("CLINICIAN") | permissions_for("PATIENT")


# (method, path template, body, expected per role: admin, phm, coordinator, clinician, patient)
MATRIX = [
    ("get", "/api/v1/dashboard/summary", None, (403, 200, 200, 200, 403)),
    ("get", "/api/v1/patients?limit=1", None, (403, 200, 200, 200, 403)),
    ("get", "/api/v1/patients/{pid_a}", None, (403, 200, 200, 200, 403)),
    ("get", "/api/v1/patients/{pid_a}/evaluations", None, (403, 200, 200, 200, 403)),
    ("get", "/api/v1/patients/{pid_a}/history", None, (403, 200, 200, 200, 403)),
    ("get", "/api/v1/patients/{pid_a}/consents", None, (403, 200, 200, 200, 403)),
    ("get", "/api/v1/patients/{pid_a}/activity", None, (403, 200, 200, 200, 403)),
    ("post", "/api/v1/evaluations", {"patient_id": "{pid_a}", "look_ahead_days": 90}, (403, 200, 403, 200, 403)),
    ("get", "/api/v1/rules", None, (200, 200, 200, 200, 403)),
    ("get", "/api/v1/open-questions", None, (200, 200, 200, 200, 403)),
    ("get", "/api/v1/facilities?limit=1", None, (200, 200, 200, 200, 200)),
    ("get", "/api/v1/care-gaps?limit=1", None, (403, 200, 200, 200, 403)),
    ("get", "/api/v1/care-gaps/{gap_a}", None, (403, 200, 200, 200, 403)),
    ("get", "/api/v1/care-gaps/{gap_a}/follow-ups", None, (403, 200, 200, 200, 403)),
    ("get", "/api/v1/care-gaps/{gap_a}/reviews", None, (403, 200, 200, 200, 403)),
    ("post", "/api/v1/care-gaps/{gap_a}/reviews", {"action": "confirmed", "reason": "matrix"},
     (403, 201, 201, 201, 403)),
    ("post", "/api/v1/care-gaps/{gap_a}/follow-ups", {"event_type": "note_recorded", "note": "matrix"},
     (403, 201, 201, 201, 403)),
    ("post", "/api/v1/explanations", {"patient_id": "{pid_a}", "rule_id": "IFHAS-PKG-MAJOR-40-64"},
     (403, 200, 200, 200, 403)),
    ("post", "/api/v1/outreach/preview", {"patient_id": "{pid_a}", "rule_id": "IFHAS-PKG-MAJOR-40-64",
                                          "channel": "phone"}, (403, 403, 200, 403, 403)),
    ("post", "/api/v1/outreach/draft", {"patient_id": "{pid_a}", "rule_id": "IFHAS-PKG-MAJOR-40-64",
                                        "channel": "phone"}, (403, 403, 200, 403, 403)),
    ("post", "/api/v1/outreach/draft/review", {"draft_audit_id": "x", "patient_id": "{pid_a}",
                                               "rule_id": "IFHAS-PKG-MAJOR-40-64", "care_gap_id": "{gap_a}",
                                               "channel": "phone", "language": "en", "decision": "rejected"},
     (403, 403, 404, 403, 403)),
    ("get", "/api/v1/insights/population", None, (403, 200, 200, 200, 403)),
    ("get", "/api/v1/ai/status", None, (200, 200, 200, 200, 403)),
    ("get", "/api/v1/ai/audit", None, (200, 403, 403, 403, 403)),
    ("get", "/api/v1/appointments?limit=1", None, (403, 200, 200, 200, 403)),
    ("get", "/api/v1/referrals?limit=1", None, (403, 200, 200, 200, 403)),
    ("get", "/api/v1/admin/users", None, (200, 403, 403, 403, 403)),
    ("get", "/api/v1/admin/organizations", None, (200, 403, 403, 403, 403)),
    ("get", "/api/v1/admin/assignments", None, (200, 200, 403, 403, 403)),
    ("get", "/api/v1/admin/assignments/staff", None, (200, 200, 403, 403, 403)),
    ("get", "/api/v1/admin/patient-links", None, (200, 403, 403, 403, 403)),
    ("get", "/api/v1/audit-events", None, (200, 403, 403, 403, 403)),
    ("get", "/api/v1/follow-up-tasks", None, (403, 200, 200, 200, 403)),
    ("get", "/api/v1/follow-up-tasks/summary", None, (403, 200, 200, 200, 403)),
    ("get", "/api/v1/care-team", None, (403, 200, 200, 200, 403)),
    ("get", "/api/v1/facility-service-profiles", None, (200, 200, 200, 200, 200)),
    ("post", "/api/v1/follow-up-tasks", {"patient_id": "{pid_a}", "priority": "high"}, (403, 201, 201, 201, 403)),
    ("get", "/api/v1/patient-requests", None, (403, 200, 200, 403, 403)),
    ("post", "/api/v1/patients/{pid_a}/portal-invitations", None, (403, 201, 201, 403, 403)),
    ("get", "/api/v1/portal/summary", None, (403, 403, 403, 403, 200)),
    ("get", "/api/v1/portal/recommendations", None, (403, 403, 403, 403, 200)),
    ("get", "/api/v1/me", None, (200, 200, 200, 200, 200)),
]


def _fill(value, w):
    if isinstance(value, str):
        return value.replace("{pid_a}", w.pid_a).replace("{gap_a}", w.gap_a)
    if isinstance(value, dict):
        return {k: _fill(v, w) for k, v in value.items()}
    return value


@pytest.mark.parametrize("method,path,body,expected", MATRIX, ids=[f"{m} {p}" for m, p, _, _ in MATRIX])
def test_role_permission_matrix(world, method, path, body, expected):
    got = []
    for role in ROLES:
        r = client.request(method, _fill(path, world), json=_fill(body, world), headers=world.h(role))
        got.append(r.status_code)
    assert tuple(got) == expected, dict(zip(ROLES, got))


def test_patient_cannot_use_staff_or_admin_endpoints(world):
    h = world.h("patient_a")
    for method, path in [("get", f"/api/v1/patients/{world.pid_a}"), ("get", "/api/v1/care-gaps"),
                         ("get", "/api/v1/dashboard/summary"), ("get", "/api/v1/audit-events"),
                         ("get", "/api/v1/ai/audit"), ("post", "/api/v1/admin/users"),
                         ("get", "/api/v1/follow-up-tasks")]:
        assert client.request(method, path, headers=h, json={}).status_code == 403, path


def test_staff_cannot_perform_admin_actions(world):
    for role in ("phm_a", "cc_a", "clin_a"):
        h = world.h(role)
        assert client.post("/api/v1/admin/users", headers=h, json={
            "email": f"x.{role}@test.pulsereach.invalid", "full_name": "X", "role": "CLINICIAN"}).status_code == 403
        assert client.post(f"/api/v1/admin/users/{world.users['cc_a']}/deactivate", headers=h).status_code == 403
        assert client.post("/api/v1/admin/organizations", headers=h,
                           json={"name": "Rogue", "slug": f"rogue-{role.replace('_', '')}"}).status_code == 403


def test_admin_cannot_escalate_self_or_create_patients(world):
    r = client.patch(f"/api/v1/admin/users/{world.users['admin_a']}", headers=world.h("admin_a"),
                     json={"role": "POPULATION_HEALTH_MANAGER"})
    assert r.status_code == 403
    r = client.post("/api/v1/admin/users", headers=world.h("admin_a"),
                    json={"email": "p@test.pulsereach.invalid", "full_name": "P", "role": "PATIENT"})
    assert r.status_code == 422


def test_coordinator_limited_to_assigned_patients(world):
    h = world.h("cc_a")
    lst = client.get("/api/v1/patients?limit=200", headers=h).json()
    assert lst["total"] == 1 and [p["patient_id"] for p in lst["items"]] == [world.pid_a]
    other = world.pid_a_unassigned
    for path in (f"/api/v1/patients/{other}", f"/api/v1/patients/{other}/history",
                 f"/api/v1/patients/{other}/evaluations", f"/api/v1/patients/{other}/activity"):
        r = client.get(path, headers=h)
        assert r.status_code == 404 and r.json()["detail"] == f"Synthetic patient '{other}' not found", path
    gaps = client.get("/api/v1/care-gaps?limit=200", headers=h).json()
    assert gaps["total"] > 0 and {g["patient_id"] for g in gaps["items"]} == {world.pid_a}


def test_ending_an_assignment_removes_access(world):
    assignments = client.get(f"/api/v1/admin/assignments?staff_user_id={world.users['cc_a']}",
                             headers=world.h("phm_a")).json()["items"]
    assert client.get(f"/api/v1/patients/{world.pid_a}", headers=world.h("cc_a")).status_code == 200
    end = client.post(f"/api/v1/admin/assignments/{assignments[0]['assignment_id']}/end", headers=world.h("phm_a"))
    assert end.status_code == 200 and end.json()["is_active"] is False
    assert client.get(f"/api/v1/patients/{world.pid_a}", headers=world.h("cc_a")).status_code == 404


def test_clinician_scope_and_explicit_organization_grant(world):
    other = world.pid_a_unassigned
    assert client.get(f"/api/v1/patients/{other}", headers=world.h("clin_a")).status_code == 404
    client.post("/api/v1/admin/assignments", headers=world.h("phm_a"),
                json={"staff_user_id": world.users["clin_a"], "patient_id": other})
    assert client.get(f"/api/v1/patients/{other}", headers=world.h("clin_a")).status_code == 200
    # Broader access only through an explicit grant (and it ends the current sessions).
    r = client.patch(f"/api/v1/admin/users/{world.users['clin_a']}", headers=world.h("admin_a"),
                     json={"patient_access": "organization"})
    assert r.status_code == 200
    world._tokens.pop("clin_a")
    total = client.get("/api/v1/patients?limit=1", headers=world.h("clin_a")).json()["total"]
    assert total == len(world.patients_a)


def test_documented_completion_requires_care_gaps_complete(world):
    body = {"event_type": "completion_documented", "close_gap": True, "documented_evidence": True,
            "evidence_reference": "SYNTH-REF-000001"}
    r = client.post(f"/api/v1/care-gaps/{world.gap_a}/follow-ups", headers=world.h("phm_a"), json=body)
    assert r.status_code == 403


def test_patients_cannot_review_outreach_drafts(world):
    draft = client.post("/api/v1/outreach/draft", headers=world.h("cc_a"), json={
        "patient_id": world.pid_a, "rule_id": "IFHAS-PKG-MAJOR-40-64", "channel": "phone"}).json()
    assert draft["allowed"] is True
    review = {"draft_audit_id": draft["ai"]["audit_id"], "patient_id": world.pid_a,
              "rule_id": "IFHAS-PKG-MAJOR-40-64", "care_gap_id": draft["care_gap_id"], "channel": "phone",
              "language": "en", "decision": "approved", "final_message": draft["draft_body"]}
    for role in ("patient_a", "clin_a", "phm_a", "admin_a"):
        assert client.post("/api/v1/outreach/draft/review", headers=world.h(role), json=review).status_code == 403
    ok = client.post("/api/v1/outreach/draft/review", headers=world.h("cc_a"), json=review)
    assert ok.status_code == 200 and ok.json()["review_status"] == "approved"
    assert ok.json()["simulated_outreach_status"] == "simulated_not_sent" and ok.json()["delivered"] is False


def test_frontend_role_fixture_matches_the_backend_matrix():
    """The frontend role tests (`frontend/test/role-permissions.json`) use the real matrix."""
    import json
    from pathlib import Path

    from app.core.permissions import DEFAULT_PATIENT_ACCESS

    fixture = Path(__file__).resolve().parents[2] / "frontend" / "test" / "role-permissions.json"
    if not fixture.exists():
        pytest.skip("frontend fixtures are not part of this checkout")
    expected = {r.value: sorted(permissions_for(r.value, a)) for r, a in DEFAULT_PATIENT_ACCESS.items()}
    assert json.loads(fixture.read_text()) == expected


def test_assignment_staff_directory_is_minimal_scoped_and_eligible_only(world):
    """`GET /admin/assignments/staff` (assignments.manage): who can be assigned patients, nothing more."""
    r = client.get("/api/v1/admin/assignments/staff", headers=world.h("phm_a"))
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert items and all(set(i) == {"user_id", "full_name", "role"} for i in items)
    ids = {i["user_id"] for i in items}
    assert {world.users[a] for a in ("phm_a", "cc_a", "clin_a")} <= ids
    # Never: administrators or patients (not assignable), other organizations' staff.
    assert not ids & {world.users[a] for a in ("admin_a", "patient_a", "admin_b", "phm_b", "cc_b")}
    assert {i["role"] for i in items} <= {"POPULATION_HEALTH_MANAGER", "CARE_COORDINATOR", "CLINICIAN"}
    assert "@" not in r.text  # no e-mail addresses
    # Organization B sees only its own staff.
    ids_b = {i["user_id"] for i in client.get("/api/v1/admin/assignments/staff", headers=world.h("phm_b")).json()["items"]}
    assert world.users["cc_b"] in ids_b and not ids_b & ids
    # Deactivated staff drop out of the directory.
    assert client.post(f"/api/v1/admin/users/{world.users['clin_a']}/deactivate", headers=world.h("admin_a")).status_code == 200
    after = {i["user_id"] for i in client.get("/api/v1/admin/assignments/staff", headers=world.h("phm_a")).json()["items"]}
    assert world.users["clin_a"] not in after


def test_manager_gets_assignment_staff_but_not_user_administration(world):
    h = world.h("phm_a")
    assert client.get("/api/v1/admin/assignments/staff", headers=h).status_code == 200
    assert client.get("/api/v1/admin/users", headers=h).status_code == 403
    assert client.get(f"/api/v1/admin/users/{world.users['cc_a']}", headers=h).status_code == 403
    assert "users.read" not in permissions_for("POPULATION_HEALTH_MANAGER", "organization")
    admin = world.h("admin_a")
    assert client.get("/api/v1/admin/users?limit=200", headers=admin).status_code == 200
    assert client.get("/api/v1/admin/assignments/staff", headers=admin).status_code == 200


def test_assignments_still_validate_assignees(world):
    h = world.h("phm_a")
    ok = client.post("/api/v1/admin/assignments", headers=h,
                     json={"staff_user_id": world.users["clin_a"], "patient_id": world.pid_a_unassigned})
    assert ok.status_code == 201, ok.text
    for alias in ("admin_a", "patient_a"):  # listed nowhere in the directory, refused by the API too
        r = client.post("/api/v1/admin/assignments", headers=h,
                        json={"staff_user_id": world.users[alias], "patient_id": world.pid_a_unassigned})
        assert r.status_code == 422, (alias, r.text)
    end = client.post(f"/api/v1/admin/assignments/{ok.json()['assignment_id']}/end", headers=h)
    assert end.status_code == 200 and end.json()["is_active"] is False
