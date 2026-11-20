"""BE-33 on a disposable PostgreSQL database (DATA_SOURCE=db): migration 0012, database-side
aggregation (parity with memory mode), persisted alerts, guards, reseed and downgrade."""

from __future__ import annotations

import argparse
import os
from datetime import datetime, timezone

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.rate_limit import reset_rate_limits
from app.main import app
from app.models.population import population_metadata
from app.models.synthetic import ConditionRecord
from app.services.identity.store import get_identity_engine
from app.services.population.config import DEFAULT_THRESHOLDS
from app.services.population.engine import build_snapshot
from app.services.population.facts import ALL_ORGANIZATIONS, MemoryFactsProvider, PostgresFactsProvider
from app.services.population.service import get_population_service
from app.services.population.store import get_population_engine

pytestmark = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set")
PW = "Live-Demo-Passphrase-42"
client = TestClient(app)
NOW = datetime(2026, 11, 20, tzinfo=timezone.utc)


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
        get_population_engine.cache_clear()
        get_population_service().reset()
        accounts = {(a.organization_slug, a.role): a for a in demo.seed_demo(lambda _e: PW)}
        try:
            yield eng, accounts
        finally:
            mp.undo()
            get_identity_engine.cache_clear()
            get_population_engine.cache_clear()
            get_population_service().reset()
            eng.dispose()


def _h(accounts, org: str, role: str) -> dict:
    reset_rate_limits()
    r = client.post("/api/v1/auth/login", json={"email": accounts[(org, role)].email, "password": PW})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_migration_matches_models(pg):
    eng, _ = pg
    insp = inspect(eng)
    tables = [*population_metadata.sorted_tables, ConditionRecord.__table__]
    for table in tables:
        cols = {c["name"]: c["nullable"] for c in insp.get_columns(table.name, schema=table.schema)}
        assert cols == {c.name: c.nullable for c in table.columns}, table.fullname
        idx = {i["name"] for i in insp.get_indexes(table.name, schema=table.schema)}
        assert {i.name for i in table.indexes} <= idx, table.fullname
    with eng.connect() as c:
        assert c.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0013"


def test_condition_records_are_seeded_and_reconciled(pg):
    from app.repositories.read_repo import get_cached_dataset

    eng, _ = pg
    with eng.connect() as c:
        n = c.execute(text("SELECT count(*) FROM synthetic.condition_record")).scalar_one()
        assert n == len(get_cached_dataset().condition_records) > 0
        with pytest.raises(DBAPIError):  # diagnosis after recording is rejected by the database
            c.execute(text("UPDATE synthetic.condition_record SET diagnosis_date = '2030-01-01' "
                           "WHERE condition_record_id = 'SYNTH-CND-000001'"))


def test_database_side_aggregation_matches_memory_definitions(pg):
    with Session(pg[0]) as s:
        db = PostgresFactsProvider(s).fetch(ALL_ORGANIZATIONS)
    mem = MemoryFactsProvider().fetch(ALL_ORGANIZATIONS)
    for name in ("population", "conditions", "coverage", "care_scope", "gaps", "screenings", "facilities"):
        assert sorted(getattr(db, name), key=repr) == sorted(getattr(mem, name), key=repr), name
    assert (db.as_of, db.source_run_id, db.reference_date) == (mem.as_of, mem.source_run_id, mem.reference_date)
    db.regions = mem.regions  # official Arabic names exist only in the database
    a = build_snapshot(db, DEFAULT_THRESHOLDS, config_version=0, generated_at=NOW)
    b = build_snapshot(mem, DEFAULT_THRESHOLDS, config_version=0, generated_at=NOW)
    assert a == b


def test_db_mode_api_isolation_and_alert_persistence(pg):
    eng, accounts = pg
    a, b = (_h(accounts, o, "POPULATION_HEALTH_MANAGER") for o in ("demo-org-a", "demo-org-b"))
    with eng.connect() as c:
        n_a = c.execute(text("SELECT count(*) FROM synthetic.patient WHERE region_id = 1 "
                             "AND date_of_death IS NULL")).scalar_one()
    summary = client.get("/api/v1/population/summary", headers=a).json()
    assert summary["total_population"] == n_a and summary["aggregation"]["status"] == "succeeded"
    top = client.get("/api/v1/population/map?condition=diabetes_type_2", headers=a).json()["items"][0]
    assert top["area"]["area_id"] == "AE-AZ-AD-L-mussafah"
    alert = client.get("/api/v1/population/alerts?category=case_increase", headers=a).json()["items"][0]
    assert client.get(f"/api/v1/population/alerts/{alert['alert_id']}", headers=b).status_code == 404
    r = client.patch(f"/api/v1/population/alerts/{alert['alert_id']}", json={"status": "ACKNOWLEDGED"}, headers=a)
    assert r.status_code == 200 and r.json()["acknowledged_by"]
    with eng.connect() as c:
        stored = c.execute(text("SELECT status, organization_key FROM population.population_alert "
                                "WHERE alert_id = :a"), {"a": alert["alert_id"]}).one()
        events = c.execute(text("SELECT count(*) FROM population.population_alert_event WHERE alert_id = :a "
                                "AND event_type = 'status_changed'"), {"a": alert["alert_id"]}).scalar_one()
        org_a = c.execute(text("SELECT organization_id FROM identity.organization WHERE slug = 'demo-org-a'")).scalar_one()
    assert stored.status == "ACKNOWLEDGED" and events == 1 and stored.organization_key == org_a


def test_alert_history_is_append_only(pg):
    eng, _ = pg
    for stmt in ("UPDATE population.population_alert_event SET note = 'x'",
                 "DELETE FROM population.population_alert_event", "TRUNCATE population.population_alert_event"):
        with eng.connect() as c, pytest.raises(DBAPIError, match="append-only"):
            c.execute(text(stmt))


def test_one_running_aggregation_per_organization(pg):
    eng, _ = pg
    row = ("INSERT INTO population.aggregation_run (run_id, organization_key, status, trigger, started_at, "
           "engine_version, summary) VALUES (:r, 'guard-test', 'running', 'manual', now(), '1.0.0', '{}')")
    with eng.begin() as c:
        c.execute(text(row), {"r": "guard-1"})
    with eng.begin() as c, pytest.raises(IntegrityError):
        c.execute(text(row), {"r": "guard-2"})
    with eng.begin() as c:
        c.execute(text("DELETE FROM population.aggregation_run WHERE organization_key = 'guard-test'"))


def test_reseed_keeps_alerts_deduplicated(pg):
    from test_live_backend_completion import _seed

    eng, accounts = pg
    h = _h(accounts, "demo-org-a", "POPULATION_HEALTH_MANAGER")
    before = client.get("/api/v1/population/alerts?limit=200", headers=h).json()["total"]
    _seed(eng)
    run = client.post("/api/v1/population/refresh", headers=h).json()
    assert run["status"] == "succeeded" and run["summary"]["alerts"]["created"] == 0
    assert client.get("/api/v1/population/alerts?limit=200", headers=h).json()["total"] == before


def test_zz_downgrade_refused_while_alerts_exist(pg):
    eng, _ = pg
    with pytest.raises(RuntimeError, match="Refusing to downgrade 0012"):
        command.downgrade(_cfg(), "0011")
    command.downgrade(_cfg(allow_data_loss=True), "0011")
    with eng.connect() as c:
        assert c.execute(text("SELECT to_regclass('synthetic.condition_record')")).scalar_one() is None
        assert c.execute(text("SELECT to_regclass('population.population_alert')")).scalar_one() is None
        assert c.execute(text("SELECT count(*) FROM synthetic.patient")).scalar_one() > 0
    command.upgrade(_cfg(), "head")
