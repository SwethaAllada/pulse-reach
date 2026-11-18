"""Tests for T-16: request IDs, structured JSON logging without PII, and llm_enabled=False."""

from __future__ import annotations

import json
import logging

from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app

client = TestClient(app)


def test_llm_disabled_by_default():
    assert settings.llm_enabled is False


def test_request_id_header_generated_and_echoed():
    r1 = client.get("/api/v1/dashboard/summary")
    assert r1.status_code == 200
    req_id = r1.headers.get("x-request-id")
    assert req_id and len(req_id) >= 8

    r2 = client.get("/api/v1/dashboard/summary", headers={"X-Request-ID": "req-abc-123"})
    assert r2.status_code == 200
    assert r2.headers.get("x-request-id") == "req-abc-123"


def test_structured_logging_omits_query_params_and_redacts_pii(caplog):
    from app.core.logging import JsonLogFormatter, redact_pii

    assert "[REDACTED_EID]" in redact_pii("Patient 784-1990-1234567-1")
    assert "[REDACTED_EMAIL]" in redact_pii("user@example.com")

    with caplog.at_level(logging.INFO, logger="pulsereach.http"):
        resp = client.get(
            "/api/v1/patients?q=784-1990-1234567-1",
            headers={"X-Request-ID": "trace-999"},
        )
        assert resp.status_code == 200

    http_records = [r for r in caplog.records if r.name == "pulsereach.http"]
    assert http_records
    fmt = JsonLogFormatter()
    payload = json.loads(fmt.format(http_records[-1]))
    assert payload["request_id"] == "trace-999"
    assert payload["method"] == "GET"
    assert payload["path"] == "/api/v1/patients"
    assert payload["status_code"] == 200
    assert "duration_ms" in payload
    assert "784-1990-1234567-1" not in json.dumps(payload)
