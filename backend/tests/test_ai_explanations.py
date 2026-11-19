"""Evidence-grounded individual explanations (`POST /explanations`) end to end.

Providers are exercised through the real HTTP adapters with `httpx.post` mocked; this proves the
request/response handling, guardrails and fallbacks, not live provider integration.
"""

from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core.config import Settings
from app.main import app
from app.repositories.read_repo import get_cached_index
from app.services.ai import DETERMINISTIC, LLM_GROUNDED, build_ai_service, get_ai_service
from app.services.ai.guardrails import validate_output

client = TestClient(app)
SECRET = "sk-test-SECRET-explanations-987"


def _find(pred) -> tuple[str, str]:
    idx = get_cached_index()
    for pid, evs in sorted(idx.evaluations_by_patient.items()):
        for e in evs:
            if pred(pid, e, idx):
                return pid, e["rule_id"]
    raise AssertionError("fixture case not found in synthetic data")


DUE = ("SYNTH-PAT-000001", "IFHAS-PKG-MAJOR-40-64")
UNKNOWN = _find(lambda pid, e, idx: e["evaluation_status"] == "unknown")
SUPERSEDED = _find(lambda pid, e, idx: any(
    g["evaluation_id"] == e["evaluation_id"] and g["status"] == "closed_completed"
    for g in idx.care_gaps_by_patient.get(pid, [])))
CONFLICTING = _find(lambda pid, e, idx: e["evaluation_status"] == "requires_clinical_review" and any(
    r["reason_code"] == "conflicting_records" for r in idx.reasons_by_eval.get(e["evaluation_id"], [])))

OPENAI_GOOD = (
    "Rule IFHAS-PKG-MAJOR-40-64 returned due for this person because an open no_documented_screening "
    "care gap is recorded and no screening for this rule was found in the available history. The rule "
    "covers the major package for people aged 40-64 years, offered every 3 years. No information is "
    "missing. The documented next step is to offer the screening package printed in the standard."
)


@pytest.fixture
def llm(monkeypatch):
    """Install a real adapter (via settings) whose HTTP call returns `reply` (or raises it)."""
    calls: list[dict] = []

    def _install(provider: str = "openai_compatible", reply=None, *, enabled=True, key=SECRET, model="m-1"):
        svc = build_ai_service(Settings(
            llm_enabled=enabled, llm_provider=provider, llm_model=model,
            llm_api_key=SecretStr(key) if key else None, llm_base_url="https://llm.example",
        ))
        app.dependency_overrides[get_ai_service] = lambda: svc

        def fake_post(url, headers, json, timeout):
            calls.append({"url": url, "headers": headers, "json": json})
            if isinstance(reply, Exception):
                raise reply
            if isinstance(reply, httpx.Response):
                return reply
            body = ({"model": model, "choices": [{"message": {"content": reply}}]} if provider == "openai_compatible"
                    else {"model": model, "content": [{"type": "text", "text": reply}]})
            return httpx.Response(200, json=body)

        monkeypatch.setattr(httpx, "post", fake_post)
        return svc

    _install.calls = calls
    yield _install
    app.dependency_overrides.pop(get_ai_service, None)


def _explain(case: tuple[str, str]) -> dict:
    resp = client.post("/api/v1/explanations", json={"patient_id": case[0], "rule_id": case[1]})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _sent_facts(call: dict) -> dict:
    payload = call["json"]
    user = payload["messages"][-1]["content"]
    return json.loads(user.removeprefix("FACTS:\n"))


_DETERMINISTIC_KEYS = ("evaluation_status", "why_identified", "care_gaps", "supporting_evidence",
                       "missing_information", "conflicting_information", "rule_meaning", "next_step",
                       "why_text", "missing_or_uncertain_text", "rule_citation_text", "warnings")


# --- providers (mocked HTTP) ----------------------------------------------------------------


@pytest.mark.parametrize("provider", ["openai_compatible", "anthropic"])
def test_mocked_provider_produces_grounded_structured_explanation(llm, provider):
    llm(provider, OPENAI_GOOD)
    body = _explain(DUE)
    assert body["generation_mode"] == LLM_GROUNDED and body["generated_explanation"] == OPENAI_GOOD
    assert body["ai"]["provider"] == provider and body["ai"]["prompt_version"] == "explanation-v2"
    assert body["evaluation_status"] == "due" and body["next_step"]["next_step"] == "offer_screening_package"
    assert body["care_gaps"][0]["status"] == "open" and body["rule_meaning"]["eligibility_as_printed"]

    (call,) = llm.calls
    sent = json.dumps(call["json"])
    assert SECRET not in sent and SECRET in json.dumps(call["headers"])
    # Minimum context: no person, evaluation or care-gap identifiers, age, sex or consent state.
    for forbidden in ("SYNTH-PAT", "SYNTH-EVL", "SYNTH-GAP", "female", "45 years", "consent"):
        assert forbidden not in sent
    facts = _sent_facts(call)
    assert facts["evaluation_status"] == "due" and facts["documented_next_step"]

    status = client.get("/api/v1/ai/status").json()
    assert status["availability"] == "last_call_succeeded" and status["configured_provider"] == provider
    assert SECRET not in json.dumps(status)
    rec = client.get("/api/v1/ai/audit?feature=explanation&limit=1").json()["items"][0]
    assert rec["audit_id"] == body["ai"]["audit_id"] and rec["provider"] == provider and rec["model"] == "m-1"
    assert rec["subject"]["evaluation_id"] == body["evaluation_id"]
    assert rec["subject"]["care_gap_ids"] == [g["care_gap_id"] for g in body["care_gaps"]]
    assert OPENAI_GOOD not in json.dumps(rec)


def test_missing_credentials_never_call_provider(llm):
    llm(key=None)
    body = _explain(DUE)
    assert llm.calls == [] and body["ai"]["fallback_reason"] == "llm_misconfigured"
    assert body["generated_explanation"] is None and body["why_identified"]
    status = client.get("/api/v1/ai/status").json()
    assert status["availability"] == "misconfigured" and "LLM_API_KEY" in status["status"]


def test_llm_disabled_keeps_deterministic_explanation(llm):
    llm(enabled=False, reply=OPENAI_GOOD)
    body = _explain(DUE)
    assert llm.calls == [] and body["ai"]["fallback_reason"] == "llm_disabled"
    assert body["generation_mode"] == DETERMINISTIC and body["generated_explanation"] is None
    assert body["supporting_evidence"] and body["next_step"]["status"] == "documented_next_step"
    assert client.get("/api/v1/ai/status").json()["availability"] == "disabled"


@pytest.mark.parametrize("reply", [
    httpx.ReadTimeout("timed out"),
    httpx.ConnectError("refused"),
    httpx.Response(200, json={"choices": []}),
    httpx.Response(200, content=b"<html>not json</html>"),
    httpx.Response(503, json={"error": "overloaded"}),
], ids=["timeout", "connect_error", "malformed_json", "non_json", "http_503"])
def test_provider_failures_fall_back_to_identical_deterministic_facts(llm, reply):
    llm("openai_compatible", OPENAI_GOOD)
    grounded = _explain(DUE)
    llm("openai_compatible", reply)
    body = _explain(DUE)
    assert body["generation_mode"] == DETERMINISTIC and body["ai"]["fallback_reason"] == "provider_error"
    assert body["generated_explanation"] is None
    assert {k: body[k] for k in _DETERMINISTIC_KEYS} == {k: grounded[k] for k in _DETERMINISTIC_KEYS}
    assert client.get("/api/v1/ai/status").json()["availability"] == "last_call_failed"


def test_anthropic_without_text_blocks_is_rejected(llm):
    llm("anthropic", httpx.Response(200, json={"model": "m-1", "content": [{"type": "tool_use"}]}))
    body = _explain(DUE)
    assert body["generation_mode"] == DETERMINISTIC and "empty_output" in body["ai"]["violations"]


# --- unsupported claims ---------------------------------------------------------------------


@pytest.mark.parametrize("violation,text", [
    ("clinical_claim", "Rule IFHAS-PKG-MAJOR-40-64: the person is diagnosed with hypertension."),
    ("risk_or_probability", "Rule IFHAS-PKG-MAJOR-40-64: this person has a high risk of disease."),
    ("invented_number", "Rule IFHAS-PKG-MAJOR-40-64 applies because the BMI is above 30.5."),
    ("overdue_claim", "Rule IFHAS-PKG-MAJOR-40-64: the person is overdue for screening."),
    ("completed_claim", "Rule IFHAS-PKG-MAJOR-40-64: the person has already completed the package."),
])
def test_unsupported_claims_are_rejected(llm, violation, text):
    llm(reply=text)
    body = _explain(DUE)
    assert body["generation_mode"] == DETERMINISTIC and body["ai"]["fallback_reason"] == "output_rejected"
    assert violation in body["ai"]["violations"] and body["generated_explanation"] is None


# --- missing / conflicting evidence ---------------------------------------------------------


def test_missing_history_is_reported_as_missing_never_as_completed_or_due(llm):
    pid, rid = UNKNOWN
    llm(reply=f"Rule {rid}: the person is due for screening and is up to date otherwise.")
    body = _explain(UNKNOWN)
    assert body["evaluation_status"] == "unknown" and body["history_status"] == "not_available"
    assert any("not available" in m and "not assumed" in m for m in body["missing_information"])
    assert not any(e["code"] == "documented_activity" for e in body["supporting_evidence"])
    assert body["next_step"] is None
    assert {"due_claim", "completed_claim"} <= set(body["ai"]["violations"])
    facts = _sent_facts(llm.calls[0])
    assert facts["history_status"] == "not_available" and facts["missing_information"]

    llm(reply=f"Rule {rid} returned unknown: screening history is not available, so no automated "
              "conclusion is made and it has not been completed or found due. No next step is documented.")
    ok = _explain(UNKNOWN)
    assert ok["generation_mode"] == LLM_GROUNDED, ok["ai"]["violations"]


def test_completion_after_evaluation_is_surfaced_as_conflict(llm):
    llm(enabled=False)
    body = _explain(SUPERSEDED)
    assert any("later closed as completed" in c for c in body["conflicting_information"])
    assert body["next_step"] is None  # no step for a closed gap
    assert any(g["status"] == "closed_completed" for g in body["care_gaps"])


def test_conflicting_records_route_to_review_and_block_eligibility_claims(llm):
    pid, rid = CONFLICTING
    llm(reply=f"Rule {rid}: the person is eligible and meets the criteria.")
    body = _explain(CONFLICTING)
    assert body["evaluation_status"] == "requires_clinical_review"
    assert any("conflicting" in c for c in body["conflicting_information"])
    assert body["next_step"]["status"] == "requires_clinical_review" and body["next_step"]["next_step"] is None
    assert "eligibility_claim" in body["ai"]["violations"]


def test_negated_status_phrasing_passes_guardrails():
    kw = dict(facts={}, max_chars=500, allow_completed=False, allow_due=False, allow_eligibility=False)
    assert validate_output("It has not been completed, is not due and is not eligible.", **kw) == []
    assert validate_output("The screening was completed.", **kw) == ["completed_claim"]
