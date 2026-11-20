"""Shared session-scoped PostgreSQL test fixtures (`T-14`)."""

from __future__ import annotations

import os
from collections.abc import Iterator

# Workflow tests exercise business rules, not the shared write key; write protection itself is
# covered with explicit settings in `test_write_auth.py`. Set before `app` settings are imported.
os.environ.setdefault("ALLOW_UNPROTECTED_WRITES", "true")
# Pre-existing workflow/regression suites exercise the legacy contract (public reads, shared write
# key, client-supplied actor). Identity, RBAC and isolation tests switch to AUTH_MODE=users
# explicitly (`identity_fixtures.users_mode`). Cheap scrypt cost keeps those tests fast; the
# production default is N=2**17.
os.environ.setdefault("AUTH_MODE", "legacy")
os.environ.setdefault("PASSWORD_SCRYPT_N", "1024")

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


@pytest.fixture(scope="session")
def pg_test_engine() -> Iterator[Engine]:
    """Session-scoped SQLAlchemy Engine for `TEST_DATABASE_URL` (skips if unset)."""
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not set; skipping PostgreSQL integration test.")
    engine = create_engine(url, pool_pre_ping=True, future=True)
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    try:
        yield engine
    finally:
        engine.dispose()
