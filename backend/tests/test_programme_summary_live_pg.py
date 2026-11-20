"""Programme API alignment on a disposable PostgreSQL database: `GET /programmes/{pathway}/summary`
and the programme-scoped `/patients` filters return exactly what memory mode returns."""

from __future__ import annotations

import os

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app.core.config import settings
from app.main import app

pytestmark = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set")
client = TestClient(app)

SUMMARY_QUERIES = [
    "/api/v1/programmes/ifhas/summary",
    "/api/v1/programmes/well_child/summary",
    "/api/v1/programmes/ifhas/summary?region_id=2&sex=female",
    "/api/v1/programmes/ifhas/summary?age_band=adult_40_59&period=30d",
    "/api/v1/programmes/well_child/summary?region_id=3",
]
PATIENT_QUERIES = [
    f"pathway={pw}&{f}"
    for pw in ("ifhas", "well_child")
    for f in ("has_open_care_gaps=true", "has_open_care_gaps=false", "history_status=partial",
              "has_open_care_gaps=false&history_status=not_available")
] + ["has_open_care_gaps=true", "history_status=partial"]


@pytest.fixture(scope="module")
def pg():
    from test_live_backend_completion import _clear_store_engines, _seed
    from test_official_integrity import alembic_config, scratch_database

    with scratch_database() as url:
        command.upgrade(alembic_config(), "head")
        eng = create_engine(url)
        _seed(eng)
        mp = pytest.MonkeyPatch()
        mp.setattr(settings, "auth_mode", "legacy")
        try:
            yield mp
        finally:
            mp.undo()
            _clear_store_engines()
            eng.dispose()


def _get(mp, source: str, path: str) -> dict:
    mp.setattr(settings, "data_source", source)
    r = client.get(path)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.parametrize("path", SUMMARY_QUERIES)
def test_programme_summary_parity(pg, path):
    assert _get(pg, "db", path) == _get(pg, "memory", path)


@pytest.mark.parametrize("qs", PATIENT_QUERIES)
def test_programme_scoped_patient_filter_parity(pg, qs):
    path = f"/api/v1/patients?limit=200&{qs}"
    db, mem = _get(pg, "db", path), _get(pg, "memory", path)
    assert db["total"] == mem["total"]
    assert [p["patient_id"] for p in db["items"]] == [p["patient_id"] for p in mem["items"]]
