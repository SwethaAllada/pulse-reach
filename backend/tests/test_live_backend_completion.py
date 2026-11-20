"""Backend completion on a fresh, disposable PostgreSQL database (`TEST_DATABASE_URL`).

Every test here runs the real API in `DATA_SOURCE=db` mode (or the real repositories / Alembic)
against a scratch database created for this module: migrations to head, the official loader, the
synthetic seed (twice, for idempotency). Nothing is mocked except the absent LLM provider
(disabled, so drafts use the validated deterministic fallback).
"""

from __future__ import annotations

import argparse
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from alembic import command
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings, settings
from app.db.session import get_engine
from app.main import app
from app.repositories.followup_repo import PostgresFollowUpRepository
from app.repositories.read_repo import MemoryReadRepository, PostgresReadRepository
from app.schemas.v1 import AppointmentCreateIn, AppointmentPatchIn, FollowUpCreateIn
from app.services.ai import build_ai_service, get_ai_service

pytestmark = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set")

BACKEND = Path(__file__).resolve().parents[1]
WHO = "coordinator.live"
PID, RULE, GAP = "SYNTH-PAT-000001", "IFHAS-PKG-MAJOR-40-64", "SYNTH-GAP-000001"
REFERRAL_GAP, REFERRAL_ID = "SYNTH-GAP-000026", "SYNTH-REF-000001"
DRAFT = {"patient_id": PID, "rule_id": RULE, "channel": "phone", "language": "en", "tone": "supportive"}

client = TestClient(app)


def _alembic_cfg(allow_data_loss: bool = False):
    from test_official_integrity import alembic_config

    cfg = alembic_config()
    if allow_data_loss:
        cfg.cmd_opts = argparse.Namespace(x=["allow_data_loss=true"])
    return cfg


def _seed(eng) -> dict:
    from app.services import official_loader
    from app.services.synthetic_generator import seed as seed_cmd

    with eng.connect() as conn:
        if conn.execute(text("SELECT count(*) FROM official.facility")).scalar_one() == 0:
            assert official_loader.run(engine=eng)["quarantined"] == []
    return seed_cmd.seed_database(engine=eng)


def _new_ai():
    return build_ai_service(Settings(data_source="db", llm_enabled=False))


@pytest.fixture(scope="module")
def db():
    """Fresh database: migrate, load official data, seed twice, then serve the API from it."""
    from test_official_integrity import scratch_database

    with scratch_database() as url:
        command.upgrade(_alembic_cfg(), "head")
        eng = create_engine(url)
        first = _seed(eng)
        again = _seed(eng)  # repeatable: same run replaced, identical reconciliation
        assert first["reconciliation"] == again["reconciliation"]
        assert again["clinical"]["load_id"] == first["clinical"]["load_id"]  # clinical load reused
        mp = pytest.MonkeyPatch()
        mp.setattr(settings, "data_source", "db")
        # Deployment configuration: writes go through the shared write key.
        mp.setattr(settings, "allow_unprotected_writes", False)
        mp.setattr(settings, "write_api_key", SecretStr("live-test-write-key"))
        client.headers["X-PulseReach-Write-Key"] = "live-test-write-key"
        ai = _new_ai()
        app.dependency_overrides[get_ai_service] = lambda: ai
        try:
            yield eng
        finally:
            app.dependency_overrides.pop(get_ai_service, None)
            client.headers.pop("X-PulseReach-Write-Key", None)
            mp.undo()
            eng.dispose()


def _count(eng, sql: str, **p) -> int:
    with eng.connect() as c:
        return c.execute(text(sql), p).scalar_one()


def _draft(**kw) -> dict:
    resp = client.post("/api/v1/outreach/draft", json={**DRAFT, **kw})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _review(draft: dict, **kw):
    return client.post("/api/v1/outreach/draft/review", json={
        "draft_audit_id": draft["ai"]["audit_id"], "patient_id": PID, "rule_id": RULE,
        "care_gap_id": draft["care_gap_id"], "channel": "phone", "language": "en",
        "reviewed_by": WHO, **kw})


# --- read API ---------------------------------------------------------------------------------


def test_dashboard_insights_and_evaluations_match_memory_mode(db):
    mem = MemoryReadRepository()
    d = client.get("/api/v1/dashboard/summary").json()
    assert d == mem.get_dashboard_summary().model_dump(mode="json")
    assert sum(d["patient_status_counts"].values()) == d["total_patients"]
    insight = client.get("/api/v1/insights/population").json()
    assert insight["facts"]["review_flagged_patients_count"] == d["review_flagged_patients_count"]
    evals = client.get(f"/api/v1/patients/{PID}/evaluations").json()
    assert evals == mem.get_patient_evaluations(PID).model_dump(mode="json")
    assert all(e["input_snapshot_basis"] == "recorded_at_evaluation" for e in evals["evaluations"])
    # Stored at evaluation time, not rebuilt: the DB rows carry the snapshot and engine detail.
    assert _count(db, "SELECT count(*) FROM synthetic.eligibility_evaluation WHERE input_snapshot IS NULL "
                      "OR reason_detail IS NULL AND reason_code IS NOT NULL") == 0
    adhoc = client.post("/api/v1/evaluations", json={"patient_id": PID, "look_ahead_days": 90}).json()
    assert adhoc["is_persisted"] is False and adhoc["evaluations"][0]["evaluation_id"].startswith("EPHEMERAL-")


def test_explanation_in_db_mode_is_audited_durably(db):
    resp = client.post("/api/v1/explanations", json={"patient_id": PID, "rule_id": RULE})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ai"]["generation_mode"] == "deterministic_fallback"
    assert body["ai"]["fallback_reason"] == "llm_disabled"
    audit = client.get("/api/v1/ai/audit?feature=explanation").json()
    assert audit["durable"] is True
    rec = next(r for r in audit["items"] if r["audit_id"] == body["ai"]["audit_id"])
    assert rec["run_id"] == "SYNTH-RUN-0001" and rec["subject"]["patient_id"] == PID
    assert _count(db, "SELECT count(*) FROM synthetic.ai_audit_record WHERE audit_id = :a AND patient_id = :p "
                      "AND rule_id = :r", a=body["ai"]["audit_id"], p=PID, r=RULE) == 1
    status = client.get("/api/v1/ai/status").json()
    assert status["availability"] == "disabled" and status["llm_enabled"] is False


# --- outreach -------------------------------------------------------------------------------


def test_outreach_reject_then_approve_is_refused(db):
    draft = _draft()
    assert draft["allowed"] and draft["generation_status"] == "fallback" and draft["care_gap_id"] == GAP
    out = _review(draft, decision="rejected", reason="tone")
    assert out.status_code == 200 and out.json()["review_status"] == "rejected"
    late = _review(draft, decision="approved", final_message=draft["draft_body"])
    assert late.status_code == 409 and late.json()["detail"]["review_status"] == "rejected"
    assert _count(db, "SELECT count(*) FROM synthetic.care_gap_follow_up_event WHERE care_gap_id = :g", g=GAP) == 0


def test_outreach_approval_records_one_simulated_follow_up_and_no_text(db):
    outreach_rows = _count(db, "SELECT count(*) FROM synthetic.outreach_event")
    draft = _draft()
    resp = _review(draft, decision="approved", final_message=draft["draft_body"])
    assert resp.status_code == 200, resp.text
    out = resp.json()
    assert out["review_status"] == "approved" and out["delivered"] is False and out["sendable"] is False
    fu = out["follow_up"]
    assert (fu["event_type"], fu["outcome_status"]) == ("outreach_attempted", "simulated_not_sent")
    replay = _review(draft, decision="approved", final_message=draft["draft_body"])
    assert replay.status_code == 409 and replay.json()["detail"]["follow_up_id"] == fu["follow_up_id"]

    # Follow-up status refresh: the event is visible to every follow-up read path.
    listed = client.get(f"/api/v1/care-gaps/{GAP}/follow-ups").json()["items"]
    assert [e["follow_up_id"] for e in listed] == [fu["follow_up_id"]]
    activity = client.get(f"/api/v1/patients/{PID}/activity").json()
    assert fu["follow_up_id"] in {e["follow_up_id"] for e in activity["follow_up_events"]}
    assert fu["follow_up_id"] in {e["follow_up_id"] for e in client.get(f"/api/v1/care-gaps/{GAP}").json()["follow_up_events"]}

    row = dict(db.connect().execute(text(
        "SELECT review_decision, reviewed_by, follow_up_id, simulated_outreach_status, draft_audit_id "
        "FROM synthetic.ai_audit_record WHERE audit_id = :a"), {"a": out["review_audit_id"]}).mappings().one())
    assert row == {"review_decision": "approved", "reviewed_by": WHO, "follow_up_id": fu["follow_up_id"],
                   "simulated_outreach_status": "simulated_not_sent", "draft_audit_id": draft["ai"]["audit_id"]}
    # Message content is never persisted, only fingerprints.
    assert _count(db, "SELECT count(*) FROM synthetic.ai_audit_record r WHERE row_to_json(r)::text LIKE :b",
                  b=f"%{draft['draft_body'][:60]}%") == 0
    # Nothing is ever delivered: approval writes no outreach_event (delivery) row.
    assert _count(db, "SELECT count(*) FROM synthetic.outreach_event") == outreach_rows


def test_draft_survives_restart_and_is_reviewable_from_another_worker(db):
    draft = _draft()
    # "Restart": drop the engine pool and the AI service, build new ones (as a new process would).
    get_engine.cache_clear()
    worker_b = _new_ai()
    app.dependency_overrides[get_ai_service] = lambda: worker_b
    try:
        persisted = {r["audit_id"] for r in client.get("/api/v1/ai/audit?feature=outreach_draft").json()["items"]}
        assert draft["ai"]["audit_id"] in persisted
        resp = _review(draft, decision="approved", final_message=draft["draft_body"])
        assert resp.status_code == 200 and resp.json()["review_status"] == "approved"
        worker_c = _new_ai()
        assert worker_c.audit.terminal_review(draft["ai"]["audit_id"]).audit_id == resp.json()["review_audit_id"]
    finally:
        app.dependency_overrides[get_ai_service] = lambda: worker_b


def test_concurrent_approvals_create_one_simulated_follow_up(db):
    draft = _draft()
    before = _count(db, "SELECT count(*) FROM synthetic.care_gap_follow_up_event WHERE care_gap_id = :g", g=GAP)
    with ThreadPoolExecutor(max_workers=6) as pool:
        codes = sorted(pool.map(
            lambda _: _review(draft, decision="approved", final_message=draft["draft_body"]).status_code, range(6)))
    assert codes == [200, 409, 409, 409, 409, 409]
    assert _count(db, "SELECT count(*) FROM synthetic.care_gap_follow_up_event WHERE care_gap_id = :g", g=GAP) == before + 1
    assert _count(db, "SELECT count(*) FROM synthetic.ai_audit_record WHERE draft_audit_id = :d AND "
                      "review_decision = 'approved'", d=draft["ai"]["audit_id"]) == 1


def test_ai_audit_constraints_reject_unsafe_rows(db):
    draft = _draft()
    base = ("INSERT INTO synthetic.ai_audit_record (audit_id, run_id, recorded_at, feature, patient_id, "
            "prompt_version, generation_mode, draft_audit_id, review_decision, reviewed_by, follow_up_id, "
            "simulated_outreach_status) VALUES (md5(random()::text), 'SYNTH-RUN-0001', now(), :f, :p, 'x', :m, "
            ":d, :rd, :rb, :fu, :st)")
    ok = dict(f="outreach_review", p=PID, m="human_blocked", d=draft["ai"]["audit_id"], rd="blocked", rb=WHO,
              fu=None, st=None)
    explanation_id = client.get("/api/v1/ai/audit?feature=explanation&limit=1").json()["items"][0]["audit_id"]
    for bad in (
        {**ok, "m": "human_approved", "rd": "approved"},          # approval without a simulated follow-up
        {**ok, "st": "sent"},                                     # delivery status is never recordable
        {**ok, "d": explanation_id},                              # a review must reference a draft
        {**ok, "rb": "  "},                                       # reviewer attribution required
        {**ok, "f": "explanation", "m": "llm_grounded"},          # draft link only on reviews
    ):
        with pytest.raises(IntegrityError):
            with db.begin() as c:
                c.execute(text(base), bad)
    with db.begin() as c:
        c.execute(text(base), {**ok, "m": "human_rejected", "rd": "rejected"})
    with pytest.raises(IntegrityError):  # a second terminal decision for the same draft
        with db.begin() as c:
            c.execute(text(base), {**ok, "m": "human_rejected", "rd": "rejected"})
    with pytest.raises(DBAPIError, match="append-only"):
        with db.begin() as c:
            c.execute(text("UPDATE synthetic.ai_audit_record SET reviewed_by = 'x' WHERE draft_audit_id = :d"),
                      {"d": draft["ai"]["audit_id"]})


# --- workflow -------------------------------------------------------------------------------


def _apt(**kw) -> dict:
    return {"patient_id": PID, "profile_id": "SYNTH-FSP-000001", "care_gap_id": GAP,
            "appointment_type": "ifhas_screening", "scheduled_datetime": "2026-12-01T09:00:00+00:00",
            "recorded_by": WHO, **kw}


def test_appointment_and_referral_history_and_duplicates(db):
    first = client.post("/api/v1/appointments", json=_apt())
    assert first.status_code == 201, first.text
    apt_id = first.json()["appointment_id"]
    dup = client.post("/api/v1/appointments", json=_apt())
    assert dup.status_code == 409 and dup.json()["detail"]["existing_id"] == apt_id
    assert client.patch(f"/api/v1/appointments/{apt_id}", json={
        "status": "rescheduled", "scheduled_datetime": "2026-12-03T09:00:00+00:00", "recorded_by": WHO}).status_code == 200
    assert client.patch(f"/api/v1/appointments/{apt_id}", json={"status": "attended", "recorded_by": WHO}).status_code == 200
    hist = client.get(f"/api/v1/appointments/{apt_id}/history").json()["items"]
    assert [(h["from_status"], h["to_status"]) for h in hist] == [
        (None, "scheduled"), ("scheduled", "rescheduled"), ("rescheduled", "attended")]
    assert hist[0]["scheduled_datetime"].startswith("2026-12-01")

    ref = {"patient_id": "SYNTH-PAT-000008", "ifhas_screening_id": "SYNTH-SCR-000002", "trigger_rule_id": RULE,
           "trigger_rule_version": "1.0.0", "referral_target": "diagnostics", "trigger_date": "2026-11-16",
           "care_gap_id": "SYNTH-GAP-000017", "recorded_by": WHO}
    created = client.post("/api/v1/referrals", json=ref)
    assert created.status_code == 201, created.text
    assert client.post("/api/v1/referrals", json=ref).status_code == 409
    ref_id = created.json()["referral_id"]
    client.patch(f"/api/v1/referrals/{ref_id}", json={"status": "cancelled", "recorded_by": WHO})
    assert [h["to_status"] for h in client.get(f"/api/v1/referrals/{ref_id}/history").json()["items"]] == [
        "pending", "cancelled"]
    activity = client.get("/api/v1/patients/SYNTH-PAT-000008/activity").json()
    assert {e["referral_id"] for e in activity["workflow_events"]} == {ref_id}


def test_concurrent_duplicate_appointments_create_one_row(db):
    body = _apt(scheduled_datetime="2026-12-09T09:00:00+00:00")
    with ThreadPoolExecutor(max_workers=6) as pool:
        codes = sorted(pool.map(lambda _: client.post("/api/v1/appointments", json=body).status_code, range(6)))
    assert codes == [201, 409, 409, 409, 409, 409]
    assert _count(db, "SELECT count(*) FROM synthetic.appointment WHERE scheduled_datetime = '2026-12-09T09:00:00+00:00'") == 1


def test_duplicate_follow_up_submission_is_rejected(db):
    note = {"event_type": "note_recorded", "recorded_by": WHO, "note": "Live duplicate check."}
    first = client.post(f"/api/v1/care-gaps/{GAP}/follow-ups", json=note)
    assert first.status_code == 201
    dup = client.post(f"/api/v1/care-gaps/{GAP}/follow-ups", json=note)
    assert dup.status_code == 409 and dup.json()["detail"]["existing_id"] == first.json()["follow_up_id"]


def test_completion_requires_valid_evidence_and_happens_once(db):
    assert client.patch(f"/api/v1/referrals/{REFERRAL_ID}", json={
        "status": "initiated", "initiated_date": "2026-09-20", "recorded_by": WHO}).status_code == 200
    body = {"event_type": "completion_documented", "close_gap": True, "documented_evidence": True,
            "evidence_reference": REFERRAL_ID, "recorded_by": WHO}
    early = client.post(f"/api/v1/care-gaps/{REFERRAL_GAP}/follow-ups", json=body)
    assert early.status_code == 422  # referral not completed yet
    bogus = client.post(f"/api/v1/care-gaps/{REFERRAL_GAP}/follow-ups", json={**body, "evidence_reference": "SYNTH-SCR-999999"})
    assert bogus.status_code == 422
    assert client.patch(f"/api/v1/referrals/{REFERRAL_ID}", json={
        "status": "completed", "completed_date": "2026-10-01", "recorded_by": WHO}).status_code == 200

    with ThreadPoolExecutor(max_workers=4) as pool:
        codes = sorted(pool.map(
            lambda _: client.post(f"/api/v1/care-gaps/{REFERRAL_GAP}/follow-ups", json=body).status_code, range(4)))
    assert codes == [201, 422, 422, 422]
    gap = client.get(f"/api/v1/care-gaps/{REFERRAL_GAP}").json()
    assert gap["status"] == "closed_completed" and gap["closed_by_referral_id"] == REFERRAL_ID
    assert [e["event_type"] for e in gap["follow_up_events"]].count("completion_documented") == 1
    # The historical evaluation is unchanged; it is only marked superseded by the completion.
    ev = next(e for e in client.get(f"/api/v1/patients/{gap['patient_id']}/evaluations").json()["evaluations"]
              if e["evaluation_id"] == gap["evaluation_id"])
    assert ev["superseded_by_completion"] is True and ev["evaluation_status"] != "completed"


def test_consent_withdrawal_between_draft_and_approval_blocks(db):
    draft = _draft()
    with db.begin() as c:
        c.execute(text(
            "INSERT INTO synthetic.consent (consent_id, run_id, patient_id, consent_type, state, applies_to, "
            "scope_pathway, recorded_at, recorded_by) VALUES ('SYNTH-CNS-900001', 'SYNTH-RUN-0001', :p, "
            "'contact', 'withdrawn', 'self', 'ifhas', now(), 'live-test')"), {"p": PID})
    before = _count(db, "SELECT count(*) FROM synthetic.care_gap_follow_up_event WHERE care_gap_id = :g", g=GAP)
    out = _review(draft, decision="approved", final_message=draft["draft_body"])
    assert out.status_code == 200 and out.json()["review_status"] == "blocked"
    assert out.json()["blocked_reason"].startswith("contact_consent")
    assert out.json()["follow_up"] is None
    assert _count(db, "SELECT count(*) FROM synthetic.care_gap_follow_up_event WHERE care_gap_id = :g", g=GAP) == before
    # A new draft is refused before any generation.
    assert _draft()["allowed"] is False


def test_ai_audit_retrievable_after_restart(db):
    get_engine.cache_clear()
    fresh = _new_ai()
    items = fresh.audit.recent(limit=500)
    assert {r.feature for r in items} >= {"explanation", "outreach_draft", "outreach_review"}
    assert all(r.run_id == "SYNTH-RUN-0001" for r in items)


# --- migrations -----------------------------------------------------------------------------


def test_migration_chain_upgrade_downgrade_safeguard_and_legacy_rows():
    """Fresh upgrade; refusal to drop history; 0009 -> head upgrade over existing workflow data."""
    from test_official_integrity import scratch_database

    with scratch_database() as url:
        command.upgrade(_alembic_cfg(), "head")
        eng = create_engine(url)
        try:
            _seed(eng)
            with Session(eng) as s:
                repo = PostgresFollowUpRepository(s)
                apt = repo.create_appointment(AppointmentCreateIn(**_apt()))
                repo.create_follow_up(GAP, FollowUpCreateIn(event_type="outreach_attempted", recorded_by=WHO))

            for target in ("0009", "0008"):
                with pytest.raises(RuntimeError, match="Refusing to downgrade"):
                    command.downgrade(_alembic_cfg(), target)
            with eng.connect() as c:
                assert c.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0010"

            # Explicitly allowed: back to the previous supported schema (0009).
            command.downgrade(_alembic_cfg(allow_data_loss=True), "0009")
            with eng.connect() as c:
                assert c.execute(text("SELECT to_regclass('synthetic.ai_audit_record')")).scalar_one() is None
            # Workflow written on 0009 (no 0010 columns involved).
            with Session(eng) as s:
                repo = PostgresFollowUpRepository(s)
                repo.update_appointment(apt.appointment_id, AppointmentPatchIn(status="attended", recorded_by=WHO))
            wse = _count(eng, "SELECT count(*) FROM synthetic.workflow_status_event")
            fups = _count(eng, "SELECT count(*) FROM synthetic.care_gap_follow_up_event")

            command.upgrade(_alembic_cfg(), "head")
            assert _count(eng, "SELECT count(*) FROM synthetic.workflow_status_event") == wse
            assert _count(eng, "SELECT count(*) FROM synthetic.care_gap_follow_up_event") == fups
            names = {r[0] for r in eng.connect().execute(text(
                "SELECT conname FROM pg_constraint WHERE conrelid = 'synthetic.ai_audit_record'::regclass"))}
            assert {"fk_ai_audit_record_draft_audit_id_ai_audit_record",
                    "fk_ai_audit_record_follow_up_id_care_gap_follow_up_event",
                    "fk_ai_audit_record_patient_id_patient", "fk_ai_audit_record_run_id_generation_run",
                    "ck_ai_audit_record_approved_records_simulated_follow_up",
                    "ck_ai_audit_record_review_decision"} <= names
            # Legacy evaluations (written before 0010) are labelled, never presented as recorded.
            with Session(eng) as s:
                ev = PostgresReadRepository(s).get_patient_evaluations(PID).evaluations[0]
                assert ev.input_snapshot_basis == "reconstructed_at_read" and ev.input_snapshot
                hist = PostgresFollowUpRepository(s).get_appointment_history(apt.appointment_id).items
                assert [h.to_status for h in hist] == ["scheduled", "attended"]
            # Reseeding replaces the run (and its AI audit rows) in one transaction.
            _seed(eng)
            assert _count(eng, "SELECT count(*) FROM synthetic.eligibility_evaluation WHERE input_snapshot IS NULL") == 0
        finally:
            eng.dispose()


def test_bootstrap_second_start_does_not_reseed():
    from test_official_integrity import scratch_database

    from app.db.init import bootstrap

    with scratch_database() as url:
        first = bootstrap()
        assert first == {"migrated": True, "official_loaded": True, "seeded": True}
        eng = create_engine(url)
        try:
            with Session(eng) as s:
                PostgresFollowUpRepository(s).create_follow_up(
                    GAP, FollowUpCreateIn(event_type="note_recorded", recorded_by=WHO, note="kept"))
            assert bootstrap() == {"migrated": True, "official_loaded": False, "seeded": False}
            assert _count(eng, "SELECT count(*) FROM synthetic.care_gap_follow_up_event WHERE note = 'kept'") == 1
        finally:
            eng.dispose()
