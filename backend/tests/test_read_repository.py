"""Tests for T-03: ReadRepository abstraction, DATA_SOURCE=memory|db mode, and fail-fast DB behavior."""

from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import JSON, CheckConstraint, ForeignKeyConstraint, MetaData, create_engine, event, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Session

from app.core.config import settings
from app.main import app
from app.models.clinical import (
    OpenQuestion,
    Rule,
    RuleItem,
    RuleItemOpenQuestion,
    RuleLoad,
    RuleOpenQuestion,
    Standard,
)
from app.models.synthetic import (
    Appointment,
    Assessment,
    CareGap,
    ComponentResult,
    Consent,
    EligibilityEvaluation,
    EvaluationReason,
    EvaluationRun,
    GenerationRun,
    Guardian,
    HistoryAvailability,
    IfhasScreening,
    OutreachEvent,
    Patient,
    Referral,
    WellChildVisit,
)
from app.repositories import MemoryReadRepository, PostgresReadRepository
from app.services.clinical_loader.parse import parse_clinical_bundle
from app.services.synthetic_generator import generate_synthetic_dataset


def _sqlite_multi_schema_engine():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _attach_schemas(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        cur.execute("ATTACH DATABASE ':memory:' AS official")
        cur.execute("ATTACH DATABASE ':memory:' AS clinical")
        cur.execute("ATTACH DATABASE ':memory:' AS synthetic")
        cur.close()

    return engine


def test_db_mode_fails_clearly_when_database_not_configured(monkeypatch):
    monkeypatch.setattr(settings, "data_source", "db")
    monkeypatch.setattr(settings, "database_url", None)

    client = TestClient(app)
    resp = client.get("/api/v1/dashboard/summary")
    assert resp.status_code == 503
    assert "DATA_SOURCE=db" in resp.json()["detail"]


def test_db_mode_fails_clearly_when_database_unreachable(monkeypatch):
    from pydantic import SecretStr

    monkeypatch.setattr(settings, "data_source", "db")
    monkeypatch.setattr(
        settings,
        "database_url",
        SecretStr("postgresql+psycopg://invalid:invalid@127.0.0.1:59999/nope"),
    )
    monkeypatch.setattr(settings, "db_connect_timeout", 1)

    from app.db.session import get_engine

    get_engine.cache_clear()
    try:
        client = TestClient(app)
        resp = client.get("/api/v1/patients")
        assert resp.status_code == 503
    finally:
        get_engine.cache_clear()


def test_postgres_read_repository_matches_memory_repository_on_seeded_subset():
    engine = _sqlite_multi_schema_engine()
    tables_to_create = [
        Standard.__table__,
        RuleLoad.__table__,
        Rule.__table__,
        RuleOpenQuestion.__table__,
        RuleItem.__table__,
        RuleItemOpenQuestion.__table__,
        OpenQuestion.__table__,
        GenerationRun.__table__,
        EvaluationRun.__table__,
        Patient.__table__,
        Guardian.__table__,
        HistoryAvailability.__table__,
        Consent.__table__,
        Appointment.__table__,
        IfhasScreening.__table__,
        WellChildVisit.__table__,
        ComponentResult.__table__,
        Assessment.__table__,
        Referral.__table__,
        EligibilityEvaluation.__table__,
        EvaluationReason.__table__,
        CareGap.__table__,
        OutreachEvent.__table__,
    ]
    test_meta = MetaData()
    for tbl in tables_to_create:
        copied = tbl.to_metadata(test_meta)
        copied.constraints = {
            c for c in copied.constraints if not isinstance(c, (CheckConstraint, ForeignKeyConstraint))
        }
        copied.foreign_keys.clear()
        for col in copied.columns:
            col.foreign_keys.clear()
            col.server_default = None
            if col.computed is not None:
                col.computed = None
            if not col.primary_key:
                col.nullable = True
            if isinstance(col.type, (JSONB, ARRAY)):
                col.type = JSON()
    test_meta.create_all(bind=engine)

    bundle = parse_clinical_bundle()
    ds = generate_synthetic_dataset(seed=20261116, total_patients=550, bundle=bundle)
    mem_repo = MemoryReadRepository()

    def _cols(model_cls, row: dict) -> dict:
        valid = {c.name for c in model_cls.__table__.columns}
        return {k: v for k, v in row.items() if k in valid}

    with Session(engine) as session:
        std_id_by_key: dict[tuple[str, str], int] = {}
        for idx_s, s in enumerate(bundle.standards, 1):
            row_s = _cols(Standard, s)
            row_s.setdefault("standard_id", idx_s)
            row_s.setdefault("publication_date_precision", "unknown")
            row_s.setdefault("effective_date_precision", "unknown")
            row_s.setdefault("acquisition_state", "document_obtained")
            session.add(Standard(**row_s))
            std_id_by_key[(s["source_name"], s["source_version"])] = row_s["standard_id"]
        for oq in bundle.open_questions:
            row_oq = _cols(OpenQuestion, oq)
            row_oq.setdefault("status", "open")
            session.execute(test_meta.tables["clinical.open_question"].insert().values(**row_oq))
        for r in bundle.rules:
            row_r = _cols(Rule, r)
            row_r["standard_id"] = std_id_by_key[(r["source_name"], r["source_version"])]
            row_r["load_id"] = 1
            session.execute(test_meta.tables["clinical.rule"].insert().values(**row_r))
        for roq in bundle.rule_open_questions:
            session.add(RuleOpenQuestion(**_cols(RuleOpenQuestion, roq)))
        for it in bundle.items:
            row_it = _cols(RuleItem, it)
            session.execute(test_meta.tables["clinical.rule_item"].insert().values(**row_it))
        for ioq in bundle.rule_item_open_questions:
            session.add(RuleItemOpenQuestion(**_cols(RuleItemOpenQuestion, ioq)))

        session.add(GenerationRun(**_cols(GenerationRun, ds.generation_run)))
        session.add(EvaluationRun(**_cols(EvaluationRun, ds.evaluation_run)))
        for p in ds.patients[:25]:
            session.add(Patient(**_cols(Patient, p)))
        p_ids = {p["patient_id"] for p in ds.patients[:25]}
        for gdn in ds.guardians:
            if gdn["patient_id"] in p_ids:
                session.add(Guardian(**_cols(Guardian, gdn)))
        for h in ds.history_availabilities:
            if h["patient_id"] in p_ids:
                session.add(HistoryAvailability(**_cols(HistoryAvailability, h)))
        for c in ds.consents:
            if c["patient_id"] in p_ids:
                session.add(Consent(**_cols(Consent, c)))
        for ap in ds.appointments:
            if ap["patient_id"] in p_ids:
                session.add(Appointment(**_cols(Appointment, ap)))
        for sc in ds.ifhas_screenings:
            if sc["patient_id"] in p_ids:
                session.add(IfhasScreening(**_cols(IfhasScreening, sc)))
        for wv in ds.well_child_visits:
            if wv["patient_id"] in p_ids:
                session.add(WellChildVisit(**_cols(WellChildVisit, wv)))
        for cr in ds.component_results:
            if cr["patient_id"] in p_ids:
                session.add(ComponentResult(**_cols(ComponentResult, cr)))
        for asm in ds.assessments:
            if asm["patient_id"] in p_ids:
                session.add(Assessment(**_cols(Assessment, asm)))
        for ref in ds.referrals:
            if ref["patient_id"] in p_ids:
                session.add(Referral(**_cols(Referral, ref)))
        ev_ids = set()
        for ev in ds.eligibility_evaluations:
            if ev["patient_id"] in p_ids:
                session.add(EligibilityEvaluation(**_cols(EligibilityEvaluation, ev)))
                ev_ids.add(ev["evaluation_id"])
        for er in ds.evaluation_reasons:
            if er["evaluation_id"] in ev_ids:
                session.add(EvaluationReason(**_cols(EvaluationReason, er)))
        for g in ds.care_gaps:
            if g["patient_id"] in p_ids:
                session.add(CareGap(**_cols(CareGap, g)))
        for oe in ds.outreach_events:
            if oe["patient_id"] in p_ids:
                session.add(OutreachEvent(**_cols(OutreachEvent, oe)))
        session.commit()

        db_repo = PostgresReadRepository(session)
        assert db_repo.list_rules(None, None, None).total == mem_repo.list_rules(None, None, None).total
        assert (
            db_repo.get_rule_detail("WCV-VISIT-15M").rule_id
            == mem_repo.get_rule_detail("WCV-VISIT-15M").rule_id
        )
        p_db = db_repo.get_patient("SYNTH-PAT-000001")
        p_mem = mem_repo.get_patient("SYNTH-PAT-000001")
        assert p_db is not None and p_mem is not None
        assert p_db.model_dump() == p_mem.model_dump()

        ev_db = db_repo.get_patient_evaluations("SYNTH-PAT-000001")
        ev_mem = mem_repo.get_patient_evaluations("SYNTH-PAT-000001")
        assert ev_db is not None and ev_mem is not None
        assert len(ev_db.evaluations) == len(ev_mem.evaluations) == 54
        assert len(ev_db.care_gaps) == len(ev_mem.care_gaps)

        # Sprint C DB coverage & parity checks
        h_db = db_repo.get_patient_history("SYNTH-PAT-000013")
        h_mem = mem_repo.get_patient_history("SYNTH-PAT-000013")
        assert h_db is not None and h_mem is not None
        assert h_db.model_dump() == h_mem.model_dump()

        c_db = db_repo.get_patient_consents("SYNTH-PAT-000021")
        c_mem = mem_repo.get_patient_consents("SYNTH-PAT-000021")
        assert c_db is not None and c_mem is not None
        assert [c.consent_id for c in c_db.current_states] == [
            c.consent_id for c in c_mem.current_states
        ]
        assert [c.state for c in c_db.current_states] == [
            c.state for c in c_mem.current_states
        ]
        assert [c.consent_id for c in c_db.history] == [c.consent_id for c in c_mem.history]

        # Sorting & filtering on DB subset
        db_sorted = db_repo.list_patients(10, 0, None, None, None, sort_by="age", sort_dir="asc")
        assert db_sorted.total == 25
        assert len(db_sorted.items) == 10

        # Care-gap detail parity
        first_gap_id = next(g["care_gap_id"] for g in ds.care_gaps if g["patient_id"] in p_ids)
        gd_db = db_repo.get_care_gap_detail(first_gap_id)
        gd_mem = mem_repo.get_care_gap_detail(first_gap_id)
        assert gd_db is not None and gd_mem is not None
        assert gd_db.model_dump() == gd_mem.model_dump()

        # Dashboard summary in DB mode
        dash_db = db_repo.get_dashboard_summary()
        assert dash_db.total_patients == 25
        assert sum(r.total_patients for r in dash_db.region_breakdown) == 25
        assert sum(r.open_care_gaps_count for r in dash_db.region_breakdown) == dash_db.open_care_gaps_count

        # Referral input_snapshot parity
        ref_pid = next((r["patient_id"] for r in ds.referrals if r["patient_id"] in p_ids), None)
        if ref_pid is not None:
            ref_ev_db = db_repo.get_patient_evaluations(ref_pid)
            ref_ev_mem = mem_repo.get_patient_evaluations(ref_pid)
            assert ref_ev_db is not None and ref_ev_mem is not None
            assert any(e.input_snapshot.get("has_referral") for e in ref_ev_db.evaluations)
            assert any(e.input_snapshot.get("has_referral") for e in ref_ev_mem.evaluations)


@pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL not set; live PostgreSQL read parity test skipped",
)
def test_live_postgres_read_repository_parity():
    live_engine = create_engine(os.environ["TEST_DATABASE_URL"])
    with Session(live_engine) as session:
        session.execute(text("SELECT 1"))
        db_repo = PostgresReadRepository(session)
        summary = db_repo.get_dashboard_summary()
        assert summary.is_synthetic is True
        assert summary.total_patients >= 1
