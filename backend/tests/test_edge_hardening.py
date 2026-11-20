"""Deployment-edge hardening (Phase 6): client address behind Cloud Run for per-IP rate limits,
request body size limit and CORS without credentials."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.core.config import settings
from app.core.rate_limit import client_ip
from app.main import app
from identity_fixtures import users_mode  # noqa: F401

client = TestClient(app)


def _req(xff: str | None, peer: str = "169.254.1.1") -> Request:
    headers = [(b"x-forwarded-for", xff.encode())] if xff is not None else []
    return Request({"type": "http", "headers": headers, "client": (peer, 1234)})


def test_forwarded_header_is_ignored_without_trusted_proxies(monkeypatch):
    monkeypatch.setattr(settings, "trusted_proxy_hops", 0)
    assert client_ip(_req("203.0.113.9")) == "169.254.1.1"


@pytest.mark.parametrize("xff,expected", [
    ("198.51.100.7", "198.51.100.7"),
    ("1.2.3.4, 198.51.100.7", "198.51.100.7"),  # caller-supplied prefix is not trusted
    ("9.9.9.9, 8.8.8.8,198.51.100.7", "198.51.100.7"),
])
def test_cloud_run_appended_address_is_used_and_cannot_be_spoofed(monkeypatch, xff, expected):
    monkeypatch.setattr(settings, "trusted_proxy_hops", 1)
    assert client_ip(_req(xff)) == expected


def test_extra_proxy_hop_and_short_header_fall_back_safely(monkeypatch):
    monkeypatch.setattr(settings, "trusted_proxy_hops", 2)
    assert client_ip(_req("203.0.113.9, 198.51.100.7, 35.191.0.1")) == "198.51.100.7"
    assert client_ip(_req("35.191.0.1")) == "169.254.1.1"
    assert client_ip(_req(None)) == "169.254.1.1"


def test_rotating_a_spoofed_prefix_does_not_reset_the_login_rate_limit(users_mode, monkeypatch):
    from app.core.rate_limit import reset_rate_limits

    monkeypatch.setattr(settings, "trusted_proxy_hops", 1)
    monkeypatch.setattr(settings, "auth_rate_limit_per_minute", 3)
    reset_rate_limits()
    try:
        codes = [
            client.post("/api/v1/auth/login",
                        json={"email": f"nobody{i}@test.pulsereach.invalid", "password": "x" * 12},
                        headers={"X-Forwarded-For": f"10.0.0.{i}, 198.51.100.7"}).status_code
            for i in range(5)
        ]
    finally:
        reset_rate_limits()
    assert codes[-1] == 429, codes


def test_oversized_request_bodies_are_refused():
    body = b'{"note": "' + b"x" * (settings.max_request_body_bytes + 1) + b'"}'
    r = client.post("/api/v1/auth/login", content=body, headers={"Content-Type": "application/json"})
    assert r.status_code == 413
    assert r.json()["error"]["code"] == "payload_too_large"


def test_cors_does_not_allow_credentials():
    r = client.options("/api/v1/me", headers={"Origin": "http://localhost:3000",
                                               "Access-Control-Request-Method": "GET"})
    assert r.headers.get("access-control-allow-origin") == "http://localhost:3000"
    assert "access-control-allow-credentials" not in r.headers
