"""Shared fixtures for AUTH_MODE=users tests (memory mode, in-process identity store).

`world` builds two organizations that split the synthetic population by region:
- org A owns the region of SYNTH-PAT-000001 (PID_A); org B owns every other region;
- one user per role in A (admin, manager, coordinator, clinician, patient) and admin/manager/
  coordinator in B; coordinators/clinicians are assigned only to specific patients;
- the A patient account is linked to PID_A through the real invitation + date-of-birth workflow.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.rate_limit import reset_rate_limits
from app.main import app
from app.repositories.followup_repo import reset_memory_writes
from app.repositories.read_repo import get_cached_dataset, get_cached_index
from app.services.ai import get_ai_service
from app.services.identity import directory
from app.services.identity import service as auth
from app.services.identity.store import identity_session, reset_identity_store

PW = "Synthetic-Test-Passphrase-9"
PID_A = "SYNTH-PAT-000001"
RULE_A = "IFHAS-PKG-MAJOR-40-64"
client = TestClient(app)


@dataclass
class World:
    org_a: str
    org_b: str
    users: dict[str, str]  # alias -> user_id
    emails: dict[str, str]
    pid_a: str
    pid_a_unassigned: str
    pid_b: str
    gap_a: str
    gap_b: str
    region_a: int
    patients_a: list[str] = field(default_factory=list)
    patients_b: list[str] = field(default_factory=list)
    _tokens: dict[str, dict] = field(default_factory=dict)

    def login(self, alias: str, **extra) -> dict:
        r = client.post("/api/v1/auth/login", json={"email": self.emails[alias], "password": PW, **extra})
        assert r.status_code == 200, r.text
        self._tokens[alias] = r.json()
        return r.json()

    def h(self, alias: str, **headers) -> dict:
        tok = self._tokens.get(alias) or self.login(alias)
        return {"Authorization": f"Bearer {tok['access_token']}", **headers}


def _make_user(s, email: str, role: str | None, org: str | None, patient_access: str | None = None) -> str:
    u = auth.create_user(s, email=email, full_name=f"Test {email.split('@')[0]}", password=PW)
    if role is not None:
        directory.add_membership(s, user_id=u.user_id, organization_id=org, role=role,
                                 patient_access=patient_access, created_by=None)
    return u.user_id


def build_world() -> World:
    ds = get_cached_dataset()
    idx = get_cached_index()
    region_a = idx.patients_by_id[PID_A]["region_id"]
    patients_a = sorted(p["patient_id"] for p in ds.patients if p["region_id"] == region_a)
    patients_b = sorted(p["patient_id"] for p in ds.patients if p["region_id"] != region_a)

    def open_gap(pid):
        return next((g["care_gap_id"] for g in idx.care_gaps_by_patient.get(pid, []) if g["status"] == "open"), None)

    pid_b = next(pid for pid in patients_b if open_gap(pid) and idx.patients_by_id[pid]["date_of_birth"])
    pid_a_unassigned = next(pid for pid in patients_a if pid != PID_A and open_gap(pid))
    gap_a = next(g["care_gap_id"] for g in idx.care_gaps_by_patient[PID_A]
                 if g["status"] == "open" and g["rule_id"] == RULE_A)
    users: dict[str, str] = {}
    emails: dict[str, str] = {}
    with identity_session() as s:
        org_a = directory.create_organization(s, name="Test Org A (synthetic)", slug="test-org-a", created_by=None)
        org_b = directory.create_organization(s, name="Test Org B (synthetic)", slug="test-org-b", created_by=None)
        directory.associate_patients(s, organization_id=org_a.organization_id, patient_ids=patients_a, created_by=None)
        directory.associate_patients(s, organization_id=org_b.organization_id, patient_ids=patients_b, created_by=None)
        spec = [
            ("admin_a", "SYSTEM_ADMIN", org_a), ("phm_a", "POPULATION_HEALTH_MANAGER", org_a),
            ("cc_a", "CARE_COORDINATOR", org_a), ("clin_a", "CLINICIAN", org_a),
            ("admin_b", "SYSTEM_ADMIN", org_b), ("phm_b", "POPULATION_HEALTH_MANAGER", org_b),
            ("cc_b", "CARE_COORDINATOR", org_b), ("patient_a", None, None), ("outsider", None, None),
        ]
        for alias, role, org in spec:
            emails[alias] = f"{alias.replace('_', '.')}@test.pulsereach.invalid"
            users[alias] = _make_user(s, emails[alias], role, org.organization_id if org else None)
        for staff in ("cc_a", "clin_a"):
            directory.create_assignment(s, organization_id=org_a.organization_id, staff_user_id=users[staff],
                                        patient_id=PID_A, created_by=users["phm_a"])
        directory.create_assignment(s, organization_id=org_b.organization_id, staff_user_id=users["cc_b"],
                                    patient_id=pid_b, created_by=users["phm_b"])
        _, code = directory.create_invitation(s, organization_id=org_a.organization_id, patient_id=PID_A,
                                              created_by=users["cc_a"])
    with identity_session() as s:
        directory.redeem_invitation(s, user_id=users["patient_a"], code=code,
                                    date_of_birth=idx.patients_by_id[PID_A]["date_of_birth"],
                                    patient_dob_lookup=lambda pid: idx.patients_by_id[pid]["date_of_birth"])
    return World(org_a=org_a.organization_id, org_b=org_b.organization_id, users=users, emails=emails,
                 pid_a=PID_A, pid_a_unassigned=pid_a_unassigned, pid_b=pid_b, gap_a=gap_a,
                 gap_b=open_gap(pid_b), region_a=region_a, patients_a=patients_a, patients_b=patients_b)


@pytest.fixture
def users_mode(monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", "users")
    reset_identity_store()
    reset_rate_limits()
    reset_memory_writes()
    get_ai_service().audit.clear()
    yield
    reset_identity_store()
    reset_rate_limits()
    reset_memory_writes()
    get_ai_service().audit.clear()
    get_cached_index.cache_clear()
    get_cached_dataset.cache_clear()


@pytest.fixture
def world(users_mode) -> World:
    return build_world()
