"""Tests for the Phase 3 `synthetic` schema (18 tables + views + triggers).

Level 1 (always runs, no database required) inspects `Base.metadata` and verifies
that all 18 `synthetic` SQLAlchemy models match `docs/phase-3-database-design.md` §5:
table set, columns and nullability, `run_id` and `is_synthetic` on all 18 tables,
primary keys, composite RESTRICT foreign keys, check constraints, generated
evidence-marker columns, and migration `0007`.

Level 2 (runs when `TEST_DATABASE_URL` is set) runs Alembic migration `0007`
against PostgreSQL and checks tables and views.
"""

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from pydantic import SecretStr
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint, create_engine

from app.db import session
from app.models import synthetic as m
from app.models.base import Base

BACKEND = Path(__file__).resolve().parents[1]

TABLES = {
    "generation_run",
    "evaluation_run",
    "patient",
    "guardian",
    "consent",
    "facility_service_profile",
    "history_availability",
    "eligibility_evaluation",
    "evaluation_reason",
    "ifhas_screening",
    "well_child_visit",
    "component_result",
    "assessment",
    "referral",
    "care_gap",
    "care_gap_review",
    "care_gap_follow_up_event",
    "workflow_status_event",
    "appointment",
    "outreach_event",
    "ai_audit_record",
}

EXPECTED_PKS = {
    "generation_run": ("run_id",),
    "evaluation_run": ("evaluation_run_id",),
    "patient": ("patient_id",),
    "guardian": ("guardian_id",),
    "consent": ("consent_id",),
    "facility_service_profile": ("profile_id",),
    "history_availability": ("history_id",),
    "eligibility_evaluation": ("evaluation_id",),
    "evaluation_reason": ("reason_id",),
    "ifhas_screening": ("screening_id",),
    "well_child_visit": ("visit_id",),
    "component_result": ("component_result_id",),
    "assessment": ("assessment_id",),
    "referral": ("referral_id",),
    "care_gap": ("care_gap_id",),
    "care_gap_review": ("review_id",),
    "care_gap_follow_up_event": ("follow_up_id",),
    "workflow_status_event": ("status_event_id",),
    "ai_audit_record": ("audit_id",),
    "appointment": ("appointment_id",),
    "outreach_event": ("outreach_id",),
}

EXPECTED = {
    "generation_run": {
        "run_id": False,
        "is_synthetic": False,
        "generator_version": False,
        "generator_commit": True,
        "spec_version": False,
        "generation_seed": False,
        "started_at": False,
        "finished_at": True,
        "rule_bundle_load_id": False,
        "parameters": False,
        "calibration_inputs": False,
        "population_profile": False,
        "n_adults": False,
        "n_children": False,
        "clinically_validated": False,
        "data_card_path": False,
    },
    "evaluation_run": {
        "evaluation_run_id": False,
        "run_id": False,
        "is_synthetic": False,
        "rule_bundle_load_id": False,
        "reference_date": False,
        "age_convention": False,
        "look_ahead_days": True,
        "applicability_policy": False,
        "engine_version": False,
        "started_at": False,
    },
    "patient": {
        "patient_id": False,
        "run_id": False,
        "is_synthetic": False,
        "emirates_id_synthetic": False,
        "given_name": False,
        "family_name": False,
        "date_of_birth": True,
        "sex": True,
        "nationality_group": True,
        "region_id": False,
        "district_label": True,
        "thiqa_member": True,
        "ever_smoked": True,
        "preferred_language": False,
        "preferred_channel": False,
        "phone_synthetic": True,
        "email_synthetic": True,
        "contact_status": False,
        "registered_profile_id": True,
        "date_of_death": True,
    },
    "guardian": {
        "guardian_id": False,
        "run_id": False,
        "patient_id": False,
        "is_synthetic": False,
        "relationship": False,
        "given_name": False,
        "family_name": False,
        "phone_synthetic": True,
        "email_synthetic": True,
        "preferred_language": False,
        "preferred_channel": False,
        "contact_status": False,
    },
    "consent": {
        "consent_id": False,
        "run_id": False,
        "patient_id": False,
        "is_synthetic": False,
        "guardian_id": True,
        "consent_type": False,
        "state": False,
        "applies_to": False,
        "scope_pathway": True,
        "scope_rule_id": True,
        "scope_rule_version": True,
        "recorded_at": False,
        "recorded_by": False,
        "documented_in_record": True,
        "signature_on_file": True,
        "refusal_reason": True,
        "refusal_evidence_valid": False,
        "grants_contact": False,
        "grants_ai_scoring": False,
    },
    "facility_service_profile": {
        "profile_id": False,
        "run_id": False,
        "is_synthetic": False,
        "facility_id": False,
        "offers_ifhas": False,
        "offers_wcv": False,
        "evening_hours": False,
        "weekend_hours": False,
        "capability_basis": False,
    },
    "history_availability": {
        "history_id": False,
        "run_id": False,
        "patient_id": False,
        "is_synthetic": False,
        "pathway": False,
        "history_status": False,
        "as_of_date": False,
        "note": True,
    },
    "eligibility_evaluation": {
        "evaluation_id": False,
        "run_id": False,
        "patient_id": False,
        "is_synthetic": False,
        "evaluation_run_id": False,
        "rule_id": False,
        "rule_version": False,
        "evaluated_at": False,
        "evaluation_status": False,
        "reason_code": True,
        "next_due_date": True,
        "reason_detail": True,
        "input_snapshot": True,
    },
    "evaluation_reason": {
        "reason_id": False,
        "run_id": False,
        "patient_id": False,
        "is_synthetic": False,
        "evaluation_id": False,
        "rule_id": False,
        "rule_version": False,
        "reason_ordinal": False,
        "guard_id": True,
        "reason_code": False,
        "item_category": True,
        "item_code": True,
        "reason_detail": True,
    },
    "ifhas_screening": {
        "screening_id": False,
        "run_id": False,
        "patient_id": False,
        "is_synthetic": False,
        "profile_id": False,
        "rule_id": False,
        "rule_version": False,
        "appointment_id": True,
        "performed_date": True,
        "completion_status": False,
        "results_communicated_date": True,
        "journey_reported_date": True,
        "has_abnormal_finding": True,
        "has_performed": False,
    },
    "well_child_visit": {
        "visit_id": False,
        "run_id": False,
        "patient_id": False,
        "is_synthetic": False,
        "guardian_id": False,
        "profile_id": False,
        "rule_id": False,
        "rule_version": False,
        "appointment_id": True,
        "performed_date": True,
        "attendance_status": False,
        "is_catch_up_visit": False,
        "has_performed": False,
    },
    "component_result": {
        "component_result_id": False,
        "run_id": False,
        "patient_id": False,
        "is_synthetic": False,
        "ifhas_screening_id": True,
        "well_child_visit_id": True,
        "rule_id": False,
        "rule_version": False,
        "item_category": False,
        "item_code": False,
        "result_status": False,
        "performed_date": True,
        "documented_in_record": True,
        "signature_on_file": True,
        "refused_by_guardian_id": True,
        "refusal_reason": True,
        "refusal_evidence_valid": False,
    },
    "assessment": {
        "assessment_id": False,
        "run_id": False,
        "patient_id": False,
        "is_synthetic": False,
        "ifhas_screening_id": True,
        "well_child_visit_id": True,
        "instrument": False,
        "instrument_version": True,
        "administered_date": False,
        "raw_score": True,
        "item_responses": True,
        "rule_id": True,
        "rule_version": True,
    },
    "referral": {
        "referral_id": False,
        "run_id": False,
        "patient_id": False,
        "is_synthetic": False,
        "ifhas_screening_id": True,
        "well_child_visit_id": True,
        "assessment_id": True,
        "trigger_rule_id": False,
        "trigger_rule_version": False,
        "rule_action_ordinal": True,
        "referral_target": False,
        "target_profile_id": True,
        "trigger_date": False,
        "initiated_date": True,
        "completed_date": True,
        "status": False,
        "is_initiated": False,
    },
    "care_gap": {
        "care_gap_id": False,
        "run_id": False,
        "patient_id": False,
        "is_synthetic": False,
        "evaluation_id": False,
        "rule_id": False,
        "rule_version": False,
        "gap_type": False,
        "subject_ifhas_screening_id": True,
        "subject_well_child_visit_id": True,
        "subject_referral_id": True,
        "identified_date": False,
        "status": False,
        "closed_date": True,
        "suppression_reason": True,
        "closed_by_ifhas_screening_id": True,
        "closed_by_well_child_visit_id": True,
        "closed_by_referral_id": True,
        "closed_by_component_result_id": True,
        "closed_by_consent_id": True,
        "completion_evidence_marker": True,
        "refusal_evidence_marker": True,
        "priority_score": True,
        "priority_explanation": True,
        "scored_by_model_version": True,
        "scored_at": True,
        "scoring_consent_id": True,
        "scoring_consent_marker": True,
        "scoring_suppressed_reason": True,
    },
    "care_gap_review": {
        "review_id": False,
        "run_id": False,
        "care_gap_id": False,
        "is_synthetic": False,
        "reviewer": False,
        "action": False,
        "previous_priority": True,
        "new_priority": True,
        "reason": False,
        "reviewed_at": False,
    },
    "appointment": {
        "appointment_id": False,
        "run_id": False,
        "patient_id": False,
        "is_synthetic": False,
        "profile_id": False,
        "care_gap_id": True,
        "appointment_type": False,
        "scheduled_datetime": False,
        "slot_type": False,
        "status": False,
        "booked_via": False,
    },
    "outreach_event": {
        "outreach_id": False,
        "run_id": False,
        "patient_id": False,
        "is_synthetic": False,
        "care_gap_id": False,
        "guardian_id": True,
        "recipient": False,
        "event_type": False,
        "channel": False,
        "sent_datetime": True,
        "delivery_status": False,
        "suppression_reason": True,
        "contact_consent_id": True,
        "contact_consent_marker": True,
        "response": True,
        "appointment_id": True,
        "triggered_by_ai_score": False,
        "clinician_approved_by": True,
        "message_template_id": True,
    },
}


def synthetic_tables():
    return {t.name: t for t in Base.metadata.tables.values() if t.schema == "synthetic"}


def test_eighteen_synthetic_tables_exist():
    assert set(synthetic_tables()) == TABLES


def test_every_synthetic_table_has_run_id_and_is_synthetic():
    for name, t in synthetic_tables().items():
        assert "run_id" in t.c and not t.c.run_id.nullable, name
        assert "is_synthetic" in t.c and not t.c.is_synthetic.nullable, name


def test_synthetic_columns_and_nullability():
    for name, cols in EXPECTED.items():
        table = synthetic_tables()[name]
        assert {c.name: c.nullable for c in table.columns} == cols, name


def test_synthetic_primary_keys():
    for name, pk_cols in EXPECTED_PKS.items():
        table = synthetic_tables()[name]
        assert tuple(c.name for c in table.primary_key.columns) == pk_cols, name


def test_every_synthetic_fk_is_restrict_and_same_run_enforced():
    for name, t in synthetic_tables().items():
        for fk in t.foreign_key_constraints:
            assert fk.ondelete == "RESTRICT" and fk.onupdate == "RESTRICT", (name, fk.name)
            assert fk.referred_table.schema in ("synthetic", "clinical", "official"), fk.name
            if fk.referred_table.schema == "synthetic":
                child_cols = [el.parent.name for el in fk.elements]
                assert "run_id" in child_cols, (name, fk.name, child_cols)


def test_all_synthetic_constraints_follow_naming_convention():
    prefixes = {CheckConstraint: "ck_", UniqueConstraint: "uq_", ForeignKeyConstraint: "fk_"}
    for t in synthetic_tables().values():
        assert t.primary_key.name == f"pk_{t.name}"
        for c in t.constraints:
            for cls, prefix in prefixes.items():
                if isinstance(c, cls):
                    assert c.name and str(c.name).startswith(prefix), (t.name, c)


def test_generated_marker_columns_are_persisted():
    t = synthetic_tables()
    for tbl_name, col_names in (
        ("consent", ("refusal_evidence_valid", "grants_contact", "grants_ai_scoring")),
        ("ifhas_screening", ("has_performed",)),
        ("well_child_visit", ("has_performed",)),
        ("component_result", ("refusal_evidence_valid",)),
        ("referral", ("is_initiated",)),
        (
            "care_gap",
            (
                "completion_evidence_marker",
                "refusal_evidence_marker",
                "scoring_consent_marker",
            ),
        ),
        ("outreach_event", ("contact_consent_marker",)),
        ("ai_audit_record", ("draft_feature",)),
    ):
        for col_name in col_names:
            col = t[tbl_name].c[col_name]
            assert col.computed is not None and col.computed.persisted is True, (
                tbl_name,
                col_name,
            )


def test_migration_0007_is_wired_to_0006():
    from alembic.script import ScriptDirectory

    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    script = ScriptDirectory.from_config(cfg)
    rev_0007 = script.get_revision("0007")
    assert rev_0007 is not None
    assert rev_0007.down_revision == "0006"


def test_migration_0007_append_only_trigger_has_scoped_reset_guard():
    mig_path = BACKEND / "migrations" / "versions" / "0007_create_synthetic_schema_tables.py"
    text = mig_path.read_text(encoding="utf-8")
    assert "pulsereach.allow_synthetic_reset" in text
    assert "IF TG_OP = 'DELETE'" in text


def test_migration_0007_uses_frozen_static_ddl():
    mig_path = BACKEND / "migrations" / "versions" / "0007_create_synthetic_schema_tables.py"
    src = mig_path.read_text(encoding="utf-8")
    assert "app.models" not in src
    assert "Base.metadata" not in src
    for tbl_name in TABLES - {"care_gap_follow_up_event", "workflow_status_event", "ai_audit_record"}:
        assert f"CREATE TABLE synthetic.{tbl_name}" in src


# --- live PostgreSQL (set TEST_DATABASE_URL) -----------------------------
live = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set"
)


@live
def test_live_synthetic_migration(monkeypatch):
    from sqlalchemy import inspect, text

    from app.services.clinical_loader import load as clinical_load
    from app.services.synthetic_generator import generate_synthetic_dataset, load_synthetic_dataset

    url = os.environ["TEST_DATABASE_URL"]
    monkeypatch.setattr(session.settings, "database_url", SecretStr(url))
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    command.upgrade(cfg, "head")
    engine = create_engine(url)
    try:
        insp = inspect(engine)
        assert set(insp.get_table_names(schema="synthetic")) == TABLES
        assert set(insp.get_view_names(schema="synthetic")) >= {
            "v_consent_current",
            "v_history_availability_current",
            "v_eligibility_current",
            "v_care_gap_effective_priority",
        }
        from app.services import official_loader

        clinical_load.run(engine)
        with engine.connect() as conn:
            has_facilities = conn.execute(text("SELECT count(*) FROM official.facility")).scalar_one()
        if not has_facilities:  # synthetic profiles reference real official.facility rows
            assert official_loader.run(engine=engine)["quarantined"] == []
        small_ds = generate_synthetic_dataset(seed=20261116, total_patients=35)
        res1 = load_synthetic_dataset(engine, small_ds, reset_existing_run=True)
        res2 = load_synthetic_dataset(engine, small_ds, reset_existing_run=True)
        assert res1 == res2
    finally:
        engine.dispose()
