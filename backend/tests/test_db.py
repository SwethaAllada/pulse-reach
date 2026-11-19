import os

import pytest
from pydantic import SecretStr
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import OperationalError

from app.core.config import Settings
from app.db import session
from app.db.session import (
    SCHEMAS,
    DatabaseNotConfigured,
    build_engine,
    database_status,
)
from app.main import app

client = TestClient(app)
URL = "postgresql+psycopg://u:secret-pw@localhost:5432/d"


def make_settings(**kw) -> Settings:
    return Settings(_env_file=None, **kw)


# --- configuration -------------------------------------------------------
def test_database_url_has_no_default(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert make_settings().database_url is None


def test_database_url_read_from_env_and_not_leaked(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", URL)
    s = make_settings()
    assert s.database_url.get_secret_value() == URL
    assert "secret-pw" not in repr(s)


def test_pool_settings_applied():
    s = make_settings(
        database_url=URL, db_pool_size=3, db_max_overflow=1, db_pool_timeout=7, db_pool_recycle=99
    )
    engine = build_engine(s)
    pool = engine.pool
    assert (pool.size(), pool._max_overflow, pool._timeout, pool._recycle) == (3, 1, 7, 99)
    assert pool._pre_ping is True


def test_build_engine_without_url_raises(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(DatabaseNotConfigured):
        build_engine(make_settings())


def test_schema_list_and_naming_convention():
    assert SCHEMAS == ("official", "clinical", "synthetic")
    assert session.metadata.naming_convention["pk"] == "pk_%(table_name)s"


# --- health check --------------------------------------------------------
def test_app_health_without_database(monkeypatch):
    monkeypatch.setattr(session.settings, "database_url", None)
    session.get_engine.cache_clear()
    assert client.get("/health").json() == {"status": "ok"}


def test_health_db_not_configured(monkeypatch):
    monkeypatch.setattr(session.settings, "database_url", None)
    session.get_engine.cache_clear()
    r = client.get("/health/db")
    assert r.status_code == 503
    assert r.json() == {"status": "degraded", "database": "not_configured"}


def test_health_db_unreachable_does_not_leak_details():
    # Port 1 refuses connections.
    engine = create_engine(
        "postgresql+psycopg://u:secret-pw@127.0.0.1:1/d", connect_args={"connect_timeout": 1}
    )
    assert database_status(engine) == "unavailable"


def test_health_db_ok_response(monkeypatch):
    monkeypatch.setattr("app.api.health.database_status", lambda: "ok")
    r = client.get("/health/db")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "database": "ok"}


def test_health_db_unavailable_response(monkeypatch):
    monkeypatch.setattr("app.api.health.database_status", lambda: "unavailable")
    r = client.get("/health/db")
    assert r.status_code == 503
    assert "secret" not in r.text


# --- live PostgreSQL (set TEST_DATABASE_URL) -----------------------------
live = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set"
)


@live
def test_live_connection_and_migrations(monkeypatch):
    from alembic import command
    from alembic.config import Config

    url = os.environ["TEST_DATABASE_URL"]
    monkeypatch.setattr(session.settings, "database_url", SecretStr(url))
    session.get_engine.cache_clear()
    session.check_database()  # surfaces the real error if the connection fails
    assert database_status() == "ok"
    assert client.get("/health/db").status_code == 200

    cfg = Config("alembic.ini")
    command.downgrade(cfg, "base")  # start from empty whatever a previous run left behind
    # Revision 0001 only: the schema-creation step. Table creation is covered by
    # tests/test_official_schema.py.
    command.upgrade(cfg, "0001")
    engine = create_engine(url)
    try:
        assert set(SCHEMAS) <= set(inspect(engine).get_schema_names())
        # Revision 0001 creates no application tables.
        for schema in SCHEMAS:
            assert inspect(engine).get_table_names(schema=schema) == []
        command.downgrade(cfg, "base")
        assert not set(SCHEMAS) & set(inspect(engine).get_schema_names())
        command.upgrade(cfg, "0001")  # idempotent re-apply
    finally:
        engine.dispose()
        session.get_engine.cache_clear()
