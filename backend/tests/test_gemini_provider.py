"""Google Gemini adapter: configuration, request shape, response parsing, failures and retries.

All provider calls are mocked (`httpx.post`); `_sleep` is patched so retries never wait - no network.
"""

from __future__ import annotations

import json
import logging
from types import SimpleNamespace

import httpx
import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.services.ai import DETERMINISTIC, LLM_GROUNDED, AIService, LLMProviderError, build_provider
from app.services.ai import provider as provider_mod
from app.services.ai.provider import (
    _BACKOFF_CAP_SECONDS,
    AnthropicProvider,
    GeminiProvider,
    OpenAICompatibleProvider,
)
from app.services.explanation import BoundedExplanationInput

KEY = "AIza-test-GEMINI-SECRET-123"
BASE = "https://gemini.example/v1beta"
MODEL = "gemini-3.5-flash-lite"
RAW_MARKER = "RAW-RESPONSE-MARKER-xyz"


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch):
    for var in ("LLM_ENABLED", "LLM_PROVIDER", "LLM_API_KEY", "LLM_MODEL", "LLM_BASE_URL",
                "GEMINI_API_KEY", "GEMINI_MODEL", "GEMINI_BASE_URL", "GEMINI_THINKING_LEVEL"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def sleeps(monkeypatch):
    delays: list[float] = []
    monkeypatch.setattr(provider_mod, "_sleep", delays.append)
    return delays


def _settings(**kw) -> Settings:
    return Settings(_env_file=None, **kw)


def _gemini(**kw) -> GeminiProvider:
    args = {"api_key": KEY, "model": MODEL, "base_url": BASE, "timeout": 3, "max_retries": 2, **kw}
    return GeminiProvider(**args)


def _ok(text: str = "hello", **extra) -> dict:
    return {"candidates": [{"content": {"role": "model", "parts": [{"text": text}]}, "finishReason": "STOP"}],
            "modelVersion": "gemini-3.5-flash-lite-001", **extra}


class FakePost:
    """Replays `responses` (an httpx.Response, a dict body for HTTP 200, or an exception) in order."""

    def __init__(self, *responses) -> None:
        self.responses = list(responses)
        self.calls: list[dict] = []

    def __call__(self, url, headers, json, timeout):
        self.calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        r = self.responses[min(len(self.calls), len(self.responses)) - 1]
        if isinstance(r, Exception):
            raise r
        return r if isinstance(r, httpx.Response) else httpx.Response(200, json=r)


def _install(monkeypatch, *responses) -> FakePost:
    fake = FakePost(*responses)
    monkeypatch.setattr(httpx, "post", fake)
    return fake


def _fail(p: GeminiProvider) -> LLMProviderError:
    with pytest.raises(LLMProviderError) as exc:
        p.complete(system="s", user="u", max_tokens=10)
    assert KEY not in str(exc.value) and RAW_MARKER not in str(exc.value)
    return exc.value


# --- configuration -------------------------------------------------------------------------


def test_disabled_and_missing_gemini_key():
    assert build_provider(_settings(llm_enabled=False, llm_provider="gemini",
                                    gemini_api_key=SecretStr(KEY))) == (None, "disabled")
    p, st = build_provider(_settings(llm_enabled=True, llm_provider="gemini"))
    assert p is None and st.startswith("misconfigured") and "GEMINI_API_KEY" in st
    p, st = build_provider(_settings(llm_enabled=True, llm_provider="gemini", gemini_api_key=SecretStr("  ")))
    assert p is None and "GEMINI_API_KEY" in st


def test_llm_api_key_alone_does_not_enable_gemini():
    p, st = build_provider(_settings(llm_enabled=True, llm_provider="gemini", llm_api_key=SecretStr(KEY)))
    assert p is None and "GEMINI_API_KEY" in st


@pytest.mark.parametrize("model", ["bad model", "../etc", "gemini/x:generateContent", "-lead", "x" * 200])
def test_invalid_model_id_is_misconfigured(model):
    for kw in ({"gemini_model": model}, {"llm_model": model}):
        p, st = build_provider(_settings(llm_enabled=True, llm_provider="gemini", gemini_api_key=SecretStr(KEY), **kw))
        assert p is None and st.startswith("misconfigured") and KEY not in st


def test_default_model_and_llm_model_override():
    p, st = build_provider(_settings(llm_enabled=True, llm_provider="gemini", gemini_api_key=SecretStr(KEY)))
    assert isinstance(p, GeminiProvider) and st == "enabled" and p.model == "gemini-3.5-flash-lite"
    p, _ = build_provider(_settings(llm_enabled=True, llm_provider="gemini", gemini_api_key=SecretStr(KEY),
                                    gemini_model="gemini-x", llm_model="gemini-override-2"))
    assert p.model == "gemini-override-2"
    p, _ = build_provider(_settings(llm_enabled=True, llm_provider="gemini", gemini_api_key=SecretStr(KEY),
                                    gemini_model="gemini-custom"))
    assert p.model == "gemini-custom"


def test_other_providers_unchanged():
    p, st = build_provider(_settings(llm_enabled=True, llm_api_key=SecretStr(KEY), llm_model="m",
                                     gemini_api_key=SecretStr("other")))
    assert isinstance(p, OpenAICompatibleProvider) and st == "enabled"
    p, _ = build_provider(_settings(llm_enabled=True, llm_provider="anthropic", llm_api_key=SecretStr(KEY), llm_model="m"))
    assert isinstance(p, AnthropicProvider)
    p, st = build_provider(_settings(llm_enabled=True, llm_provider="anthropic", gemini_api_key=SecretStr(KEY),
                                     llm_model="m"))
    assert p is None and "LLM_API_KEY" in st


# --- request shape -------------------------------------------------------------------------


def test_request_shape_and_key_placement(monkeypatch):
    fake = _install(monkeypatch, _ok())
    _gemini().complete(system="SYSTEM-TEXT", user="USER-TEXT", max_tokens=123)
    call = fake.calls[0]
    assert call["url"] == f"{BASE}/models/{MODEL}:generateContent" and call["timeout"] == 3
    assert call["headers"] == {"x-goog-api-key": KEY}
    assert KEY not in call["url"] and KEY not in json.dumps(call["json"])
    body = call["json"]
    assert body["systemInstruction"] == {"parts": [{"text": "SYSTEM-TEXT"}]}
    assert body["contents"] == [{"role": "user", "parts": [{"text": "USER-TEXT"}]}]
    assert "SYSTEM-TEXT" not in json.dumps(body["contents"])
    assert body["generationConfig"] == {"temperature": 0, "maxOutputTokens": 1024, "candidateCount": 1}


def test_trailing_slash_base_url(monkeypatch):
    fake = _install(monkeypatch, _ok())
    _gemini(base_url=BASE + "/").complete(system="s", user="u", max_tokens=10)
    assert fake.calls[0]["url"] == f"{BASE}/models/{MODEL}:generateContent"


def test_json_mode_and_thinking_level(monkeypatch):
    fake = _install(monkeypatch, _ok())
    _gemini().complete(system="s", user="u", max_tokens=10, json_mode=True)
    cfg = fake.calls[0]["json"]["generationConfig"]
    assert cfg["responseMimeType"] == "application/json" and "thinkingConfig" not in cfg

    _gemini(thinking_level="low").complete(system="s", user="u", max_tokens=10)
    cfg = fake.calls[1]["json"]["generationConfig"]
    assert cfg["thinkingConfig"] == {"thinkingLevel": "LOW"} and "responseMimeType" not in cfg

    _gemini(thinking_level="").complete(system="s", user="u", max_tokens=10)
    assert "thinkingConfig" not in fake.calls[2]["json"]["generationConfig"]


def test_build_provider_passes_settings(monkeypatch):
    p, _ = build_provider(_settings(llm_enabled=True, llm_provider="gemini", gemini_api_key=SecretStr(f" {KEY} "),
                                    gemini_base_url=BASE, gemini_thinking_level="high", llm_timeout_seconds=7))
    fake = _install(monkeypatch, _ok())
    p.complete(system="s", user="u", max_tokens=10)
    call = fake.calls[0]
    assert call["headers"] == {"x-goog-api-key": KEY} and call["timeout"] == 7
    assert call["url"].startswith(BASE + "/models/")
    assert call["json"]["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "HIGH"}


# --- success parsing -----------------------------------------------------------------------


def test_text_joined_thoughts_excluded_model_version_used(monkeypatch):
    _install(monkeypatch, {
        "candidates": [{"content": {"parts": [
            {"text": "SECRET-REASONING", "thought": True},
            {"text": "Hello, "},
            {"inlineData": {"mimeType": "image/png"}},
            {"text": "world."},
        ]}, "finishReason": "STOP"}],
        "modelVersion": "gemini-3.5-flash-lite-002",
    })
    c = _gemini().complete(system="s", user="u", max_tokens=10)
    assert c.text == "Hello, world." and "SECRET-REASONING" not in c.text
    assert (c.provider, c.model, c.attempts) == ("gemini", "gemini-3.5-flash-lite-002", 1)


def test_model_falls_back_to_configured_model(monkeypatch):
    body = _ok()
    del body["modelVersion"]
    _install(monkeypatch, body)
    assert _gemini().complete(system="s", user="u", max_tokens=10).model == MODEL


# --- failures ------------------------------------------------------------------------------


def _error(status: int, *, reason: str | None = None) -> httpx.Response:
    err: dict = {"code": status, "message": f"{RAW_MARKER} {KEY}", "status": "INVALID_ARGUMENT"}
    if reason:
        err["details"] = [{"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": reason}]
    return httpx.Response(status, json={"error": err})


@pytest.mark.parametrize("resp,kind", [
    (_error(401), "auth"),
    (_error(403), "auth"),
    (_error(400, reason="API_KEY_INVALID"), "auth"),
    (_error(400), "bad_request"),
    (_error(400, reason="OTHER_REASON"), "bad_request"),
    (httpx.Response(400, text=f"not json {RAW_MARKER}"), "bad_request"),
    (httpx.Response(400, json=[RAW_MARKER]), "bad_request"),
    (httpx.Response(404, json={"error": {"message": RAW_MARKER}}), "bad_request"),
])
def test_http_errors_are_classified_and_not_retried(monkeypatch, sleeps, resp, kind):
    fake = _install(monkeypatch, resp)
    err = _fail(_gemini())
    assert err.kind == kind and err.status_code == resp.status_code and not err.retryable
    assert len(fake.calls) == 1 and sleeps == []


@pytest.mark.parametrize("body,kind", [
    ({"promptFeedback": {"blockReason": "SAFETY"}, "candidates": []}, "blocked"),
    ({"promptFeedback": {"blockReason": "OTHER"}}, "blocked"),
    ({"candidates": [{"content": {"parts": [{"text": RAW_MARKER}]}, "finishReason": "SAFETY"}]}, "blocked"),
    ({"candidates": [{"content": {"parts": [{"text": RAW_MARKER}]}, "finishReason": "RECITATION"}]}, "blocked"),
    ({"candidates": [{"content": {"parts": [{"text": RAW_MARKER}]}, "finishReason": "MAX_TOKENS"}]}, "truncated"),
    ({"candidates": []}, "invalid_response"),
    ({}, "invalid_response"),
    ({"candidates": ["x"]}, "invalid_response"),
    ({"candidates": [{"finishReason": "STOP"}]}, "invalid_response"),
    ({"candidates": [{"content": {"parts": []}, "finishReason": "STOP"}]}, "invalid_response"),
    ({"candidates": [{"content": {"parts": [{"text": "   "}]}, "finishReason": "STOP"}]}, "invalid_response"),
    ({"candidates": [{"content": {"parts": [{"text": RAW_MARKER, "thought": True}]}}]}, "invalid_response"),
])
def test_unusable_bodies_fail_without_retry(monkeypatch, sleeps, body, kind):
    fake = _install(monkeypatch, body)
    err = _fail(_gemini())
    assert err.kind == kind and len(fake.calls) == 1 and sleeps == []


@pytest.mark.parametrize("resp", [
    httpx.Response(200, text=f"<html>{RAW_MARKER}</html>"),
    httpx.Response(200, json=[RAW_MARKER]),
])
def test_non_json_or_non_object_body_is_invalid_response(monkeypatch, sleeps, resp):
    fake = _install(monkeypatch, resp)
    assert _fail(_gemini()).kind == "invalid_response" and len(fake.calls) == 1


# --- retries -------------------------------------------------------------------------------


def test_rate_limited_then_success(monkeypatch, sleeps):
    fake = _install(monkeypatch, _error(429), _ok("recovered"))
    c = _gemini().complete(system="s", user="u", max_tokens=10)
    assert c.text == "recovered" and c.attempts == 2 and len(fake.calls) == 2
    assert len(sleeps) == 1 and 0 < sleeps[0] <= _BACKOFF_CAP_SECONDS


def test_server_errors_exhaust_retries(monkeypatch, sleeps):
    fake = _install(monkeypatch, _error(503))
    err = _fail(_gemini(max_retries=2))
    assert err.kind == "server_error" and err.status_code == 503 and err.retryable
    assert len(fake.calls) == 3 and len(sleeps) == 2
    assert sleeps[1] > sleeps[0]  # exponential backoff (0.4-0.6s, then 0.8-1.2s)


def test_no_retries_when_max_retries_zero(monkeypatch, sleeps):
    fake = _install(monkeypatch, _error(500))
    assert _fail(_gemini(max_retries=0)).kind == "server_error"
    assert len(fake.calls) == 1 and sleeps == []


@pytest.mark.parametrize("exc,kind", [
    (httpx.ConnectTimeout(f"connect {KEY}"), "timeout"),
    (httpx.ReadTimeout(f"read {KEY}"), "timeout"),
    (httpx.ConnectError(f"refused {KEY}"), "network"),
])
def test_transport_errors_are_retried(monkeypatch, sleeps, exc, kind):
    fake = _install(monkeypatch, exc)
    err = _fail(_gemini(max_retries=2))
    assert err.kind == kind and err.status_code is None and len(fake.calls) == 3 and len(sleeps) == 2
    assert err.__cause__ is None and err.__suppress_context__


def test_transport_error_then_success(monkeypatch, sleeps):
    _install(monkeypatch, httpx.ReadTimeout("slow"), _ok())
    assert _gemini().complete(system="s", user="u", max_tokens=10).attempts == 2


def test_retry_after_is_respected_but_capped(monkeypatch, sleeps):
    _install(monkeypatch, httpx.Response(429, headers={"retry-after": "2"}), _ok())
    _gemini().complete(system="s", user="u", max_tokens=10)
    assert sleeps == [2.0]

    sleeps.clear()
    _install(monkeypatch, httpx.Response(503, headers={"retry-after": "120"}), _ok())
    _gemini(total_timeout=300).complete(system="s", user="u", max_tokens=10)
    assert sleeps == [_BACKOFF_CAP_SECONDS]

    sleeps.clear()
    _install(monkeypatch, httpx.Response(429, headers={"retry-after": "soon"}), _ok())
    _gemini().complete(system="s", user="u", max_tokens=10)
    assert len(sleeps) == 1 and 0 < sleeps[0] <= _BACKOFF_CAP_SECONDS


def test_backoff_never_exceeds_cap(monkeypatch, sleeps):
    monkeypatch.setattr(provider_mod, "random", SimpleNamespace(random=lambda: 0.999))
    _install(monkeypatch, _error(503))
    _fail(_gemini(max_retries=5, total_timeout=300))
    assert len(sleeps) == 5 and max(sleeps) <= _BACKOFF_CAP_SECONDS


def test_total_timeout_prevents_further_attempts(monkeypatch):
    clock = {"t": 0.0}
    monkeypatch.setattr(provider_mod, "time", SimpleNamespace(monotonic=lambda: clock["t"]))
    monkeypatch.setattr(provider_mod, "_sleep", lambda d: clock.__setitem__("t", clock["t"] + d))
    fake = _install(monkeypatch, _error(503))
    orig = fake.__call__

    def slow_post(*a, **k):  # each attempt uses up the full 1s per-attempt timeout
        clock["t"] += 1.0
        return orig(*a, **k)

    monkeypatch.setattr(httpx, "post", slow_post)
    err = _fail(_gemini(timeout=1, max_retries=5, total_timeout=3))
    assert err.kind == "server_error" and len(fake.calls) == 2

    fake.calls.clear()
    clock["t"] = 0.0
    _fail(_gemini(timeout=1, max_retries=5, total_timeout=1))
    assert len(fake.calls) == 1


def test_auth_and_bad_request_never_retried_even_with_retry_after(monkeypatch, sleeps):
    for status in (400, 401, 403):
        fake = _install(monkeypatch, httpx.Response(status, headers={"retry-after": "1"}, json={}), _ok())
        _fail(_gemini(max_retries=5))
        assert len(fake.calls) == 1
    assert sleeps == []


# --- service integration -------------------------------------------------------------------

INP = BoundedExplanationInput(
    synthetic_patient_id="SYNTH-PAT-000001",
    pathway="ifhas",
    standard_name="IFHAS Standard",
    rule_id="IFHAS-PKG-MAJOR-40-64",
    rule_version="1.0.0",
    source_reference="Appendix 7",
    verification_status="verified",
    is_authoritative=True,
    evaluation_status="due",
    history_status="available",
    reason_codes=(),
)
GOOD_EXPLANATION = (
    "Under rule IFHAS-PKG-MAJOR-40-64 (version 1.0.0) this person is evaluated as due for the "
    "package; screening history is available."
)


def _assert_logs_clean(caplog, fake: FakePost, *extra_secrets: str) -> None:
    sent = fake.calls[0]["json"]
    secrets = [KEY, RAW_MARKER, sent["systemInstruction"]["parts"][0]["text"],
               sent["contents"][0]["parts"][0]["text"], *extra_secrets]
    for rec in caplog.records:
        dump = rec.getMessage() + json.dumps(rec.__dict__, default=str)
        for s in secrets:
            assert s not in dump, f"{s[:20]!r} leaked into log record {rec.name}"


def test_service_falls_back_on_gemini_failure(monkeypatch, sleeps, caplog):
    caplog.set_level(logging.DEBUG)
    fake = _install(monkeypatch, _error(503))
    svc = AIService(_gemini(max_retries=1), provider_status="enabled")
    assert svc.status()["availability"] == "configured_unverified"

    res, meta = svc.explain(INP)
    assert res.generation_mode == DETERMINISTIC and meta.fallback_reason == "provider_error"
    assert res.summary_text == AIService(None).explain(INP)[0].summary_text
    assert meta.provider == "gemini" and meta.model == MODEL and len(fake.calls) == 2

    rec = svc.audit.recent()[0]
    assert rec.extra["provider_error_kind"] == "server_error"
    st = svc.status()
    assert st["availability"] == "last_call_failed" and st["last_provider_error"] == "server_error"
    assert st["provider"] == "gemini" and KEY not in json.dumps(st, default=str)
    _assert_logs_clean(caplog, fake)


@pytest.mark.parametrize("resp,kind", [
    (_error(400, reason="API_KEY_INVALID"), "auth"),
    ({"promptFeedback": {"blockReason": "SAFETY"}}, "blocked"),
    ({"candidates": [{"content": {"parts": [{"text": RAW_MARKER}]}, "finishReason": "MAX_TOKENS"}]}, "truncated"),
])
def test_service_records_error_kind(monkeypatch, sleeps, caplog, resp, kind):
    caplog.set_level(logging.DEBUG)
    fake = _install(monkeypatch, resp)
    svc = AIService(_gemini(), provider_status="enabled")
    _, meta = svc.explain(INP)
    assert meta.fallback_reason == "provider_error"
    assert svc.audit.recent()[0].extra["provider_error_kind"] == kind
    assert svc.status()["last_provider_error"] == kind
    _assert_logs_clean(caplog, fake)


def test_service_success_with_retry(monkeypatch, sleeps, caplog):
    caplog.set_level(logging.DEBUG)
    body = _ok(GOOD_EXPLANATION)
    body["usageMetadata"] = {"note": RAW_MARKER}
    fake = _install(monkeypatch, _error(429), body)
    svc = AIService(_gemini(), provider_status="enabled")
    res, meta = svc.explain(INP)
    assert res.generation_mode == LLM_GROUNDED and res.summary_text == GOOD_EXPLANATION
    assert meta.fallback_reason is None and meta.model == "gemini-3.5-flash-lite-001"
    rec = svc.audit.recent()[0]
    assert rec.extra.get("provider_attempts") == 2 and "provider_error_kind" not in rec.extra
    st = svc.status()
    assert st["availability"] == "last_call_succeeded" and st["last_provider_error"] is None
    _assert_logs_clean(caplog, fake, GOOD_EXPLANATION)
