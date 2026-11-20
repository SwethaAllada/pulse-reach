"""Workflow traceability, consent and simulated-outreach safety (BE-08 … BE-15).

Part 1 runs in memory mode through the API. Part 2 runs the same workflow through
`PostgresFollowUpRepository` on a disposable PostgreSQL (`TEST_DATABASE_URL`) and checks the
0009 database guarantees (consent FK, append-only history, completion CHECK, link CHECKs).
"""

from __future__ import annotations

import argparse
import os
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_engine
from app.main import app
from app.repositories.followup_repo import PostgresFollowUpRepository, reset_memory_writes
from app.repositories.read_repo import (
    PostgresReadRepository,
    get_cached_dataset,
    get_cached_index,
)
from app.schemas.v1 import (
    AppointmentCreateIn,
    AppointmentPatchIn,
    FollowUpCreateIn,
    ReferralCreateIn,
    ReferralPatchIn,
)
from app.services.followup import FollowUpService

client = TestClient(app)
BACKEND = Path(__file__).resolve().parents[1]

# Fixed facts of the deterministic dataset (seed 20261116).
ALLOWED_GAP, ALLOWED_PATIENT, ALLOWED_CONSENT = "SYNTH-GAP-000001", "SYNTH-PAT-000001", "SYNTH-CNS-000001"
NO_CONSENT_GAP = "SYNTH-GAP-000007"  # SYNTH-PAT-000002, contact consent absent
TEMPLATE_GAP, TEMPLATE_CONSENT = "SYNTH-GAP-000051", "SYNTH-CNS-000004"  # Arabic-only patient
WRONG_CONTACT_GAP = "SYNTH-GAP-000070"  # granted consent, contact details wrong
REFERRAL_GAP, REFERRAL_PATIENT, REFERRAL_ID = "SYNTH-GAP-000026", "SYNTH-PAT-000009", "SYNTH-REF-000001"
PROFILE_ID = "SYNTH-FSP-000001"
WHO = "coordinator.test"


@pytest.fixture(autouse=True)
def _reset_memory():
    get_cached_index.cache_clear()
    get_cached_dataset.cache_clear()
    reset_memory_writes()
    yield
    reset_memory_writes()
    get_cached_index.cache_clear()
    get_cached_dataset.cache_clear()


def _apt_body(**kw):
    return {
        "patient_id": ALLOWED_PATIENT,
        "profile_id": PROFILE_ID,
        "care_gap_id": ALLOWED_GAP,
        "appointment_type": "ifhas_screening",
        "scheduled_datetime": "2026-11-25T10:00:00+00:00",
        "recorded_by": WHO,
        **kw,
    }


# ---------------------------------------------------------------------------
# Part 1 - memory mode (API)
# ---------------------------------------------------------------------------


def test_appointment_history_preserves_every_status_and_datetime():
    apt = client.post("/api/v1/appointments", json=_apt_body())
    assert apt.status_code == 201
    apt_id = apt.json()["appointment_id"]

    # Reschedule requires a new datetime; other statuses must not carry one.
    assert client.patch(f"/api/v1/appointments/{apt_id}", json={"status": "rescheduled", "recorded_by": WHO}).status_code == 422
    assert client.patch(
        f"/api/v1/appointments/{apt_id}",
        json={"status": "attended", "scheduled_datetime": "2026-11-26T10:00:00+00:00", "recorded_by": WHO},
    ).status_code == 422
    assert client.patch(
        f"/api/v1/appointments/{apt_id}",
        json={"status": "rescheduled", "scheduled_datetime": "2026-11-27T09:00:00+00:00", "recorded_by": WHO, "note": "patient asked"},
    ).status_code == 200
    assert client.patch(f"/api/v1/appointments/{apt_id}", json={"status": "attended", "recorded_by": "nurse.test"}).status_code == 200
    assert client.patch(f"/api/v1/appointments/{apt_id}", json={"status": "no_show", "recorded_by": WHO}).status_code == 422

    hist = client.get(f"/api/v1/appointments/{apt_id}/history").json()["items"]
    assert [(h["from_status"], h["to_status"]) for h in hist] == [
        (None, "scheduled"),
        ("scheduled", "rescheduled"),
        ("rescheduled", "attended"),
    ]
    assert hist[0]["scheduled_datetime"].startswith("2026-11-25T10:00")
    assert hist[1]["scheduled_datetime"].startswith("2026-11-27T09:00")
    assert [h["recorded_by"] for h in hist] == [WHO, WHO, "nurse.test"]
    assert all(h["care_gap_id"] == ALLOWED_GAP for h in hist)

    # The linked gap shows the appointment timeline but is NOT closed by attendance.
    gap = client.get(f"/api/v1/care-gaps/{ALLOWED_GAP}").json()
    assert gap["status"] == "open"
    types = sorted(e["event_type"] for e in gap["follow_up_events"])
    assert types == ["appointment_scheduled", "appointment_updated", "appointment_updated"]
    assert all(e["appointment_id"] == apt_id for e in gap["follow_up_events"])
    assert len(gap["workflow_events"]) == 3
    assert client.get("/api/v1/appointments/SYNTH-APT-999999/history").status_code == 404


def test_referral_history_and_gap_linkage():
    upd = client.patch(f"/api/v1/referrals/{REFERRAL_ID}", json={"status": "initiated", "initiated_date": "2026-09-20", "recorded_by": WHO})
    assert upd.status_code == 200
    client.patch(f"/api/v1/referrals/{REFERRAL_ID}", json={"status": "completed", "completed_date": "2026-10-01", "recorded_by": WHO})
    hist = client.get(f"/api/v1/referrals/{REFERRAL_ID}/history").json()["items"]
    assert [(h["from_status"], h["to_status"]) for h in hist] == [("pending", "initiated"), ("initiated", "completed")]
    assert hist[1]["initiated_date"] == "2026-09-20" and hist[1]["completed_date"] == "2026-10-01"

    # The referral is the gap's subject: both changes are on the gap timeline; the gap is still
    # open until completion is documented with evidence.
    gap = client.get(f"/api/v1/care-gaps/{REFERRAL_GAP}").json()
    assert gap["status"] == "open"
    assert [e["event_type"] for e in gap["follow_up_events"]] == ["referral_updated"] * 2

    close = client.post(
        f"/api/v1/care-gaps/{REFERRAL_GAP}/follow-ups",
        json={"event_type": "completion_documented", "close_gap": True, "documented_evidence": True,
              "evidence_reference": REFERRAL_ID, "recorded_by": "clinician.test"},
    )
    assert close.status_code == 201
    gap = client.get(f"/api/v1/care-gaps/{REFERRAL_GAP}").json()
    assert gap["status"] == "closed_completed" and gap["closed_by_referral_id"] == REFERRAL_ID

    listed = client.get(f"/api/v1/care-gaps/{REFERRAL_GAP}/follow-ups").json()
    assert listed["total"] == 3 and listed["items"][0]["event_type"] == "completion_documented"


def test_new_referral_linked_to_gap_is_traceable():
    # SYNTH-PAT-000008: open gap SYNTH-GAP-000017, partial screening SYNTH-SCR-000002 (MAJOR-40-64).
    pid, gap_id = "SYNTH-PAT-000008", "SYNTH-GAP-000017"
    scr = next(s for s in client.get(f"/api/v1/patients/{pid}/history").json()["ifhas_screenings"]
               if s["screening_id"] == "SYNTH-SCR-000002")
    body = {"patient_id": pid, "ifhas_screening_id": scr["screening_id"], "trigger_rule_id": scr["rule_id"],
            "trigger_rule_version": scr["rule_version"], "referral_target": "diagnostics",
            "trigger_date": "2026-11-16", "care_gap_id": gap_id, "recorded_by": WHO}
    created = client.post("/api/v1/referrals", json=body)
    assert created.status_code == 201
    ref_id = created.json()["referral_id"]
    client.patch(f"/api/v1/referrals/{ref_id}", json={"status": "cancelled", "recorded_by": WHO})
    gap = client.get(f"/api/v1/care-gaps/{gap_id}").json()
    assert gap["status"] == "open"
    assert ref_id in {r["referral_id"] for r in gap["linked_referrals"]}
    assert [e["event_type"] for e in sorted(gap["follow_up_events"], key=lambda e: e["follow_up_id"])] == [
        "referral_created", "referral_updated"]
    hist = client.get(f"/api/v1/referrals/{ref_id}/history").json()["items"]
    assert [(h["from_status"], h["to_status"], h["care_gap_id"]) for h in hist] == [
        (None, "pending", gap_id), ("pending", "cancelled", gap_id)]
    # A care gap of another patient cannot be linked.
    assert client.post("/api/v1/referrals", json={**body, "care_gap_id": REFERRAL_GAP}).status_code == 404


def test_writes_require_an_actor():
    body = _apt_body()
    del body["recorded_by"]
    assert client.post("/api/v1/appointments", json=body).status_code == 422
    assert client.patch(f"/api/v1/referrals/{REFERRAL_ID}", json={"status": "declined"}).status_code == 422
    assert client.patch(f"/api/v1/referrals/{REFERRAL_ID}", json={"status": "declined", "recorded_by": "  "}).status_code == 422
    assert client.get(f"/api/v1/referrals/{REFERRAL_ID}/history").json()["items"] == []


def test_completion_event_requires_close_gap_and_evidence():
    resp = client.post(f"/api/v1/care-gaps/{ALLOWED_GAP}/follow-ups",
                       json={"event_type": "completion_documented", "recorded_by": WHO})
    assert resp.status_code == 422


@pytest.mark.parametrize(
    ("gap_id", "event_type", "outcome", "consent", "reason"),
    [
        (ALLOWED_GAP, "outreach_attempted", "simulated_not_sent", ALLOWED_CONSENT, None),
        (TEMPLATE_GAP, "outreach_attempted", "simulated_not_sent", TEMPLATE_CONSENT, None),
        (NO_CONSENT_GAP, "outreach_suppressed", "suppressed", None, "contact_consent_absent"),
        (WRONG_CONTACT_GAP, "outreach_suppressed", "suppressed", None, "contact_details_wrong"),
    ],
)
def test_outreach_is_simulated_and_consent_gated(gap_id, event_type, outcome, consent, reason):
    resp = client.post(f"/api/v1/care-gaps/{gap_id}/follow-ups", json={"event_type": "outreach_attempted", "recorded_by": WHO})
    assert resp.status_code == 201
    body = resp.json()
    assert (body["event_type"], body["outcome_status"], body["contact_consent_id"], body["suppression_reason"]) == (
        event_type, outcome, consent, reason)
    assert body["outcome_status"] not in ("sent", "delivered")


def test_patient_activity_lists_all_writes():
    apt_id = client.post("/api/v1/appointments", json=_apt_body()).json()["appointment_id"]
    client.post(f"/api/v1/care-gaps/{ALLOWED_GAP}/follow-ups", json={"event_type": "note_recorded", "recorded_by": WHO, "note": "n"})
    act = client.get(f"/api/v1/patients/{ALLOWED_PATIENT}/activity").json()
    assert {e["event_type"] for e in act["follow_up_events"]} == {"appointment_scheduled", "note_recorded"}
    assert [e["appointment_id"] for e in act["workflow_events"]] == [apt_id]
    assert all(e["recorded_by"] == WHO and e["recorded_at"] for e in act["follow_up_events"])
    assert client.get("/api/v1/patients/SYNTH-PAT-999999/activity").status_code == 404
    assert client.get("/api/v1/care-gaps/SYNTH-GAP-999999/follow-ups").status_code == 404


def test_service_never_assumes_missing_outreach_inputs():
    svc = FollowUpService()
    assert svc.evaluate_outreach_consent(
        patient={"patient_id": ALLOWED_PATIENT}, consents=[], rule_meta=None,
        care_gap={"care_gap_id": ALLOWED_GAP, "rule_id": "X", "status": "open"}, evaluations=[],
    ) == (False, None, "rule_not_found")
    # Without a granting consent nothing is authorised, whatever the gate says.
    assert svc.outreach_attempt_outcome(allowed=True, consent_id=None, blocked_reason=None)[0] == "outreach_suppressed"
    assert svc.outreach_attempt_outcome(allowed=False, consent_id="C", blocked_reason="contact_consent_withdrawn")[1] == "suppressed"


# ---------------------------------------------------------------------------
# Part 2 - live, disposable PostgreSQL (TEST_DATABASE_URL)
# ---------------------------------------------------------------------------

live = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set")


@pytest.fixture(scope="module")
def seeded_pg():
    from alembic import command
    from alembic.config import Config

    from app.services import official_loader
    from app.services.synthetic_generator import seed as seed_cmd

    url = os.environ["TEST_DATABASE_URL"]
    mp = pytest.MonkeyPatch()
    mp.setattr(settings, "database_url", SecretStr(url))
    get_engine.cache_clear()
    command.upgrade(Config(str(BACKEND / "alembic.ini")), "head")
    eng = create_engine(url)
    with eng.connect() as conn:
        if conn.execute(text("SELECT count(*) FROM official.facility")).scalar_one() == 0:
            official_loader.run(engine=eng)
    seed_cmd.seed_database(engine=eng)
    try:
        yield eng
    finally:
        eng.dispose()
        get_engine.cache_clear()
        mp.undo()


@live
def test_live_workflow_history_and_constraints(seeded_pg):
    eng = seeded_pg
    with Session(eng) as s:
        repo = PostgresFollowUpRepository(s)
        apt = repo.create_appointment(AppointmentCreateIn(**{**_apt_body(), "scheduled_datetime": datetime(2026, 11, 25, 10, tzinfo=timezone.utc)}))
        repo.update_appointment(apt.appointment_id, AppointmentPatchIn(
            status="rescheduled", scheduled_datetime=datetime(2026, 11, 27, 9, tzinfo=timezone.utc), recorded_by=WHO))
        repo.update_appointment(apt.appointment_id, AppointmentPatchIn(status="attended", recorded_by=WHO))
        with pytest.raises(HTTPException) as bad:
            repo.update_appointment(apt.appointment_id, AppointmentPatchIn(status="no_show", recorded_by=WHO))
        assert bad.value.status_code == 422
        hist = repo.get_appointment_history(apt.appointment_id).items
        assert [(h.from_status, h.to_status) for h in hist] == [
            (None, "scheduled"), ("scheduled", "rescheduled"), ("rescheduled", "attended")]
        assert hist[0].scheduled_datetime == datetime(2026, 11, 25, 10, tzinfo=timezone.utc)

        repo.update_referral(REFERRAL_ID, ReferralPatchIn(status="initiated", initiated_date=date(2026, 9, 20), recorded_by=WHO))
        repo.update_referral(REFERRAL_ID, ReferralPatchIn(status="completed", completed_date=date(2026, 10, 1), recorded_by=WHO))
        assert [h.to_status for h in repo.get_referral_history(REFERRAL_ID).items] == ["initiated", "completed"]
        repo.create_follow_up(REFERRAL_GAP, FollowUpCreateIn(
            event_type="completion_documented", close_gap=True, documented_evidence=True,
            evidence_reference=REFERRAL_ID, recorded_by=WHO))

        allowed = repo.create_follow_up(ALLOWED_GAP, FollowUpCreateIn(event_type="outreach_attempted", recorded_by=WHO))
        assert (allowed.outcome_status, allowed.contact_consent_id) == ("simulated_not_sent", ALLOWED_CONSENT)
        blocked = repo.create_follow_up(NO_CONSENT_GAP, FollowUpCreateIn(event_type="outreach_attempted", recorded_by=WHO))
        assert (blocked.event_type, blocked.contact_consent_id) == ("outreach_suppressed", None)

        detail = PostgresReadRepository(s).get_care_gap_detail(ALLOWED_GAP)
        assert detail.status == "open"
        assert {e.event_type for e in detail.follow_up_events} == {
            "appointment_scheduled", "appointment_updated", "outreach_attempted"}
        assert len(detail.workflow_events) == 3
        ref_detail = PostgresReadRepository(s).get_care_gap_detail(REFERRAL_GAP)
        assert ref_detail.closed_by_referral_id == REFERRAL_ID
        assert [e.event_type for e in ref_detail.follow_up_events].count("referral_updated") == 2
        assert len(repo.get_patient_activity(ALLOWED_PATIENT).workflow_events) == 3

    def _raw(sql: str, **p):
        with eng.begin() as conn:
            conn.execute(text(sql), p)

    base = ("INSERT INTO synthetic.care_gap_follow_up_event (follow_up_id, run_id, patient_id, care_gap_id, "
            "event_type, outcome_status, documented_evidence, evidence_reference, contact_consent_id, "
            "suppression_reason, recorded_by, recorded_at, appointment_id) VALUES (:id, 'SYNTH-RUN-0001', "
            ":pid, :gap, :et, :os, :de, :er, :cc, :sr, 'raw', now(), :apt)")
    ok = dict(id="SYNTH-FUP-900001", pid="SYNTH-PAT-000002", gap=NO_CONSENT_GAP, et="note_recorded",
              os="noted", de=False, er=None, cc=None, sr=None, apt=None)
    for bad in (
        # outreach "authorised" by a consent of another patient / a non-granting consent
        {**ok, "et": "outreach_attempted", "os": "simulated_not_sent", "cc": ALLOWED_CONSENT},
        # outreach recorded as actually sent
        {**ok, "os": "sent"},
        # completion without documented evidence
        {**ok, "et": "completion_documented", "os": "completed"},
        # appointment event without its appointment
        {**ok, "et": "appointment_updated", "os": "status_recorded"},
    ):
        with pytest.raises(IntegrityError):
            _raw(base, **bad)
    _raw(base, **ok)

    with pytest.raises(DBAPIError, match="append-only"):
        _raw("UPDATE synthetic.workflow_status_event SET to_status = 'cancelled_by_patient' WHERE appointment_id = :a", a=apt.appointment_id)
    with pytest.raises(DBAPIError, match="append-only"):
        _raw("DELETE FROM synthetic.workflow_status_event WHERE appointment_id = :a", a=apt.appointment_id)


@live
def test_live_constraint_violation_maps_to_409_and_rolls_back(seeded_pg, monkeypatch):
    with Session(seeded_pg) as s:
        repo = PostgresFollowUpRepository(s)
        before = s.scalar(text("SELECT count(*) FROM synthetic.workflow_status_event"))
        apts_before = s.scalar(text("SELECT count(*) FROM synthetic.appointment"))
        # Simulate an id collision (e.g. a concurrent writer): the PK violation must surface as
        # 409 with a generic message, and the appointment + its history must roll back together.
        monkeypatch.setattr(repo, "_next_id", lambda *_a: "SYNTH-APT-000001" if _a[2] == "SYNTH-APT" else "SYNTH-WSE-900001")
        with pytest.raises(HTTPException) as exc:
            repo.create_appointment(AppointmentCreateIn(**_apt_body()))
        assert exc.value.status_code == 409 and "PostgreSQL" not in exc.value.detail
        assert s.scalar(text("SELECT count(*) FROM synthetic.workflow_status_event")) == before
        assert s.scalar(text("SELECT count(*) FROM synthetic.appointment")) == apts_before


@live
def test_live_0009_round_trip_on_populated_database():
    """0009 downgrades and re-upgrades with follow-up history present (scratch database)."""
    from alembic import command
    from alembic.config import Config

    from app.services import official_loader
    from app.services.synthetic_generator import seed as seed_cmd
    from test_official_integrity import scratch_database

    with scratch_database() as url:
        cfg = Config(str(BACKEND / "alembic.ini"))
        command.upgrade(cfg, "head")
        eng = create_engine(url)
        try:
            assert official_loader.run(engine=eng)["quarantined"] == []
            seed_cmd.seed_database(engine=eng)
            with Session(eng) as s:
                repo = PostgresFollowUpRepository(s)
                apt = repo.create_appointment(AppointmentCreateIn(**{**_apt_body(), "scheduled_datetime": datetime(2026, 11, 25, 10, tzinfo=timezone.utc)}))
                repo.create_follow_up(ALLOWED_GAP, FollowUpCreateIn(event_type="outreach_attempted", recorded_by=WHO))

            def count(sql: str) -> int:
                with eng.connect() as c:
                    return c.execute(text(sql)).scalar_one()

            fups = count("SELECT count(*) FROM synthetic.care_gap_follow_up_event")
            assert fups == 2 and count("SELECT count(*) FROM synthetic.workflow_status_event") == 1

            # Downgrading would drop workflow history: refused unless explicitly allowed.
            with pytest.raises(RuntimeError, match="Refusing to downgrade"):
                command.downgrade(cfg, "0008")
            assert count("SELECT count(*) FROM synthetic.workflow_status_event") == 1
            cfg.cmd_opts = argparse.Namespace(x=["allow_data_loss=true"])
            command.downgrade(cfg, "0008")
            cfg.cmd_opts = None
            assert count("SELECT count(*) FROM synthetic.care_gap_follow_up_event") == fups
            assert count("SELECT count(*) FROM information_schema.tables WHERE table_name = 'workflow_status_event'") == 0

            command.upgrade(cfg, "head")
            assert count("SELECT count(*) FROM synthetic.care_gap_follow_up_event") == fups
            assert count("SELECT count(*) FROM synthetic.care_gap_follow_up_event WHERE appointment_id IS NOT NULL") == 0
            names = {r[0] for r in eng.connect().execute(text(
                "SELECT conname FROM pg_constraint WHERE conrelid = 'synthetic.care_gap_follow_up_event'::regclass"))}
            assert {"fk_care_gap_follow_up_event_contact_consent_id_consent",
                    "ck_care_gap_follow_up_event_outcome_status",
                    "ck_care_gap_follow_up_event_event_type"} <= names
            assert not any("ck_care_gap_follow_up_event_ck_" in n for n in names)
            # Writes work again after the round trip; the appointment still exists.
            with Session(eng) as s:
                repo = PostgresFollowUpRepository(s)
                repo.update_appointment(apt.appointment_id, AppointmentPatchIn(status="attended", recorded_by=WHO))
                assert [h.to_status for h in repo.get_appointment_history(apt.appointment_id).items] == ["attended"]
        finally:
            eng.dispose()
