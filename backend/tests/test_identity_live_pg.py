"""Identity, RBAC, isolation, portal and audit on a disposable PostgreSQL database (DATA_SOURCE=db).

Migrates a scratch database to head (incl. 0011), loads official + synthetic data, seeds the demo
organizations through the real CLI code path, then exercises the API in AUTH_MODE=users.
"""

from __future__ import annotations

import argparse
import os

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import DBAPIError

from app.core.config import Settings, settings
from app.core.rate_limit import reset_rate_limits
from app.main import app
from app.models.identity import identity_metadata
from app.services.ai import build_ai_service, get_ai_service
from app.services.identity.store import get_identity_engine

pytestmark = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set")
PW = "Live-Demo-Passphrase-42"
client = TestClient(app)


def _cfg(allow_data_loss: bool = False):
    from test_official_integrity import alembic_config

    cfg = alembic_config()
    if allow_data_loss:
        cfg.cmd_opts = argparse.Namespace(x=["allow_data_loss=true"])
    return cfg


@pytest.fixture(scope="module")
def pg():
    from test_live_backend_completion import _seed
    from test_official_integrity import scratch_database

    from app.services.identity import demo

    with scratch_database() as url:
        command.upgrade(_cfg(), "head")
        eng = create_engine(url)
        _seed(eng)
        mp = pytest.MonkeyPatch()
        mp.setattr(settings, "data_source", "db")
        mp.setattr(settings, "auth_mode", "users")
        get_identity_engine.cache_clear()
        ai = build_ai_service(Settings(data_source="db", llm_enabled=False))
        app.dependency_overrides[get_ai_service] = lambda: ai
        accounts = {(a.organization_slug, a.role): a for a in demo.seed_demo(lambda _e: PW)}
        assert demo.seed_demo(lambda _e: PW)  # idempotent
        try:
            yield eng, accounts
        finally:
            app.dependency_overrides.pop(get_ai_service, None)
            mp.undo()
            get_identity_engine.cache_clear()
            eng.dispose()


def _h(accounts, org: str, role: str) -> dict:
    reset_rate_limits()
    r = client.post("/api/v1/auth/login", json={"email": accounts[(org, role)].email, "password": PW})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_migration_matches_identity_models(pg):
    eng, _ = pg
    insp = inspect(eng)
    for table in identity_metadata.sorted_tables:
        cols = {c["name"]: c["nullable"] for c in insp.get_columns(table.name, schema=table.schema)}
        assert cols == {c.name: c.nullable for c in table.columns}, table.fullname
    assert insp.get_table_names(schema="public") == ["alembic_version"]


def test_audit_history_is_append_only(pg):
    eng, accounts = pg
    _h(accounts, "demo-org-a", "SYSTEM_ADMIN")  # produces at least one audit event
    for stmt in ("UPDATE identity.audit_event SET outcome = 'success'", "DELETE FROM identity.audit_event",
                 "TRUNCATE identity.audit_event"):
        with eng.connect() as c, pytest.raises(DBAPIError, match="append-only"):
            c.execute(text(stmt))


def test_scoped_reads_and_cross_org_concealment_in_db_mode(pg):
    eng, accounts = pg
    mgr_a, mgr_b = _h(accounts, "demo-org-a", "POPULATION_HEALTH_MANAGER"), _h(accounts, "demo-org-b",
                                                                                 "POPULATION_HEALTH_MANAGER")
    with eng.connect() as c:
        n_a = c.execute(text("SELECT count(*) FROM synthetic.patient WHERE region_id = 1")).scalar_one()
        n_b = c.execute(text("SELECT count(*) FROM synthetic.patient WHERE region_id <> 1")).scalar_one()
        pid_b = c.execute(text("SELECT patient_id FROM synthetic.patient WHERE region_id <> 1 "
                               "ORDER BY patient_id LIMIT 1")).scalar_one()
    assert client.get("/api/v1/patients?limit=1", headers=mgr_a).json()["total"] == n_a
    assert client.get("/api/v1/patients?limit=1", headers=mgr_b).json()["total"] == n_b
    assert client.get("/api/v1/dashboard/summary", headers=mgr_a).json()["total_patients"] == n_a
    assert client.get(f"/api/v1/patients/{pid_b}", headers=mgr_a).status_code == 404
    cc = _h(accounts, "demo-org-a", "CARE_COORDINATOR")
    assert client.get("/api/v1/patients?limit=1", headers=cc).json()["total"] == 20
    gaps = client.get("/api/v1/care-gaps?limit=200", headers=cc).json()
    assert gaps["total"] > 0
    assert client.get("/api/v1/patients", headers=_h(accounts, "demo-org-a", "SYSTEM_ADMIN")).status_code == 403


def test_portal_follow_up_and_actor_attribution_in_db_mode(pg):
    eng, accounts = pg
    patient = accounts[("demo-org-a", "PATIENT")]
    ph, cc = _h(accounts, "demo-org-a", "PATIENT"), _h(accounts, "demo-org-a", "CARE_COORDINATOR")
    summary = client.get("/api/v1/portal/summary?lang=ar", headers=ph).json()
    assert summary["patient_id"] == patient.patient_id and summary["direction"] == "rtl"
    rec = client.get("/api/v1/portal/recommendations", headers=ph).json()["items"][0]
    task = client.post("/api/v1/follow-up-tasks", headers=cc, json={
        "patient_id": patient.patient_id, "care_gap_id": rec["recommendation_id"]}).json()
    resp = client.post(f"/api/v1/portal/follow-ups/{task['task_id']}/responses", headers=ph,
                       json={"response": "need_help", "message": "مساعدة من فضلك"})
    assert resp.status_code == 201 and resp.json()["status"] == "patient_responded"
    fu = client.post(f"/api/v1/care-gaps/{rec['recommendation_id']}/follow-ups", headers=cc,
                     json={"event_type": "note_recorded", "note": "called", "recorded_by": "forged"})
    assert fu.status_code == 201
    with eng.connect() as c:
        stored = c.execute(text("SELECT recorded_by FROM synthetic.care_gap_follow_up_event WHERE follow_up_id = :f"),
                           {"f": fu.json()["follow_up_id"]}).scalar_one()
        cc_id = c.execute(text("SELECT user_id FROM identity.user_account WHERE email = :e"),
                          {"e": accounts[("demo-org-a", "CARE_COORDINATOR")].email}).scalar_one()
        msg = c.execute(text("SELECT message FROM engagement.follow_up_task_event WHERE task_id = :t "
                             "AND event_type = 'patient_response'"), {"t": task["task_id"]}).scalar_one()
    assert stored == cc_id and msg == "مساعدة من فضلك"


def test_durable_ai_audit_is_filtered_by_organization(pg):
    _, accounts = pg
    mgr_a = _h(accounts, "demo-org-a", "POPULATION_HEALTH_MANAGER")
    assert client.get("/api/v1/insights/population", headers=mgr_a).status_code == 200
    client.get("/api/v1/insights/population", headers=_h(accounts, "demo-org-b", "POPULATION_HEALTH_MANAGER"))
    items_a = client.get("/api/v1/ai/audit", headers=_h(accounts, "demo-org-a", "SYSTEM_ADMIN")).json()
    assert items_a["durable"] is True and items_a["items"]
    orgs = {i["extra"].get("organization_id") for i in items_a["items"]}
    assert len(orgs) == 1


def test_reseed_keeps_identity_data_working(pg):
    from test_live_backend_completion import _seed

    eng, accounts = pg
    _seed(eng)
    ph = _h(accounts, "demo-org-a", "PATIENT")
    assert client.get("/api/v1/portal/summary", headers=ph).status_code == 200
    assert client.get("/api/v1/patients?limit=1", headers=_h(accounts, "demo-org-a", "CARE_COORDINATOR")).json()["total"] == 20


def test_zz_downgrade_refused_while_identity_data_exists(pg):
    eng, _ = pg
    with pytest.raises(RuntimeError, match="Refusing to downgrade 0011"):
        command.downgrade(_cfg(), "0010")
    with eng.connect() as c:  # one transaction: the 0012 step is rolled back too
        assert c.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0012"
    command.downgrade(_cfg(allow_data_loss=True), "0010")
    with eng.connect() as c:
        assert c.execute(text("SELECT to_regclass('identity.user_account')")).scalar_one() is None
        assert c.execute(text("SELECT count(*) FROM synthetic.patient")).scalar_one() > 0
    command.upgrade(_cfg(), "head")
