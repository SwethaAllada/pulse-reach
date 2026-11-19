"""Runtime foundation (BE-22, BE-24): fail-fast startup and structured, safe API errors."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.v1 import get_read_repository
from app.core.config import Settings, settings
from app.core.startup import StartupValidationError, validate_startup
from app.main import app
from app.repositories.read_repo import get_cached_bundle


@pytest.fixture
def broken_rules_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "rules_dir", str(tmp_path / "missing-rules"))
    get_cached_bundle.cache_clear()
    yield
    monkeypatch.undo()
    get_cached_bundle.cache_clear()


def test_startup_validation_passes_in_memory_mode():
    report = validate_startup(Settings(data_source="memory"))
    assert report.rules > 0 and report.authoritative_rules > 0 and len(report.bundle_sha256) == 64


def test_startup_fails_fast_without_rules(broken_rules_dir):
    with pytest.raises(StartupValidationError, match="Clinical rule bundle could not be loaded"):
        validate_startup(settings)
    with pytest.raises(StartupValidationError):
        with TestClient(app):
            pass


def test_startup_db_mode_requires_configured_database():
    with pytest.raises(StartupValidationError, match="DATABASE_URL"):
        validate_startup(Settings(data_source="db", database_url=None))
    unreachable = "postgresql+psycopg://u:p@127.0.0.1:1/none"
    with pytest.raises(StartupValidationError, match="unreachable or not migrated"):
        validate_startup(Settings(data_source="db", database_url=unreachable, db_connect_timeout=1))


def test_app_starts_with_valid_rules():
    with TestClient(app) as c:
        assert c.get("/health").json() == {"status": "ok"}


client = TestClient(app)


def test_not_found_error_envelope():
    resp = client.get("/api/v1/patients/SYNTH-PAT-999999", headers={"X-Request-ID": "req-abc"})
    body = resp.json()
    assert resp.status_code == 404
    assert body["detail"] == "Synthetic patient 'SYNTH-PAT-999999' not found"
    assert body["error"] == {
        "status": 404,
        "code": "not_found",
        "message": "Synthetic patient 'SYNTH-PAT-999999' not found",
        "request_id": "req-abc",
    }


def test_validation_error_envelope_does_not_echo_input():
    resp = client.post("/api/v1/appointments", json={"patient_id": "SYNTH-PAT-000001", "secret_field": "x" * 50})
    body = resp.json()
    assert resp.status_code == 422 and body["error"]["code"] == "validation_error"
    assert all(set(e) <= {"type", "loc", "msg"} for e in body["detail"])
    assert "xxxxxxxxxx" not in resp.text


def test_unhandled_errors_are_generic_500():
    class Exploding:
        def get_dashboard_summary(self):
            raise RuntimeError("SELECT secret FROM synthetic.patient WHERE password='hunter2'")

    app.dependency_overrides[get_read_repository] = lambda: Exploding()
    try:
        resp = TestClient(app, raise_server_exceptions=False).get("/api/v1/dashboard/summary")
    finally:
        app.dependency_overrides.pop(get_read_repository, None)
    assert resp.status_code == 500
    assert resp.json()["error"]["code"] == "internal_error"
    assert resp.json()["detail"] == "Internal server error."
    assert "hunter2" not in resp.text and "SELECT" not in resp.text
    assert resp.headers.get("X-Request-ID")
