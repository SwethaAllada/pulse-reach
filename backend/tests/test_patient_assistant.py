"""Phase 9: patient-portal assistant (isolation, minimum context, guardrails, audit) and the
patient/staff engagement journeys it sits next to. Providers are fakes - no network."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from app.core.rate_limit import reset_rate_limits
from app.main import app
from app.repositories.read_repo import get_cached_index
from app.services.ai import AIService, LLMCompletion, get_ai_service
from app.services.ai.guardrails import validate_patient_assistant_output
from identity_fixtures import client, users_mode, world  # noqa: F401

TOPICS = ("why", "next_steps", "prepare_questions", "appointments")


class FakeProvider:
    name, model = "fake", "fake-model"

    def __init__(self, reply: str) -> None:
        self.reply, self.calls = reply, []

    def complete(self, *, system: str, user: str, max_tokens: int) -> LLMCompletion:
        self.calls.append({"system": system, "user": user})
        return LLMCompletion(text=self.reply, provider=self.name, model=self.model)


@pytest.fixture
def provider():
    installed: list[AIService] = []

    def _install(reply: str) -> FakeProvider:
        fake = FakeProvider(reply)
        svc = AIService(fake, provider_status="enabled")
        installed.append(svc)
        app.dependency_overrides[get_ai_service] = lambda: svc
        return fake

    yield _install
    app.dependency_overrides.pop(get_ai_service, None)


def _ask(world, gap: str, topic: str = "why", alias: str = "patient_a", lang: str = "", **body):
    q = f"?lang={lang}" if lang else ""
    return client.post(f"/api/v1/portal/recommendations/{gap}/assistant{q}", headers=world.h(alias),
                       json={"topic": topic, **body})


def _private_values(world) -> list[str]:
    p = get_cached_index().patients_by_id[world.pid_a]
    return [world.pid_a, world.gap_a, p["given_name"], p["family_name"], str(p["date_of_birth"]),
            p["emirates_id_synthetic"], "IFHAS-PKG-MAJOR-40-64"]


# --- deterministic answers and isolation -------------------------------------------------------


@pytest.mark.parametrize("topic", TOPICS)
def test_every_topic_answers_from_the_patients_own_record_without_a_model(world, topic):
    r = _ask(world, world.gap_a, topic)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["generation_mode"] == "deterministic_fallback" and body["answer"] and body["topic"] == topic
    assert body["escalation"] and "care team" in body["escalation"] and body["disclaimer"]
    text = json.dumps(body["answer"])
    for value in _private_values(world)[2:]:  # names, DOB, Emirates ID, rule id never appear
        assert value not in text


def test_assistant_refuses_other_patients_staff_and_unlinked_accounts(world, provider):
    fake = provider("unused")
    assert _ask(world, world.gap_b).status_code == 404  # another organization's patient
    other_a = next(g["care_gap_id"] for g in get_cached_index().care_gaps_by_patient[world.pid_a_unassigned])
    assert _ask(world, other_a).status_code == 404  # another patient in the same organization
    for staff in ("cc_a", "clin_a", "phm_a", "admin_a"):
        assert _ask(world, world.gap_a, alias=staff).status_code == 403, staff
    assert _ask(world, world.gap_a, alias="outsider").status_code == 404  # not linked
    # The browser cannot name a patient; unknown fields and topics are rejected.
    assert _ask(world, world.gap_a, patient_id=world.pid_b).status_code == 422
    assert _ask(world, world.gap_a, topic="diagnose_me").status_code == 422
    assert fake.calls == []


def test_assistant_changes_nothing_and_is_audited(world):
    before = client.get(f"/api/v1/care-gaps/{world.gap_a}", headers=world.h("cc_a")).json()["status"]
    for topic in TOPICS:
        assert _ask(world, world.gap_a, topic).status_code == 200
    assert client.get(f"/api/v1/care-gaps/{world.gap_a}", headers=world.h("cc_a")).json()["status"] == before
    assert client.get("/api/v1/portal/requests", headers=world.h("patient_a")).json()["total"] == 0
    assert client.get("/api/v1/portal/follow-ups", headers=world.h("patient_a")).json()["total"] == 0
    ai = client.get("/api/v1/ai/audit?feature=patient_assistant", headers=world.h("admin_a")).json()["items"]
    assert len(ai) == 4 and {r["extra"]["topic"] for r in ai} == set(TOPICS)
    assert all(r["subject"]["patient_id"] == world.pid_a and r["extra"]["organization_id"] == world.org_a for r in ai)
    assert client.get("/api/v1/ai/audit?feature=patient_assistant", headers=world.h("admin_b")).json()["items"] == []
    ev = client.get("/api/v1/audit-events?limit=500&action=ai.patient_assistant", headers=world.h("admin_a")).json()
    assert len([e for e in ev["items"] if e["action"] == "ai.patient_assistant"]) == 4


def test_assistant_rate_limit(world):
    reset_rate_limits()
    codes = [_ask(world, world.gap_a).status_code for _ in range(21)]
    assert codes[:20] == [200] * 20 and codes[20] == 429


# --- model path: minimum context and guardrails -------------------------------------------------


GOOD_EN = ("This recommendation appears because your record does not show this preventive check. "
           "Your care team can help you arrange it.")


def test_model_sees_only_minimum_deidentified_context(world, provider):
    task = client.post("/api/v1/follow-up-tasks", headers=world.h("cc_a"), json={
        "patient_id": world.pid_a, "care_gap_id": world.gap_a, "staff_note": "INTERNAL-NOTE-XYZ"}).json()
    req = client.post("/api/v1/portal/appointment-requests", headers=world.h("patient_a"), json={
        "recommendation_id": world.gap_a, "message": "PATIENT-FREE-TEXT 0501234567"}).json()
    client.patch(f"/api/v1/patient-requests/{req['request_id']}", headers=world.h("cc_a"),
                 json={"status": "acknowledged", "internal_note": "INTERNAL-REQ-NOTE"})
    fake = provider(GOOD_EN)
    body = _ask(world, world.gap_a, "appointments").json()
    assert body["generation_mode"] == "llm_grounded" and body["answer"] == [GOOD_EN.strip()]
    sent = fake.calls[0]["user"]
    for secret in [*_private_values(world), task["task_id"], req["request_id"], "INTERNAL-NOTE-XYZ",
                   "INTERNAL-REQ-NOTE", "PATIENT-FREE-TEXT", "0501234567", world.users["cc_a"]]:
        assert secret not in sent, secret
    facts = json.loads(sent.removeprefix("FACTS:\n"))
    assert facts["topic"] == "appointments" and facts["open_requests"] and facts["follow_ups"]
    assert "Never diagnose" in fake.calls[0]["system"]


@pytest.mark.parametrize("reply,violation", [
    ("Your record suggests you have diabetes.", "clinical_claim"),
    ("Your appointment is confirmed, so nothing else is needed.", "booking_claim"),
    ("This preventive check has been completed.", "completed_claim"),
    ("You are eligible for this check.", "eligibility_claim"),
    ("We have sent you a reminder about this check.", "sent_claim"),
    ("There is a 30 percent risk if you wait.", "risk_or_probability"),
    ("Come in on Monday and we will see you.", "invented_date"),
    ("This is dangerous to ignore.", "fear_language"),
    ("هذه التوصية بسبب سجلك.", "language_mismatch"),
])
def test_unsafe_model_output_falls_back_to_the_deterministic_answer(world, provider, reply, violation):
    provider(reply)
    body = _ask(world, world.gap_a).json()
    assert body["generation_mode"] == "deterministic_fallback" and reply not in body["answer"]
    rec = client.get("/api/v1/ai/audit?feature=patient_assistant", headers=world.h("admin_a")).json()["items"][0]
    assert rec["fallback_reason"] == "output_rejected" and violation in rec["violations"]


def test_arabic_answers_are_localized_and_validated(world, provider):
    body = _ask(world, world.gap_a, "next_steps", lang="ar").json()
    assert body["locale"] == "ar" and body["direction"] == "rtl" and "فريق الرعاية" in body["escalation"]
    assert all(any("\u0600" <= c <= "\u06ff" for c in line) for line in body["answer"])
    provider("تظهر هذه التوصية لأن سجلك لا يتضمن هذا الفحص الوقائي. يمكن لفريق الرعاية مساعدتك في ترتيبه.")
    assert _ask(world, world.gap_a, lang="ar").json()["generation_mode"] == "llm_grounded"
    provider(GOOD_EN)
    assert _ask(world, world.gap_a, lang="ar").json()["generation_mode"] == "deterministic_fallback"


def test_guardrail_allows_completion_only_when_the_backend_closed_the_gap():
    facts = {"recommendation_status_code": "closed_completed"}
    text = "This preventive check has been completed and recorded by your care team."
    assert validate_patient_assistant_output(text, facts=facts, language="en", max_chars=900, allow_completed=True) == []
    assert "completed_claim" in validate_patient_assistant_output(
        text, facts=facts, language="en", max_chars=900, allow_completed=False)


# --- engagement journeys and permission boundaries ---------------------------------------------


def test_change_request_journey_patient_coordinator_patient(world):
    when = (datetime.now(timezone.utc) + timedelta(days=9)).isoformat()
    apt = client.post("/api/v1/appointments", headers=world.h("cc_a"), json={
        "patient_id": world.pid_a, "profile_id": "SYNTH-FSP-000001", "appointment_type": "ifhas_screening",
        "scheduled_datetime": when}).json()
    portal_apt = client.get(f"/api/v1/portal/appointments/{apt['appointment_id']}", headers=world.h("patient_a")).json()
    assert portal_apt["scheduled_display"].endswith(" UTC")
    r = client.post(f"/api/v1/portal/appointments/{apt['appointment_id']}/change-requests",
                    headers=world.h("patient_a"), json={"action": "reschedule", "message": "Evenings please"}).json()
    assert r["status_hint"] == "Your care team will review your request." and r["change_action_label"] == "Reschedule"
    assert r["created_display"].endswith(" UTC")
    staff = client.get("/api/v1/patient-requests?request_type=appointment_change", headers=world.h("cc_a")).json()
    assert [x["request_id"] for x in staff["items"]] == [r["request_id"]]
    client.patch(f"/api/v1/patient-requests/{r['request_id']}", headers=world.h("cc_a"), json={
        "status": "acknowledged", "staff_response": "We will offer an evening slot.", "internal_note": "INTERNAL ONLY"})
    mine = client.get("/api/v1/portal/requests", headers=world.h("patient_a")).json()["items"][0]
    assert mine["status_label"] == "Received by your care team" and mine["staff_response"] == "We will offer an evening slot."
    assert "will contact you" in mine["status_hint"] and "INTERNAL" not in json.dumps(mine)
    ar = client.get("/api/v1/portal/requests?lang=ar", headers=world.h("patient_a")).json()["items"][0]
    assert ar["status_hint"] == "يعمل فريق الرعاية على طلبك وسيتواصل معك."


def test_staff_scope_for_patient_questions_and_requests(world):
    task = client.post("/api/v1/follow-up-tasks", headers=world.h("cc_a"),
                       json={"patient_id": world.pid_a, "care_gap_id": world.gap_a}).json()
    client.post(f"/api/v1/portal/follow-ups/{task['task_id']}/responses", headers=world.h("patient_a"),
                json={"response": "question", "message": "Do I need to fast?"})
    req = client.post("/api/v1/portal/assistance", headers=world.h("patient_a"), json={"message": "Please call"}).json()
    # Clinician: reviews the patient's question on an assigned patient's follow-up; no request queue.
    clin = client.get(f"/api/v1/follow-up-tasks/{task['task_id']}", headers=world.h("clin_a")).json()
    assert any(e["message"] == "Do I need to fast?" for e in clin["events"])
    assert client.get("/api/v1/patient-requests", headers=world.h("clin_a")).status_code == 403
    assert client.patch(f"/api/v1/follow-up-tasks/{task['task_id']}", headers=world.h("clin_a"),
                        json={"status": "in_progress"}).status_code == 403
    # Other organization: invisible.
    assert client.get(f"/api/v1/patient-requests/{req['request_id']}", headers=world.h("cc_b")).status_code == 404
    assert client.patch(f"/api/v1/patient-requests/{req['request_id']}", headers=world.h("phm_b"),
                        json={"status": "closed"}).status_code == 404
    assert req["request_id"] not in json.dumps(client.get("/api/v1/patient-requests", headers=world.h("phm_b")).json())
    # Population health manager: no portal access; patients: no staff endpoints.
    assert client.get("/api/v1/portal/summary", headers=world.h("phm_a")).status_code == 403
    for path in ("/api/v1/patient-requests", f"/api/v1/follow-up-tasks/{task['task_id']}", "/api/v1/follow-up-tasks"):
        assert client.get(path, headers=world.h("patient_a")).status_code == 403, path
    fu = client.get(f"/api/v1/portal/follow-ups/{task['task_id']}", headers=world.h("patient_a")).json()
    assert fu["status_hint"] == "Your care team has your reply and will follow up." and fu["updated_display"]
