"""AI-assisted outreach drafts (`POST /outreach/draft`) and human review (`/outreach/draft/review`).

Providers are exercised through the real HTTP adapters with `httpx.post` mocked; this proves the
gate ordering, request content, guardrails and fallbacks, not live provider integration.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core.config import Settings
from app.main import app
from app.repositories.followup_repo import get_memory_follow_up_events, reset_memory_writes
from app.repositories.read_repo import MemoryReadRepository, get_cached_dataset, get_cached_index
from app.services.ai import build_ai_service, get_ai_service
from app.services.ai.guardrails import validate_outreach_output
from app.services.outreach.drafting import CHANNEL_MAX_CHARS, deterministic_draft

client = TestClient(app)
SECRET = "sk-test-SECRET-outreach-555"
PID = "SYNTH-PAT-000001"  # recorded contact channel: phone
GOOD = (
    "Hello, this is the IFHAS preventive screening programme. Our records show that no preventive "
    "screening is documented for you. We warmly invite you to contact your preventive-care provider "
    "to arrange the programme screening. For any questions, please consult a licensed healthcare "
    "professional."
)
ALLOWED_FACT_KEYS = {"programme", "care_gap_category", "approved_next_step", "channel", "language", "tone"}


def _allowed_rule() -> str:
    for g in get_cached_index().care_gaps_by_patient[PID]:
        if g["status"] == "open" and client.post("/api/v1/outreach/preview", json={
                "patient_id": PID, "rule_id": g["rule_id"], "channel": "phone"}).json()["allowed"]:
            return g["rule_id"]
    raise AssertionError("no allowed outreach for fixture patient")


RULE = _allowed_rule()
REQ = {"patient_id": PID, "rule_id": RULE, "channel": "phone", "language": "en", "tone": "supportive"}


@pytest.fixture
def llm(monkeypatch):
    """Install a real adapter (via settings); every `httpx.post` is recorded and answered with `reply`."""
    calls: list[dict] = []

    def _install(reply=GOOD, *, provider="openai_compatible", enabled=True, key=SECRET):
        svc = build_ai_service(Settings(
            llm_enabled=enabled, llm_provider=provider, llm_model="m-1",
            llm_api_key=SecretStr(key) if key else None, llm_base_url="https://llm.example",
        ))
        app.dependency_overrides[get_ai_service] = lambda: svc

        def fake_post(url, headers, json, timeout):
            calls.append({"url": url, "headers": headers, "json": json})
            if isinstance(reply, Exception):
                raise reply
            if isinstance(reply, httpx.Response):
                return reply
            body = ({"model": "m-1", "choices": [{"message": {"content": reply}}]} if provider == "openai_compatible"
                    else {"model": "m-1", "content": [{"type": "text", "text": reply}]})
            return httpx.Response(200, json=body)

        monkeypatch.setattr(httpx, "post", fake_post)
        return svc

    _install.calls = calls
    yield _install
    app.dependency_overrides.pop(get_ai_service, None)
    reset_memory_writes()


@pytest.fixture
def records(monkeypatch):
    """Transform the (patient, evaluations, care gaps, consents) the draft gate reads."""
    original = MemoryReadRepository.get_patient_outreach_inputs

    def _set(fn):
        def patched(self, patient_id):
            p, evals, gaps, consents = original(self, patient_id)
            return fn(dict(p), list(evals), [dict(g) for g in gaps], [dict(c) for c in consents])
        monkeypatch.setattr(MemoryReadRepository, "get_patient_outreach_inputs", patched)
    return _set


def _draft(**overrides) -> dict:
    resp = client.post("/api/v1/outreach/draft", json={**REQ, **overrides})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _assert_blocked(body: dict, reason: str, calls: list) -> None:
    assert body["allowed"] is False and body["blocked_reason"] == reason
    assert body["generation_status"] == "blocked" and body["draft_message"] is None
    assert body["draft_body"] is None and body["ai"] is None and body["review_status"] == "not_applicable"
    assert calls == []  # the provider is never consulted when a check fails


def _contact(consents):
    return [c for c in consents if c["consent_type"] == "contact"]


# --- 1. success ---------------------------------------------------------------------------


@pytest.mark.parametrize("provider", ["openai_compatible", "anthropic"])
def test_valid_consent_generates_reviewable_draft_with_minimal_context(llm, provider):
    llm(provider=provider)
    body = _draft()
    assert body["allowed"] and body["generation_status"] == "generated" and not body["is_fallback"]
    assert body["draft_body"] == GOOD and body["draft_message"] == "[SIMULATED OUTREACH PREVIEW — PHONE (en)] " + GOOD
    assert (body["channel"], body["language"], body["tone"], body["recipient"]) == ("phone", "en", "supportive", "patient")
    assert body["review_status"] == "pending_review" and body["simulated_outreach_status"] is None
    assert body["sendable"] is False and body["simulated_only"] is True
    assert body["next_step"]["status"] == "documented_next_step"
    assert body["ai"]["prompt_version"] == "outreach-v3" and body["ai"]["provider"] == provider

    (call,) = llm.calls
    payload = call["json"]
    user = payload["messages"][-1]["content"]
    facts = json.loads(user.removeprefix("FACTS:\n"))
    assert set(facts) == ALLOWED_FACT_KEYS and facts["channel"] == "phone" and facts["tone"] == "supportive"
    p = get_cached_index().patients_by_id[PID]
    # The static system prompt is fixed text; the per-person data the provider receives is `user`.
    for forbidden in ("SYNTH-", p["given_name"], p["family_name"], p["phone_synthetic"], p["email_synthetic"],
                      p["emirates_id_synthetic"], "female", "consent", "granted", RULE):
        assert forbidden not in user
    assert SECRET not in json.dumps(payload) and SECRET in json.dumps(call["headers"])


# --- 2-9. gate failures: no provider call, no draft, no fallback ----------------------------


def test_missing_consent(llm, records):
    llm()
    records(lambda p, e, g, c: (p, e, g, [x for x in c if x["consent_type"] != "contact"]))
    _assert_blocked(_draft(), "contact_consent_absent", llm.calls)


def test_withdrawn_consent_overrides_older_grant(llm, records):
    llm()

    def withdraw(p, e, g, c):
        newer = {**_contact(c)[0], "consent_id": "SYNTH-CNS-999999", "state": "withdrawn",
                 "recorded_at": datetime.now(timezone.utc)}
        return p, e, g, c + [newer]
    records(withdraw)
    _assert_blocked(_draft(), "contact_consent_withdrawn", llm.calls)


def test_expired_consent(llm, records):
    llm()

    def expire(delta):
        def fn(p, e, g, c):
            for x in _contact(c):
                x["expires_at"] = datetime.now(timezone.utc) + delta
            return p, e, g, c
        return fn
    records(expire(timedelta(days=-1)))
    _assert_blocked(_draft(), "contact_consent_expired", llm.calls)
    records(expire(timedelta(days=30)))
    assert _draft()["allowed"] is True


def test_consent_does_not_permit_requested_channel(llm, records):
    llm()
    _assert_blocked(_draft(channel="sms"), "channel_not_permitted", llm.calls)
    records(lambda p, e, g, c: ({**p, "phone_synthetic": None}, e, g, c))
    _assert_blocked(_draft(), "contact_details_missing_for_channel", llm.calls)


@pytest.mark.parametrize("channel", ["whatsapp", "SMS", "letter"])
def test_unsupported_channel(llm, channel):
    llm()
    _assert_blocked(_draft(channel=channel), "channel_unsupported", llm.calls)


@pytest.mark.parametrize("language", ["fr", "EN", "AR", "ur"])
def test_unsupported_language_is_never_silently_english(llm, language):
    llm()
    body = _draft(language=language)
    _assert_blocked(body, "language_unsupported", llm.calls)
    assert body["language"] == language


def test_closed_or_mismatched_care_gap(llm, records):
    llm()
    gap_id = next(g["care_gap_id"] for g in get_cached_index().care_gaps_by_patient[PID]
                  if g["rule_id"] == RULE and g["status"] == "open")
    _assert_blocked(_draft(care_gap_id="SYNTH-GAP-999999"), "care_gap_not_open", llm.calls)
    assert _draft(care_gap_id=gap_id)["care_gap_id"] == gap_id
    llm.calls.clear()
    records(lambda p, e, g, c: (p, e, [{**x, "status": "closed_completed"} if x["rule_id"] == RULE else x
                                       for x in g], c))
    _assert_blocked(_draft(), "no_open_care_gap", llm.calls)


def test_care_gap_without_supported_next_step(llm, records):
    llm()
    records(lambda p, e, g, c: (p, e, [{**x, "gap_type": "undocumented_type"} if x["rule_id"] == RULE else x
                                       for x in g], c))
    _assert_blocked(_draft(), "no_supported_next_step", llm.calls)


def test_unknown_patient_is_404(llm):
    llm()
    assert client.post("/api/v1/outreach/draft", json={**REQ, "patient_id": "SYNTH-PAT-999999"}).status_code == 404
    assert client.post("/api/v1/outreach/draft", json={**REQ, "patient_id": "SYNTH-PAT-999999",
                                                       "channel": "whatsapp"}).status_code == 404


# --- 10-15. provider failures and unsafe output fall back to the deterministic draft ---------


def _expected_fallback(body: dict) -> None:
    """The deterministic phone draft, built from the same approved facts."""
    assert body["draft_body"].startswith("Hello, I am calling from the IFHAS preventive screening programme.")
    assert body["draft_body"].endswith("please consult a licensed healthcare professional.")


@pytest.mark.parametrize("reply,reason", [
    (httpx.ConnectError("refused"), "provider_error"),
    (httpx.Response(503, json={"error": "unavailable"}), "provider_error"),
    (httpx.ReadTimeout("timed out"), "provider_error"),
    (httpx.Response(200, json={"choices": [{"message": {}}]}), "provider_error"),
    (httpx.Response(200, content=b"not json"), "provider_error"),
], ids=["unavailable", "http_503", "timeout", "malformed", "non_json"])
def test_provider_failures_fall_back(llm, reply, reason):
    llm(reply)
    body = _draft()
    assert body["allowed"] and body["generation_status"] == "fallback" and body["is_fallback"]
    assert body["ai"]["fallback_reason"] == reason and body["review_status"] == "pending_review"
    _expected_fallback(body)


@pytest.mark.parametrize("violation,text", [
    ("clinical_claim", "Hello. Your results suggest cancer; please consult a licensed healthcare professional."),
    ("risk_or_probability", "Hello, you have a high risk; please consult a licensed healthcare professional."),
    ("invented_logistics", "Hello, your appointment at the Al Noor clinic is on Monday. Please consult a licensed healthcare professional."),
    ("invented_logistics", "Hello, the screening is free of charge. Please consult a licensed healthcare professional."),
    ("invented_number", "Hello, please visit within 14 days and consult a licensed healthcare professional."),
    ("coercive_or_requirement", "Hello, you must contact your provider immediately. Please consult a licensed healthcare professional."),
    ("fear_language", "Hello, skipping screening is dangerous. Please consult a licensed healthcare professional."),
    ("completed_claim", "Hello, your screening was completed. Please consult a licensed healthcare professional."),
    ("overdue_claim", "Hello, your screening is overdue. Please consult a licensed healthcare professional."),
    ("eligibility_claim", "Hello, you are eligible for screening. Please consult a licensed healthcare professional."),
    ("personal_identifier", "Hello SYNTH-PAT-000001, please consult a licensed healthcare professional."),
    ("link", "Hello, see www.example.com and consult a licensed healthcare professional."),
    ("missing:professional", "Hello, please contact your preventive-care provider."),
    ("format_line_breaks", "Hello.\nPlease consult a licensed healthcare professional."),
    ("language_mismatch", "مرحبا. Please consult a licensed healthcare professional."),
])
def test_unsafe_generated_content_is_rejected(llm, violation, text):
    llm(text)
    body = _draft()
    assert body["is_fallback"] and body["ai"]["fallback_reason"] == "output_rejected"
    assert violation in body["ai"]["violations"] and body["draft_body"] != text
    _expected_fallback(body)


def test_llm_disabled_returns_validated_deterministic_draft_only_after_gate(llm, records):
    llm(enabled=False)
    body = _draft()
    assert llm.calls == [] and body["generation_status"] == "fallback" and body["ai"]["fallback_reason"] == "llm_disabled"
    records(lambda p, e, g, c: (p, e, g, [x for x in c if x["consent_type"] != "contact"]))
    _assert_blocked(_draft(), "contact_consent_absent", llm.calls)  # no fallback template either


def test_every_deterministic_draft_passes_its_own_validation():
    from app.services.outreach.drafting import _GAP_CATEGORY_TEXT, _NEXT_STEP_TEXT, PROGRAMME_NAMES

    for (pathway, _), category in _GAP_CATEGORY_TEXT.items():
        for step in _NEXT_STEP_TEXT.values():
            for channel, max_chars in CHANNEL_MAX_CHARS.items():
                facts = {"programme": PROGRAMME_NAMES[pathway], "care_gap_category": category,
                         "approved_next_step": step, "channel": channel, "language": "en", "tone": "neutral"}
                text = deterministic_draft(facts, channel)
                assert validate_outreach_output(text, facts=facts, channel=channel, language="en",
                                                max_chars=max_chars) == [], (pathway, channel, text)


# --- 16-18. review, simulated delivery and audit ---------------------------------------------


def _review(draft: dict, **kw) -> httpx.Response:
    return client.post("/api/v1/outreach/draft/review", json={
        "draft_audit_id": draft["ai"]["audit_id"], "patient_id": PID, "rule_id": RULE,
        "care_gap_id": draft["care_gap_id"], "channel": "phone", "language": "en",
        "reviewed_by": "coordinator.test", **kw})


def test_approval_records_simulated_outreach_and_never_delivers(llm):
    llm()
    outreach_events_before = len(get_cached_dataset().outreach_events)
    draft = _draft()
    resp = _review(draft, decision="approved", final_message=draft["draft_message"])
    assert resp.status_code == 200, resp.text
    out = resp.json()
    assert out["review_status"] == "approved" and out["edited"] is False
    assert out["simulated_outreach_status"] == "simulated_not_sent"
    assert out["delivered"] is False and out["sendable"] is False and out["simulated_only"] is True
    fu = out["follow_up"]
    assert fu["event_type"] == "outreach_attempted" and fu["outcome_status"] == "simulated_not_sent"
    assert fu["contact_consent_id"] and "not sent" in fu["note"] and GOOD not in fu["note"]
    assert [e["follow_up_id"] for e in get_memory_follow_up_events(draft["care_gap_id"])] == [fu["follow_up_id"]]
    # Nothing was delivered: no outreach event row, and the only HTTP traffic was the model call.
    assert len(get_cached_dataset().outreach_events) == outreach_events_before
    assert [c["url"] for c in llm.calls] == ["https://llm.example/chat/completions"]


def test_edited_approval_is_revalidated(llm):
    llm()
    draft = _draft()
    bad = _review(draft, decision="approved",
                  final_message="Your appointment is on Monday. Please consult a licensed healthcare professional.")
    assert bad.status_code == 422 and "invented_logistics" in bad.json()["detail"]["violations"]
    assert get_memory_follow_up_events(draft["care_gap_id"]) == []  # an invalid text records nothing

    edited = GOOD.replace("We warmly invite", "We invite")
    ok = _review(draft, decision="approved", final_message=edited).json()
    assert ok["review_status"] == "approved" and ok["edited"] is True
    assert len(get_memory_follow_up_events(draft["care_gap_id"])) == 1  # only the valid approval


def test_approval_cannot_be_replayed(llm):
    llm()
    draft = _draft()
    first = _review(draft, decision="approved", final_message=GOOD).json()
    for kw in ({"decision": "approved", "final_message": GOOD}, {"decision": "rejected"}):
        again = _review(draft, **kw)
        assert again.status_code == 409, again.text
        detail = again.json()["detail"]
        assert detail["code"] == "draft_already_reviewed" and detail["review_status"] == "approved"
        assert detail["follow_up_id"] == first["follow_up"]["follow_up_id"]
    assert len(get_memory_follow_up_events(draft["care_gap_id"])) == 1


def test_rejected_draft_cannot_be_approved_later(llm):
    llm()
    draft = _draft()
    assert _review(draft, decision="rejected").json()["review_status"] == "rejected"
    late = _review(draft, decision="approved", final_message=GOOD)
    assert late.status_code == 409 and late.json()["detail"]["review_status"] == "rejected"
    assert get_memory_follow_up_events(draft["care_gap_id"]) == []


def test_concurrent_approvals_record_one_simulated_outreach(llm):
    from concurrent.futures import ThreadPoolExecutor

    llm()
    draft = _draft()
    with ThreadPoolExecutor(max_workers=6) as pool:
        codes = sorted(pool.map(lambda _: _review(draft, decision="approved", final_message=GOOD).status_code,
                                range(6)))
    assert codes == [200, 409, 409, 409, 409, 409]
    assert len(get_memory_follow_up_events(draft["care_gap_id"])) == 1


def test_blocked_draft_cannot_be_reviewed(llm):
    llm()
    blocked = _draft(channel="sms")
    assert blocked["ai"] is None
    audit_id = client.get("/api/v1/ai/audit?limit=1").json()["items"][0]["audit_id"]
    resp = _review({**blocked, "ai": {"audit_id": audit_id}, "care_gap_id": blocked["care_gap_id"]},
                   decision="approved", final_message=GOOD, channel="sms")
    assert resp.status_code == 404


def test_rejection_and_mismatched_or_unknown_drafts(llm):
    llm()
    draft = _draft()
    out = _review(draft, decision="rejected", reason="tone").json()
    assert out["review_status"] == "rejected" and out["follow_up"] is None and out["simulated_outreach_status"] is None
    assert get_memory_follow_up_events(draft["care_gap_id"]) == []
    assert _review(draft, decision="approved", final_message=GOOD, channel="sms").status_code == 409
    assert _review({**draft, "ai": {"audit_id": "nope"}}, decision="approved", final_message=GOOD).status_code == 404


def test_approval_rechecks_consent(llm, records):
    llm()
    draft = _draft()
    records(lambda p, e, g, c: (p, e, g, [x for x in c if x["consent_type"] != "contact"]))
    out = _review(draft, decision="approved", final_message=GOOD).json()
    assert out["review_status"] == "blocked" and out["blocked_reason"] == "contact_consent_absent"
    assert out["follow_up"] is None and get_memory_follow_up_events(draft["care_gap_id"]) == []


def test_audit_records_generation_block_and_review_without_message_text(llm):
    llm()
    draft = _draft()
    _draft(channel="sms")
    _review(draft, decision="approved", final_message=GOOD)

    review, blocked, gen = client.get("/api/v1/ai/audit?limit=3").json()["items"]
    assert gen["audit_id"] == draft["ai"]["audit_id"] and gen["feature"] == "outreach_draft"
    assert gen["subject"] == {"patient_id": PID, "rule_id": RULE, "care_gap_id": draft["care_gap_id"]}
    assert (gen["prompt_version"], gen["provider"], gen["model"], gen["generation_mode"]) == (
        "outreach-v3", "openai_compatible", "m-1", "llm_grounded")
    assert gen["extra"]["channel"] == "phone" and gen["extra"]["language"] == "en"
    assert gen["extra"]["tone"] == "supportive" and len(gen["extra"]["returned_sha256"]) == 64

    assert blocked["generation_mode"] == "not_generated" and blocked["provider"] is None
    assert blocked["fallback_reason"] == "blocked:channel_not_permitted" and blocked["extra"]["channel"] == "sms"

    assert review["feature"] == "outreach_review" and review["generation_mode"] == "human_approved"
    assert review["extra"]["draft_audit_id"] == gen["audit_id"] and review["extra"]["edited"] is False
    assert review["extra"]["simulated_outreach_status"] == "simulated_not_sent"
    assert review["extra"]["follow_up_id"]

    dumped = json.dumps(client.get("/api/v1/ai/audit").json())
    assert GOOD not in dumped and SECRET not in dumped
    assert client.get("/api/v1/ai/audit?feature=outreach_review").json()["items"][0]["audit_id"] == review["audit_id"]
