"""English/Arabic localization: catalog, negotiation, persistence, UTF-8, determinism, Arabic AI."""

from __future__ import annotations

import re
import string
from datetime import date

import httpx
import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.core.i18n import MESSAGES, format_date, parse_accept_language, t
from app.main import app
from app.services.ai import build_ai_service, get_ai_service
from app.services.ai.guardrails import validate_outreach_output
from identity_fixtures import RULE_A, client, users_mode, world  # noqa: F401

ARABIC = re.compile(r"[\u0600-\u06FF]")


def _fields(template: str) -> set[str]:
    return {f for _, f, _, _ in string.Formatter().parse(template) if f}


def test_catalog_has_both_locales_with_identical_placeholders():
    for key, entry in MESSAGES.items():
        assert set(entry) == {"en", "ar"}, key
        assert _fields(entry["en"]) == _fields(entry["ar"]), key
        assert ARABIC.search(entry["ar"]), key


def test_arabic_interpolation_isolates_values_and_dates_are_localized():
    out = t("explain.next_due", "ar", next_due_date=format_date(date(2026, 11, 16), "ar"))
    assert "\u2068" in out and "\u2069" in out and "16 نوفمبر 2026" in out
    assert t("explain.next_due", "en", next_due_date="16 November 2026") == "The next recommended date is 16 November 2026."
    assert format_date(date(2026, 1, 5), "en") == "5 January 2026"


@pytest.mark.parametrize("header,expected", [
    ("ar", "ar"), ("ar-AE,en;q=0.5", "ar"), ("en-GB,ar;q=0.9", "en"), ("fr-FR,ar;q=0.4", "ar"),
    ("fr", None), ("", None), ("en;q=0,ar;q=0.1", "ar"),
])
def test_accept_language_parsing(header, expected):
    assert parse_accept_language(header) == expected


def test_portal_in_english_and_arabic(world):
    h = world.h("patient_a")
    en = client.get("/api/v1/portal/recommendations", headers=h)
    ar = client.get("/api/v1/portal/recommendations?lang=ar", headers=h)
    assert en.json()["locale"] == "en" and en.json()["direction"] == "ltr"
    assert ar.json()["locale"] == "ar" and ar.json()["direction"] == "rtl"
    e, a = en.json()["items"][0], ar.json()["items"][0]
    assert ARABIC.search(a["title"]) and not ARABIC.search(e["title"])
    # Machine values are never translated.
    for k in ("recommendation_id", "rule_id", "programme", "gap_type", "status", "identified_date", "next_step"):
        assert e[k] == a[k]
    assert "نوفمبر" in a["identified_date_display"] or ARABIC.search(a["identified_date_display"])
    # An authenticated user's stored preference outranks the browser header.
    hdr = client.get("/api/v1/portal/summary", headers={**h, "Accept-Language": "ar-AE"})
    assert hdr.json()["direction"] == "ltr"


def test_registration_takes_the_language_from_accept_language(users_mode):
    body = {"email": "lang.ar@test.pulsereach.invalid", "password": "Arabic-Speaker-Pass-1", "full_name": "A"}
    r = client.post("/api/v1/auth/register", json=body, headers={"Accept-Language": "ar-AE,en;q=0.5"})
    assert r.json()["locale"] == "ar"
    tok = client.post("/api/v1/auth/login", json={"email": body["email"], "password": body["password"]}).json()
    assert tok["user"]["preferred_language"] == "ar"


def test_language_preference_persists_and_drives_responses(world):
    h = world.h("patient_a")
    assert client.get("/api/v1/me/preferences", headers=h).json()["preferred_language"] == "en"
    r = client.patch("/api/v1/me/preferences", headers=h, json={"preferred_language": "ar"})
    assert r.status_code == 200 and r.json()["locale"] == "ar" and r.json()["direction"] == "rtl"
    assert client.get("/api/v1/me", headers=h).json()["user"]["preferred_language"] == "ar"
    # Preference wins over the browser header; ?lang= wins over both.
    assert client.get("/api/v1/portal/summary", headers={**h, "Accept-Language": "en"}).json()["locale"] == "ar"
    assert client.get("/api/v1/portal/summary?lang=en", headers=h).json()["locale"] == "en"
    assert client.patch("/api/v1/me/preferences", headers=h, json={"preferred_language": "fr"}).status_code == 422


def test_unsupported_locale_falls_back(world):
    h = world.h("patient_a")
    assert client.get("/api/v1/portal/summary?lang=fr", headers=h).json()["locale"] == "en"
    assert client.get("/api/v1/portal/summary", headers={**h, "Accept-Language": "de"}).json()["locale"] == "en"


def test_error_messages_are_localized_but_detail_is_stable(users_mode):
    en = client.get("/api/v1/patients")
    ar = client.get("/api/v1/patients", headers={"Accept-Language": "ar"})
    assert en.status_code == ar.status_code == 401
    assert en.json()["detail"] == ar.json()["detail"]
    assert ar.json()["error"]["message"] == MESSAGES["auth.not_authenticated"]["ar"]
    assert ar.json()["error"]["locale"] == "ar" and ar.headers["content-language"] == "ar"
    bad = client.post("/api/v1/auth/login?lang=ar", json={"email": "x"})
    assert bad.status_code == 422 and ARABIC.search(bad.json()["error"]["message"])
    wrong = client.post("/api/v1/auth/login?lang=ar", json={"email": "nobody@x.invalid", "password": "x"})
    assert wrong.json()["error"]["message"] == MESSAGES["auth.invalid_credentials"]["ar"]


def test_arabic_text_round_trips_as_utf8(world):
    h = world.h("patient_a")
    name = "نورة الظاهري (synthetic)"
    assert client.patch("/api/v1/me", headers=h, json={"full_name": name}).json()["user"]["full_name"] == name
    msg = "أحتاج إلى مساعدة في حجز الفحص، شكرًا"
    req = client.post("/api/v1/portal/assistance?lang=ar", headers=h, json={"message": msg})
    assert req.status_code == 201 and req.json()["message"] == msg
    assert req.headers["content-type"].startswith("application/json")
    staff = client.get(f"/api/v1/patient-requests/{req.json()['request_id']}", headers=world.h("cc_a")).json()
    assert staff["message"] == msg and staff["language"] == "ar"


def test_task_message_follows_the_patient_language(world):
    task = client.post("/api/v1/follow-up-tasks", headers=world.h("cc_a"),
                       json={"patient_id": world.pid_a, "language": "ar"}).json()
    assert task["language"] == "ar" and ARABIC.search(task["patient_message"])
    en = client.get(f"/api/v1/portal/follow-ups/{task['task_id']}?lang=en", headers=world.h("patient_a")).json()
    assert not ARABIC.search(en["message"]) and en["status_label"] == "Waiting for your reply"


def test_language_never_changes_clinical_results(world):
    h = world.h("phm_a")
    staff = [client.get(f"/api/v1/patients/{world.pid_a}/evaluations{q}", headers={**h, **hdr}).json()
             for q, hdr in (("", {}), ("?lang=ar", {}), ("", {"Accept-Language": "ar"}))]
    assert staff[0] == staff[1] == staff[2]
    ad_hoc = [client.post(f"/api/v1/evaluations{q}", headers=h, json={"patient_id": world.pid_a, "look_ahead_days": 90}).json()
              for q in ("", "?lang=ar")]
    for x in ad_hoc:
        for e in x["evaluations"]:
            e.pop("evaluated_at")
    assert ad_hoc[0] == ad_hoc[1]
    assert client.get("/api/v1/dashboard/summary", headers=h).json() == \
        client.get("/api/v1/dashboard/summary?lang=ar", headers=h).json()
    p = world.h("patient_a")
    pe, pa = (client.get(f"/api/v1/portal/evaluations{q}", headers=p).json()["items"] for q in ("", "?lang=ar"))
    assert [(i["rule_id"], i["status"], i["next_due_date"]) for i in pe] == \
        [(i["rule_id"], i["status"], i["next_due_date"]) for i in pa]
    client.patch("/api/v1/me/preferences", headers=p, json={"preferred_language": "ar"})
    pr = client.get("/api/v1/portal/evaluations", headers=p).json()["items"]
    assert [(i["rule_id"], i["status"]) for i in pr] == [(i["rule_id"], i["status"]) for i in pe]


# --- Arabic outreach drafts (simulated, human-reviewed) --------------------------------------

AR_GOOD = ("مرحبًا، معك برنامج الفحص الوقائي IFHAS. تُظهر سجلاتنا أن لا يوجد فحص وقائي موثّق لك. "
           "ندعوك إلى التواصل مع مقدّم الرعاية الوقائية لترتيب فحص البرنامج. لأي استفسار، يُرجى استشارة "
           "مختص رعاية صحية مرخّص.")


@pytest.fixture
def llm(monkeypatch):
    calls: list[dict] = []

    def install(reply):
        svc = build_ai_service(Settings(llm_enabled=True, llm_provider="openai_compatible", llm_model="m-1",
                                        llm_api_key=SecretStr("sk-test"), llm_base_url="https://llm.example"))
        app.dependency_overrides[get_ai_service] = lambda: svc

        def fake_post(url, headers, json, timeout):
            calls.append(json)
            return httpx.Response(200, json={"model": "m-1", "choices": [{"message": {"content": reply}}]})

        monkeypatch.setattr(httpx, "post", fake_post)
        return svc

    install.calls = calls
    yield install
    app.dependency_overrides.pop(get_ai_service, None)


def _draft(world, **kw):
    body = {"patient_id": world.pid_a, "rule_id": RULE_A, "channel": "phone", "language": "ar", **kw}
    return client.post("/api/v1/outreach/draft", headers=world.h("cc_a"), json=body).json()


def test_arabic_draft_deterministic_fallback_is_valid_arabic(world):
    d = _draft(world)
    assert d["allowed"] is True and d["language"] == "ar" and d["ai"]["fallback_reason"] == "llm_disabled"
    assert ARABIC.search(d["draft_body"]) and "مختص" in d["draft_body"]
    assert validate_outreach_output(d["draft_body"], facts={}, channel="phone", language="ar", max_chars=500) == []
    assert d["sendable"] is False and d["simulated_only"] is True


def test_arabic_llm_output_is_validated_under_the_same_policy(world, llm):
    llm(AR_GOOD)
    good = _draft(world)
    assert good["ai"]["generation_mode"] == "llm_grounded" and good["draft_body"] == AR_GOOD
    assert "Modern Standard Arabic" in llm.calls[-1]["messages"][0]["content"]
    for bad, violation in (
        ("Hello, please consult a licensed healthcare professional.", "language_mismatch"),
        (AR_GOOD.replace("ندعوك", "يجب عليك فورًا"), "coercive_or_requirement"),
        (AR_GOOD.replace("لترتيب فحص البرنامج", "لحجز موعد غدًا في العيادة"), "invented_logistics"),
        (AR_GOOD.replace("لا يوجد فحص وقائي موثّق لك", "لديك خطر الإصابة بالسرطان"), "clinical_claim"),
        (AR_GOOD.replace("مختص رعاية صحية مرخّص", "طبيب"), "missing:مختص"),
        (AR_GOOD + " ٩٩٪", "invented_number"),
    ):
        llm(bad)
        d = _draft(world)
        assert d["ai"]["generation_mode"] == "deterministic_fallback", bad
        assert violation in d["ai"]["violations"], (violation, d["ai"]["violations"])
        assert d["draft_body"] != bad and ARABIC.search(d["draft_body"])


def test_arabic_draft_review_records_simulated_attempt(world):
    d = _draft(world)
    r = client.post("/api/v1/outreach/draft/review", headers=world.h("cc_a"), json={
        "draft_audit_id": d["ai"]["audit_id"], "patient_id": world.pid_a, "rule_id": RULE_A,
        "care_gap_id": d["care_gap_id"], "channel": "phone", "language": "ar", "decision": "approved",
        "final_message": d["draft_body"]})
    assert r.status_code == 200, r.text
    assert r.json()["review_status"] == "approved" and r.json()["simulated_outreach_status"] == "simulated_not_sent"
    edited = client.post("/api/v1/outreach/draft/review", headers=world.h("cc_a"), json={
        "draft_audit_id": _draft(world)["ai"]["audit_id"], "patient_id": world.pid_a, "rule_id": RULE_A,
        "care_gap_id": d["care_gap_id"], "channel": "phone", "language": "ar", "decision": "approved",
        "final_message": "Please book now"})
    assert edited.status_code in (409, 422)
