"""Reseed/reset ordering after follow-up activity (BE-06, audit F-08).

Part 1 (no database): `DELETE_ORDER` covers every `synthetic.*` table and deletes each child
before every parent it references (other than the FK columns nulled before the deletes).

Part 2 (`TEST_DATABASE_URL`, disposable PostgreSQL with all constraints and triggers): seed,
record follow-up activity through `PostgresFollowUpRepository` (follow-up events, an appointment
created and updated, a referral created, a referral updated to completed and a care gap closed
with it), then reseed with the documented command and check counts, orphans, official and
clinical data, idempotency, rollback of a failed reseed and `--no-replace`.
"""

from __future__ import annotations

import os
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from pydantic import SecretStr
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

import app.models.synthetic  # noqa: F401
from app.core.config import settings
from app.db.session import get_engine
from app.models.base import Base
from app.repositories.followup_repo import PostgresFollowUpRepository
from app.schemas.v1 import (
    AppointmentCreateIn,
    AppointmentPatchIn,
    FollowUpCreateIn,
    ReferralCreateIn,
    ReferralPatchIn,
)
from app.services import clinical_loader
from app.services.synthetic_generator import load as load_mod
from app.services.synthetic_generator import seed as seed_cmd

BACKEND = Path(__file__).resolve().parents[1]

# Fixed facts of the deterministic dataset (seed 20261116); see test_care_gap_completion_evidence.
NOTE_GAP = "SYNTH-GAP-000017"  # open no_documented_screening gap, SYNTH-PAT-000008
NOTE_PATIENT = "SYNTH-PAT-000008"
PARTIAL_SCREENING = "SYNTH-SCR-000002"  # SYNTH-PAT-000008, IFHAS-PKG-MAJOR-40-64
MAJOR_RULE = "IFHAS-PKG-MAJOR-40-64"
REFERRAL_GAP = "SYNTH-GAP-000026"  # referral_not_initiated, subject SYNTH-REF-000001 (pending)
REFERRAL_PATIENT = "SYNTH-PAT-000009"
REFERRAL_ID = "SYNTH-REF-000001"
PROFILE_ID = "SYNTH-FSP-000001"

SYNTH_TABLES = sorted(t.name for t in Base.metadata.tables.values() if t.schema == "synthetic")


def _synthetic_fks():
    for t in Base.metadata.tables.values():
        if t.schema != "synthetic":
            continue
        for fk in t.foreign_key_constraints:
            if fk.referred_table.schema == "synthetic":
                yield t.name, fk.referred_table.name, fk


# ---------------------------------------------------------------------------
# Part 1 - no database
# ---------------------------------------------------------------------------


def test_delete_order_covers_every_synthetic_table():
    assert sorted(load_mod.DELETE_ORDER) == SYNTH_TABLES
    assert len(set(load_mod.DELETE_ORDER)) == len(load_mod.DELETE_ORDER)


def test_delete_order_deletes_children_before_parents():
    position = {name: i for i, name in enumerate(load_mod.DELETE_ORDER)}
    nulled = set(load_mod.NULLED_BEFORE_DELETE)
    violations = [
        f"{child} -> {parent} ({fk.name})"
        for child, parent, fk in _synthetic_fks()
        if child != parent
        and not any((child, c.name) in nulled for c in fk.columns)
        and position[child] > position[parent]
    ]
    assert violations == []


def test_follow_up_events_are_deleted_before_care_gaps():
    order = load_mod.DELETE_ORDER
    assert order.index("care_gap_follow_up_event") < order.index("care_gap")


# ---------------------------------------------------------------------------
# Part 2 - live, disposable PostgreSQL (TEST_DATABASE_URL)
# ---------------------------------------------------------------------------

live = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set")


@pytest.fixture
def live_db(monkeypatch):
    from alembic import command
    from alembic.config import Config

    url = os.environ["TEST_DATABASE_URL"]
    monkeypatch.setattr(settings, "database_url", SecretStr(url))
    get_engine.cache_clear()
    command.upgrade(Config(str(BACKEND / "alembic.ini")), "head")
    eng = create_engine(url, connect_args={"connect_timeout": settings.db_connect_timeout})
    try:
        _ensure_official_loaded(eng)
        yield eng
    finally:
        eng.dispose()
        get_engine.cache_clear()


def _scalar(eng, sql: str, **params):
    with eng.connect() as conn:
        return conn.execute(text(sql), params).scalar_one()


def _ensure_official_loaded(eng) -> None:
    from app.services import official_loader

    if _scalar(eng, "SELECT count(*) FROM official.facility") == 0:
        report = official_loader.run(engine=eng)
        assert report["quarantined"] == [], report["quarantined"]


def _counts(eng) -> dict[str, int]:
    with eng.connect() as conn:
        return {
            t: conn.execute(text(f"SELECT count(*) FROM synthetic.{t}")).scalar_one()
            for t in SYNTH_TABLES
        }


def _expected_counts() -> dict[str, int]:
    ds = seed_cmd.generate_synthetic_dataset(bundle=clinical_loader.parse_clinical_bundle())
    expected = {t: len(getattr(ds, attr)) for t, attr in seed_cmd._RECONCILED_TABLES.items()}
    return {**expected, "generation_run": 1, "evaluation_run": 1, "care_gap_follow_up_event": 0, "workflow_status_event": 0}


def _official_and_clinical_fingerprint(eng) -> dict[str, tuple[int, str | None]]:
    """Row count and an md5 over the full ordered row contents of every official/clinical table."""
    with eng.connect() as conn:
        tables = conn.execute(
            text(
                "SELECT table_schema || '.' || table_name FROM information_schema.tables "
                "WHERE table_schema IN ('official', 'clinical') AND table_type = 'BASE TABLE' "
                "ORDER BY 1"
            )
        ).scalars().all()
        return {
            t: tuple(
                conn.execute(
                    text(f"SELECT count(*), md5(string_agg(x::text, '|' ORDER BY x::text)) FROM {t} x")
                ).one()
            )
            for t in tables
        }


def _orphans(eng) -> dict[str, int]:
    """Child rows whose (non-null) FK columns match no parent row, for every synthetic FK."""
    found: dict[str, int] = {}
    with eng.connect() as conn:
        for child, parent, fk in _synthetic_fks():
            cols = [(c.name, e.column.name) for c, e in zip(fk.columns, fk.elements)]
            not_null = " AND ".join(f"c.{cc} IS NOT NULL" for cc, _ in cols)
            join = " AND ".join(f"p.{pc} = c.{cc}" for cc, pc in cols)
            n = conn.execute(
                text(
                    f"SELECT count(*) FROM synthetic.{child} c WHERE {not_null} AND NOT EXISTS "
                    f"(SELECT 1 FROM synthetic.{parent} p WHERE {join})"
                )
            ).scalar_one()
            if n:
                found[f"{child}.{fk.name}"] = n
        for t in SYNTH_TABLES:
            n = conn.execute(
                text(
                    f"SELECT count(*) FROM synthetic.{t} c WHERE NOT EXISTS "
                    "(SELECT 1 FROM synthetic.generation_run g WHERE g.run_id = c.run_id)"
                )
            ).scalar_one()
            if n:
                found[f"{t}.run_id"] = n
    return found


def _record_follow_up_activity(eng) -> dict[str, str]:
    """Follow-up activity of every kind the API can write, through the real PG repository."""
    major_version = _scalar(eng, "SELECT rule_version FROM clinical.rule WHERE rule_id = :r", r=MAJOR_RULE)
    with Session(eng) as session:
        repo = PostgresFollowUpRepository(session)
        note = repo.create_follow_up(
            NOTE_GAP, FollowUpCreateIn(event_type="note_recorded", recorded_by="be06-test", note="n")
        )
        outreach = repo.create_follow_up(
            NOTE_GAP, FollowUpCreateIn(event_type="outreach_attempted", recorded_by="be06-test")
        )
        apt = repo.create_appointment(
            AppointmentCreateIn(
                patient_id=REFERRAL_PATIENT,
                profile_id=PROFILE_ID,
                care_gap_id=REFERRAL_GAP,
                appointment_type="referral_visit",
                scheduled_datetime=datetime(2026, 11, 20, 9, tzinfo=timezone.utc),
                recorded_by="be06-test",
            )
        )
        repo.update_appointment(apt.appointment_id, AppointmentPatchIn(
                status="rescheduled",
                scheduled_datetime=datetime(2026, 11, 21, 9, tzinfo=timezone.utc),
                recorded_by="be06-test",
            ))
        new_ref = repo.create_referral(
            ReferralCreateIn(
                patient_id=NOTE_PATIENT,
                ifhas_screening_id=PARTIAL_SCREENING,
                trigger_rule_id=MAJOR_RULE,
                trigger_rule_version=major_version,
                referral_target="be06-test",
                trigger_date=date(2026, 11, 10),
                recorded_by="be06-test",
            )
        )
        repo.update_referral(
            REFERRAL_ID, ReferralPatchIn(status="initiated", initiated_date=date(2026, 9, 20), recorded_by="be06-test")
        )
        repo.update_referral(
            REFERRAL_ID, ReferralPatchIn(status="completed", completed_date=date(2026, 10, 1), recorded_by="be06-test")
        )
        completion = repo.create_follow_up(
            REFERRAL_GAP,
            FollowUpCreateIn(
                event_type="completion_documented",
                close_gap=True,
                documented_evidence=True,
                evidence_reference=REFERRAL_ID,
                recorded_by="be06-test",
            ),
        )
        assert completion.outcome_status == "completed"
    return {
        "note": note.follow_up_id,
        "outreach": outreach.follow_up_id,
        "completion": completion.follow_up_id,
        "appointment": apt.appointment_id,
        "referral": new_ref.referral_id,
    }


def _gap_state(eng, gap_id: str):
    with eng.connect() as conn:
        return tuple(
            conn.execute(
                text(
                    "SELECT status, closed_date, closed_by_referral_id FROM synthetic.care_gap "
                    "WHERE care_gap_id = :g"
                ),
                {"g": gap_id},
            ).one()
        )


def _content_fingerprint(eng) -> dict[str, str | None]:
    """md5 over each synthetic table's business columns (excluding wall-clock timestamps)."""
    skip = {"started_at", "finished_at", "evaluated_at", "recorded_at", "reviewed_at", "sent_at"}
    out: dict[str, str | None] = {}
    with eng.connect() as conn:
        for t in SYNTH_TABLES:
            tbl = Base.metadata.tables[f"synthetic.{t}"]
            cols = [c.name for c in tbl.columns if c.name not in skip]
            row = "concat_ws('~', " + ", ".join(f"x.{c}::text" for c in cols) + ")"
            out[t] = conn.execute(
                text(f"SELECT md5(string_agg({row}, '|' ORDER BY {row})) FROM synthetic.{t} x")
            ).scalar_one()
    return out


@live
def test_live_reseed_after_follow_up_activity_replaces_run(live_db, capsys):
    assert seed_cmd.main([]) == 0
    expected = _expected_counts()
    assert _counts(live_db) == expected
    original_gap = _gap_state(live_db, REFERRAL_GAP)
    assert original_gap[0] == "open"
    protected_before = _official_and_clinical_fingerprint(live_db)

    created = _record_follow_up_activity(live_db)
    with_activity = _counts(live_db)
    # note + outreach + completion, 2 appointment events and 2 referral events on REFERRAL_GAP
    assert with_activity["care_gap_follow_up_event"] == 7
    # appointment create + reschedule, new referral, 2 status changes of REFERRAL_ID
    assert with_activity["workflow_status_event"] == 5
    assert with_activity["appointment"] == expected["appointment"] + 1
    assert with_activity["referral"] == expected["referral"] + 1
    assert with_activity["outreach_event"] == expected["outreach_event"] > 0
    assert _gap_state(live_db, REFERRAL_GAP) == ("closed_completed", date(2026, 11, 16), REFERRAL_ID)
    capsys.readouterr()

    # Documented command, default replacement behaviour.
    assert seed_cmd.main(["--seed", "20261116", "--total-patients", "550"]) == 0, capsys.readouterr().err
    assert _counts(live_db) == expected
    assert _orphans(live_db) == {}
    assert _gap_state(live_db, REFERRAL_GAP) == original_gap
    assert _scalar(live_db, "SELECT status FROM synthetic.referral WHERE referral_id = :r", r=REFERRAL_ID) == "pending"
    for table, col, value in (
        ("care_gap_follow_up_event", "follow_up_id", created["completion"]),
        ("appointment", "appointment_id", created["appointment"]),
        ("referral", "referral_id", created["referral"]),
    ):
        assert _scalar(live_db, f"SELECT count(*) FROM synthetic.{table} WHERE {col} = :v", v=value) == 0
    assert _official_and_clinical_fingerprint(live_db) == protected_before
    first_content = _content_fingerprint(live_db)

    # A second reseed is idempotent.
    report = seed_cmd.seed_database(engine=live_db)
    assert report["clinical"]["rules_added"] == 0
    assert _counts(live_db) == expected
    assert _content_fingerprint(live_db) == first_content
    assert _orphans(live_db) == {}
    assert _official_and_clinical_fingerprint(live_db) == protected_before


_REAL_DELETE_ORDER = load_mod.DELETE_ORDER


def _fail_mid_reset(monkeypatch):
    # PostgreSQL raises after follow-up events, care gaps, ... and patients were already deleted.
    i = _REAL_DELETE_ORDER.index("patient") + 1
    monkeypatch.setattr(
        load_mod, "DELETE_ORDER", (*_REAL_DELETE_ORDER[:i], "be06_missing_table", *_REAL_DELETE_ORDER[i:])
    )
    return "UndefinedTable"


def _fail_after_reload(monkeypatch):
    # Reset and reload complete, then reconciliation fails before commit.
    def boom(*_a, **_k):
        raise seed_cmd.SeedError("simulated reconciliation failure")

    monkeypatch.setattr(seed_cmd, "_reconcile", boom)
    return "simulated reconciliation failure"


@live
@pytest.mark.parametrize("inject", [_fail_mid_reset, _fail_after_reload], ids=["mid_reset", "after_reload"])
def test_live_failed_reseed_rolls_back_without_partial_deletion(live_db, monkeypatch, capsys, inject):
    seed_cmd.seed_database(engine=live_db)
    _record_follow_up_activity(live_db)
    before = _counts(live_db)
    content_before = _content_fingerprint(live_db)
    gap_before = _gap_state(live_db, REFERRAL_GAP)
    protected_before = _official_and_clinical_fingerprint(live_db)
    capsys.readouterr()

    expected_error = inject(monkeypatch)
    assert seed_cmd.main([]) == 2
    assert expected_error in capsys.readouterr().err

    assert _counts(live_db) == before
    assert before["care_gap_follow_up_event"] == 7
    assert before["workflow_status_event"] == 5
    assert _content_fingerprint(live_db) == content_before
    assert _gap_state(live_db, REFERRAL_GAP) == gap_before == ("closed_completed", date(2026, 11, 16), REFERRAL_ID)
    assert _orphans(live_db) == {}
    assert _official_and_clinical_fingerprint(live_db) == protected_before

    monkeypatch.undo()
    monkeypatch.setattr(settings, "database_url", SecretStr(os.environ["TEST_DATABASE_URL"]))
    get_engine.cache_clear()
    assert seed_cmd.main([]) == 0
    assert _counts(live_db) == _expected_counts()


@live
def test_live_no_replace_with_follow_up_activity_is_unchanged(live_db, capsys):
    seed_cmd.seed_database(engine=live_db)
    _record_follow_up_activity(live_db)
    before = _counts(live_db)
    content_before = _content_fingerprint(live_db)
    capsys.readouterr()
    assert seed_cmd.main(["--no-replace"]) == 2
    assert "database error (IntegrityError)" in capsys.readouterr().err
    assert _counts(live_db) == before
    assert _content_fingerprint(live_db) == content_before
