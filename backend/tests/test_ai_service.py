"""AI service layer (Phase D): provider config, grounding, guardrails, fallbacks and audit.

All provider calls are mocked - no network. Live provider execution is not exercised here.
"""

from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core.config import Settings
from app.main import app
from app.services.ai import (
    DETERMINISTIC,
    LLM_GROUNDED,
    AIService,
    LLMCompletion,
    LLMProviderError,
    build_ai_service,
    build_provider,
    get_ai_service,
)
from app.services.ai.guardrails import validate_output
from app.services.ai.provider import AnthropicProvider, OpenAICompatibleProvider
from app.services.explanation import BoundedExplanationInput

client = TestClient(app)
SECRET = "sk-test-SECRET-VALUE-123"


class FakeProvider:
    name = "fake"
    model = "fake-model-1"

    def __init__(self, reply: str | Exception) -> None:
        self.reply = reply
        self.calls: list[dict] = []

    def complete(self, *, system: str, user: str, max_tokens: int) -> LLMCompletion:
        self.calls.append({"system": system, "user": user, "max_tokens": max_tokens})
        if isinstance(self.reply, Exception):
            raise self.reply
        return LLMCompletion(text=self.reply, provider=self.name, model=self.model)


@pytest.fixture
def use_ai():
    def _install(provider):
        svc = AIService(provider, provider_status="enabled" if provider else "disabled")
        app.dependency_overrides[get_ai_service] = lambda: svc
        return svc

    yield _install
    app.dependency_overrides.pop(get_ai_service, None)


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


# --- provider configuration ----------------------------------------------------------------


def test_provider_configuration_states():
    assert build_provider(Settings(llm_enabled=False)) == (None, "disabled")
    p, st = build_provider(Settings(llm_enabled=True, llm_model="m"))
    assert p is None and "LLM_API_KEY" in st
    p, st = build_provider(Settings(llm_enabled=True, llm_api_key=SecretStr(SECRET)))
    assert p is None and "LLM_MODEL" in st
    p, st = build_provider(Settings(llm_enabled=True, llm_api_key=SecretStr(SECRET), llm_model="m"))
    assert isinstance(p, OpenAICompatibleProvider) and st == "enabled"
    p, _ = build_provider(
        Settings(llm_enabled=True, llm_provider="anthropic", llm_api_key=SecretStr(SECRET), llm_model="m")
    )
    assert isinstance(p, AnthropicProvider)


def test_status_never_exposes_the_key():
    svc = build_ai_service(Settings(llm_enabled=True, llm_api_key=SecretStr(SECRET), llm_model="gpt-x"))
    app.dependency_overrides[get_ai_service] = lambda: svc
    try:
        body = client.get("/api/v1/ai/status").json()
    finally:
        app.dependency_overrides.pop(get_ai_service, None)
    assert body["llm_enabled"] is True and body["model"] == "gpt-x"
    assert set(body["prompt_versions"]) == {"explanation", "outreach_draft", "population_insight", "patient_assistant"}
    assert SECRET not in json.dumps(body)


def test_default_settings_keep_ai_off():
    body = client.get("/api/v1/ai/status").json()
    assert body["llm_enabled"] is False and body["status"] == "disabled"


@pytest.mark.parametrize("cls,path,reply", [
    (OpenAICompatibleProvider, "/chat/completions", {"model": "m", "choices": [{"message": {"content": "hi"}}]}),
    (AnthropicProvider, "/v1/messages", {"model": "m", "content": [{"type": "text", "text": "hi"}]}),
])
def test_http_adapters_send_key_only_in_headers_and_hide_it_in_errors(monkeypatch, cls, path, reply):
    seen = {}

    def fake_post(url, headers, json, timeout):
        seen.update(url=url, headers=headers, json=json, timeout=timeout)
        return httpx.Response(200, json=reply)

    monkeypatch.setattr(httpx, "post", fake_post)
    p = cls(api_key=SECRET, model="m", base_url="https://llm.example", timeout=3)
    assert p.complete(system="s", user="u", max_tokens=10).text == "hi"
    assert seen["url"] == f"https://llm.example{path}" and seen["timeout"] == 3
    assert SECRET in json.dumps(seen["headers"]) and SECRET not in json.dumps(seen["json"])
    assert seen["json"]["temperature"] == 0

    monkeypatch.setattr(httpx, "post", lambda *a, **k: httpx.Response(401, json={"error": SECRET}))
    with pytest.raises(LLMProviderError) as exc:
        p.complete(system="s", user="u", max_tokens=10)
    assert SECRET not in str(exc.value)

    def boom(*a, **k):
        raise httpx.ConnectTimeout(f"timeout {SECRET}")

    monkeypatch.setattr(httpx, "post", boom)
    with pytest.raises(LLMProviderError) as exc:
        p.complete(system="s", user="u", max_tokens=10)
    assert SECRET not in str(exc.value)

    monkeypatch.setattr(httpx, "post", lambda *a, **k: httpx.Response(200, json={"unexpected": True}))
    with pytest.raises(LLMProviderError):
        p.complete(system="s", user="u", max_tokens=10)


# --- explanations --------------------------------------------------------------------------


def test_grounded_explanation_keeps_deterministic_fields():
    prov = FakeProvider(GOOD_EXPLANATION)
    svc = AIService(prov, provider_status="enabled")
    det = AIService(None).explain(INP)[0]
    res, meta = svc.explain(INP)
    assert meta.generation_mode == LLM_GROUNDED and res.generation_mode == LLM_GROUNDED
    assert res.summary_text == GOOD_EXPLANATION
    assert (res.evaluation_status, res.why_text, res.rule_citation_text, res.warnings) == (
        det.evaluation_status, det.why_text, det.rule_citation_text, det.warnings)
    facts = json.loads(prov.calls[0]["user"].removeprefix("FACTS:\n"))
    assert facts["evaluation_status"] == "due" and facts["rule_id"] == INP.rule_id
    assert "SYNTH-PAT" not in prov.calls[0]["user"]  # the person is not identified to the model
    assert meta.prompt_version == "explanation-v2" and meta.model == "fake-model-1"


# Golden adversarial set: every one must be rejected and replaced by the deterministic text.
ADVERSARIAL = {
    "clinical_claim": "Rule IFHAS-PKG-MAJOR-40-64 shows the person is diagnosed with diabetes.",
    "risk_or_probability": "Rule IFHAS-PKG-MAJOR-40-64: there is a high risk of disease.",
    "invented_number": "Rule IFHAS-PKG-MAJOR-40-64 requires an HbA1c below 7.5 for this person.",
    "missing:IFHAS-PKG-MAJOR-40-64": "This person is due for screening.",
    "overdue_claim": "Rule IFHAS-PKG-MAJOR-40-64: the person is overdue.",
    "personal_identifier": "Rule IFHAS-PKG-MAJOR-40-64: call +971 50 123 4567 or mail a@b.com.",
    "approval_claim": "Rule IFHAS-PKG-MAJOR-40-64 is a clinically approved recommendation.",
    "link": "Rule IFHAS-PKG-MAJOR-40-64, see https://example.com.",
    "empty_output": "   ",
    "too_long": "Rule IFHAS-PKG-MAJOR-40-64 " + "applies " * 200,
}


@pytest.mark.parametrize("violation,text", list(ADVERSARIAL.items()))
def test_adversarial_explanations_fall_back(violation, text):
    svc = AIService(FakeProvider(text), provider_status="enabled")
    res, meta = svc.explain(INP)
    assert res.generation_mode == DETERMINISTIC and meta.fallback_reason == "output_rejected"
    assert violation in meta.violations
    assert res.summary_text == AIService(None).explain(INP)[0].summary_text


@pytest.mark.parametrize("err", [LLMProviderError("down"), RuntimeError("adapter bug")])
def test_provider_failures_fall_back(err):
    res, meta = AIService(FakeProvider(err), provider_status="enabled").explain(INP)
    assert res.generation_mode == DETERMINISTIC and meta.fallback_reason == "provider_error"


def test_audit_records_every_generation_without_raw_text():
    svc = AIService(FakeProvider(GOOD_EXPLANATION), provider_status="enabled")
    svc.explain(INP)
    AIService(None, audit=svc.audit).explain(INP)
    recs = svc.audit.recent()
    assert [r.generation_mode for r in recs] == [DETERMINISTIC, LLM_GROUNDED]
    assert recs[0].fallback_reason == "llm_disabled"
    grounded = recs[1]
    assert grounded.subject == {"patient_id": INP.synthetic_patient_id, "rule_id": INP.rule_id}
    assert len(grounded.input_sha256) == 64 and len(grounded.output_sha256) == 64
    assert GOOD_EXPLANATION not in json.dumps(grounded.__dict__, default=str)


def test_explanation_api_uses_ai_and_survives_provider_failure(use_ai):
    use_ai(FakeProvider(LLMProviderError("timeout")))
    resp = client.post("/api/v1/explanations", json={"patient_id": "SYNTH-PAT-000001", "rule_id": "IFHAS-PKG-MAJOR-40-64"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["generation_mode"] == DETERMINISTIC and body["ai"]["fallback_reason"] == "provider_error"
    audit = client.get("/api/v1/ai/audit?feature=explanation").json()["items"]
    assert audit[0]["audit_id"] == body["ai"]["audit_id"]


def test_explanation_api_grounded(use_ai):
    use_ai(FakeProvider(GOOD_EXPLANATION))
    body = client.post("/api/v1/explanations", json={"patient_id": "SYNTH-PAT-000001", "rule_id": "IFHAS-PKG-MAJOR-40-64"}).json()
    assert body["generation_mode"] == LLM_GROUNDED and body["ai"]["prompt_version"] == "explanation-v2"
    assert body["evaluation_status"] in {"due", "upcoming", "completed", "unknown", "requires_clinical_review",
                                         "not_eligible", "eligible", "insufficient_information"}


# --- outreach drafts -----------------------------------------------------------------------

# SYNTH-PAT-000001's recorded contact channel is `phone`; drafts are only permitted on that channel.
ALLOWED = {"patient_id": "SYNTH-PAT-000001", "rule_id": "IFHAS-PKG-MAJOR-40-64", "channel": "phone", "language": "en"}
BLOCKED = {"patient_id": "SYNTH-PAT-000002", "rule_id": "IFHAS-PKG-MAJOR-40-64", "channel": "phone", "language": "en"}


def _first_allowed_rule(pid: str) -> str:
    gaps = client.get(f"/api/v1/care-gaps?patient_id={pid}&status=open").json()["items"]
    for g in gaps:
        if client.post("/api/v1/outreach/preview", json={**ALLOWED, "patient_id": pid, "rule_id": g["rule_id"]}).json()["allowed"]:
            return g["rule_id"]
    raise AssertionError("no allowed outreach for fixture patient")


def test_outreach_draft_is_gated_and_simulated(use_ai):
    prov = FakeProvider("Hello, you are invited to contact your preventive-care provider. Please consult a licensed healthcare professional.")
    use_ai(prov)
    rule_id = _first_allowed_rule("SYNTH-PAT-000001")
    ok = client.post("/api/v1/outreach/draft", json={**ALLOWED, "rule_id": rule_id}).json()
    assert ok["allowed"] and ok["simulated_only"] and ok["sendable"] is False
    assert ok["draft_message"].startswith("[SIMULATED OUTREACH PREVIEW — PHONE (en)] Hello")
    assert ok["ai"]["generation_mode"] == LLM_GROUNDED and ok["ai"]["prompt_version"] == "outreach-v3"

    calls = len(prov.calls)
    blocked = client.post("/api/v1/outreach/draft", json=BLOCKED).json()
    assert blocked["allowed"] is False and blocked["draft_message"] is None and blocked["ai"] is None
    assert len(prov.calls) == calls  # the model is never consulted for blocked outreach


def test_outreach_draft_rejects_clinical_content(use_ai):
    use_ai(FakeProvider("Your results suggest cancer; please consult a licensed healthcare professional."))
    rule_id = _first_allowed_rule("SYNTH-PAT-000001")
    out = client.post("/api/v1/outreach/draft", json={**ALLOWED, "rule_id": rule_id}).json()
    assert out["ai"]["generation_mode"] == DETERMINISTIC and "clinical_claim" in out["ai"]["violations"]
    assert out["is_fallback"] and "cancer" not in out["draft_message"]
    assert "SYNTH-PAT" not in out["draft_message"]  # the deterministic draft carries no identifiers


# --- population insights -------------------------------------------------------------------


def test_population_insight_deterministic_and_grounded(use_ai):
    use_ai(None)
    det = client.get("/api/v1/insights/population").json()
    dash = client.get("/api/v1/dashboard/summary").json()
    assert det["facts"]["total_patients"] == dash["total_patients"]
    assert det["facts"]["open_care_gaps_count"] == dash["open_care_gaps_count"]
    assert str(dash["total_patients"]) in det["summary_text"] and det["ai"]["fallback_reason"] == "llm_disabled"

    f = det["facts"]
    good = (f"The synthetic population has {f['total_patients']} people with "
            f"{f['open_care_gaps_count']} open care gaps; {f['unknown_history_patients_count']} have unknown history.")
    use_ai(FakeProvider(good))
    assert client.get("/api/v1/insights/population").json()["summary_text"] == good

    use_ai(FakeProvider(f"The synthetic population has {f['total_patients']} people and coverage will rise to 87 next year."))
    bad = client.get("/api/v1/insights/population").json()
    assert bad["ai"]["generation_mode"] == DETERMINISTIC
    assert "invented_number" in bad["ai"]["violations"]
    assert bad["summary_text"] == det["summary_text"]


def test_guardrail_allows_numbers_present_in_facts_only():
    facts = {"total": 550, "date": "2026-11-16"}
    assert validate_output("There are 550 people as of 2026-11-16.", facts=facts, max_chars=200) == []
    assert "invented_number" in validate_output("There are 551 people.", facts=facts, max_chars=200)
