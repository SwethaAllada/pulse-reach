"""Validate CI workflow PostgreSQL & TEST_DATABASE_URL configuration (`T-14`)."""

from __future__ import annotations

from pathlib import Path

import yaml


def test_ci_workflow_defines_postgres_service_and_test_database_url():
    repo_root = Path(__file__).resolve().parents[2]
    ci_path = repo_root / ".github" / "workflows" / "ci.yml"
    assert ci_path.exists()
    doc = yaml.safe_load(ci_path.read_text(encoding="utf-8"))
    job = doc["jobs"]["backend-and-postgres"]
    assert "postgres" in job["services"]
    assert "TEST_DATABASE_URL" in job["env"]
    assert "postgresql+psycopg://" in job["env"]["TEST_DATABASE_URL"]
