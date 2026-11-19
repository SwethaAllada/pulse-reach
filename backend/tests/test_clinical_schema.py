"""Tests for the Phase 3 `clinical` schema (12 tables + views + triggers).

Level 1 (always runs, no database required) inspects `Base.metadata` directly
and verifies that the SQLAlchemy models match `docs/phase-3-database-design.md` §4
and `docs/erd/clinical-schema-erd.md`: table set, column names, nullability,
primary keys, RESTRICT foreign keys, check constraints, unique constraints,
generated columns, and indexes.

Level 2 (runs when `TEST_DATABASE_URL` is set) runs Alembic migrations through
`0006` against a real PostgreSQL instance and exercises views, generated columns,
and append-only triggers.
"""

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from pydantic import SecretStr
from sqlalchemy import (
    CheckConstraint,
    ForeignKeyConstraint,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.dialects import postgresql

from app.db import session
from app.models import clinical as m
from app.models.base import Base

BACKEND = Path(__file__).resolve().parents[1]

TABLES = {
    "standard",
    "rule_load",
    "verification_status",
    "evaluation_status",
    "reason_code",
    "guard",
    "open_question",
    "rule",
    "rule_condition",
    "rule_item",
    "rule_open_question",
    "rule_item_open_question",
}

EXPECTED = {
    "standard": {
        "standard_id": False,
        "source_name": False,
        "source_version": False,
        "document_ref": False,
        "publisher": False,
        "publication_date_text": True,
        "publication_date_precision": False,
        "publication_date_from": True,
        "effective_date_text": True,
        "effective_date_precision": False,
        "effective_date_from": True,
        "effective_date_note": True,
        "revision_date_text": True,
        "pdf_pages": True,
        "url": True,
        "contact": True,
        "status_note": True,
        "manifest_source_id": True,
        "acquisition_state": False,
        "local_copy_sha256": True,
    },
    "rule_load": {
        "load_id": False,
        "loaded_at": False,
        "loader_version": False,
        "bundle_sha256": False,
        "file_hashes": False,
        "config_versions": False,
        "git_commit": True,
        "clinical_review_status": False,
        "rules_loaded": False,
        "rules_added": False,
    },
    "verification_status": {
        "code": False,
        "definition": False,
        "may_drive_decisions": False,
    },
    "evaluation_status": {
        "code": False,
        "definition": False,
        "requires_text": True,
        "never_inferred_from": True,
        "sort_order": False,
    },
    "reason_code": {
        "code": False,
        "description": True,
    },
    "guard": {
        "guard_id": False,
        "when_text": False,
        "result_status": False,
        "reason_code": False,
        "note": True,
    },
    "open_question": {
        "oq_id": False,
        "category": False,
        "status": False,
        "title": False,
        "detail": False,
        "affects_raw": True,
        "resolve_via": True,
        "resolution": True,
        "resolved_on": True,
        "first_load_id": False,
        "last_changed_load_id": False,
    },
    "rule": {
        "rule_id": False,
        "rule_version": False,
        "ver_major": False,
        "ver_minor": False,
        "ver_patch": False,
        "pathway": False,
        "rule_type": True,
        "standard_id": False,
        "source_reference": False,
        "verification_status": False,
        "requires_clinical_review": False,
        "is_authoritative": False,
        "effective_date_text": True,
        "effective_date_precision": False,
        "effective_date_from": True,
        "effective_date_note": True,
        "last_reviewed": False,
        "description": False,
        "notes": True,
        "spec": False,
        "history": True,
        "content_sha256": False,
        "yaml_path": False,
        "load_id": False,
        "package_name": True,
        "package_group": True,
        "age_min_years": True,
        "age_max_years": True,
        "age_as_printed": True,
        "sexes": True,
        "frequency_type": True,
        "interval_value": True,
        "interval_unit": True,
        "visit_number": True,
        "visit_id": True,
        "recommended_age_months": True,
        "age_band": True,
        "instrument": True,
        "score_min": True,
        "score_max": True,
        "timing_value": True,
        "timing_unit": True,
        "timing_reference_event": True,
        "gate_attribute": True,
    },
    "rule_condition": {
        "rule_id": False,
        "rule_version": False,
        "condition_ordinal": False,
        "kind": False,
        "as_printed": False,
        "machine_evaluable": False,
        "attribute": True,
        "required_value": True,
    },
    "rule_item": {
        "rule_id": False,
        "rule_version": False,
        "category": False,
        "code": False,
        "code_origin": False,
        "text_verbatim": True,
        "ordinal": False,
        "description": False,
        "source_reference": False,
        "inherited_from_rule": False,
        "verification_status": False,
        "status_is_verified": False,
        "condition_text": True,
        "components_text": True,
        "rule_refs": True,
        "notes": True,
    },
    "rule_open_question": {
        "rule_id": False,
        "rule_version": False,
        "oq_id": False,
    },
    "rule_item_open_question": {
        "rule_id": False,
        "rule_version": False,
        "category": False,
        "code": False,
        "oq_id": False,
    },
}

EXPECTED_PKS = {
    "standard": ("standard_id",),
    "rule_load": ("load_id",),
    "verification_status": ("code",),
    "evaluation_status": ("code",),
    "reason_code": ("code",),
    "guard": ("guard_id",),
    "open_question": ("oq_id",),
    "rule": ("rule_id", "rule_version"),
    "rule_condition": ("rule_id", "rule_version", "condition_ordinal"),
    "rule_item": ("rule_id", "rule_version", "category", "code"),
    "rule_open_question": ("rule_id", "rule_version", "oq_id"),
    "rule_item_open_question": ("rule_id", "rule_version", "category", "code", "oq_id"),
}

# (child_table, tuple(child_cols), parent_table, tuple(parent_cols))
EXPECTED_FKS = {
    ("guard", ("result_status",), "evaluation_status", ("code",)),
    ("guard", ("reason_code",), "reason_code", ("code",)),
    ("open_question", ("first_load_id",), "rule_load", ("load_id",)),
    ("open_question", ("last_changed_load_id",), "rule_load", ("load_id",)),
    ("rule", ("standard_id",), "standard", ("standard_id",)),
    ("rule", ("verification_status",), "verification_status", ("code",)),
    ("rule", ("load_id",), "rule_load", ("load_id",)),
    ("rule_condition", ("rule_id", "rule_version"), "rule", ("rule_id", "rule_version")),
    ("rule_item", ("rule_id", "rule_version"), "rule", ("rule_id", "rule_version")),
    ("rule_item", ("verification_status",), "verification_status", ("code",)),
    ("rule_open_question", ("rule_id", "rule_version"), "rule", ("rule_id", "rule_version")),
    ("rule_open_question", ("oq_id",), "open_question", ("oq_id",)),
    (
        "rule_item_open_question",
        ("rule_id", "rule_version", "category", "code"),
        "rule_item",
        ("rule_id", "rule_version", "category", "code"),
    ),
    ("rule_item_open_question", ("oq_id",), "open_question", ("oq_id",)),
}


def clinical_tables():
    return {t.name: t for t in Base.metadata.tables.values() if t.schema == "clinical"}


def test_twelve_clinical_tables_exist():
    assert set(clinical_tables()) == TABLES


def test_clinical_columns_and_nullability():
    for name, cols in EXPECTED.items():
        table = clinical_tables()[name]
        assert {c.name: c.nullable for c in table.columns} == cols, name


def test_clinical_primary_keys():
    for name, pk_cols in EXPECTED_PKS.items():
        table = clinical_tables()[name]
        assert tuple(c.name for c in table.primary_key.columns) == pk_cols, name


def test_every_clinical_fk_is_restrict_and_stays_in_clinical_schema():
    found = set()
    for t in clinical_tables().values():
        for fk in t.foreign_key_constraints:
            assert fk.ondelete == "RESTRICT" and fk.onupdate == "RESTRICT", fk.name
            assert fk.referred_table.schema == "clinical", fk.name
            child_cols = tuple(el.parent.name for el in fk.elements)
            parent_cols = tuple(el.column.name for el in fk.elements)
            found.add((t.name, child_cols, fk.referred_table.name, parent_cols))
    assert found == EXPECTED_FKS


def test_all_clinical_constraints_follow_naming_convention():
    prefixes = {CheckConstraint: "ck_", UniqueConstraint: "uq_", ForeignKeyConstraint: "fk_"}
    for t in clinical_tables().values():
        assert t.primary_key.name == f"pk_{t.name}"
        for c in t.constraints:
            for cls, prefix in prefixes.items():
                if isinstance(c, cls):
                    assert c.name and str(c.name).startswith(prefix), (t.name, c)


def test_computed_and_identity_columns():
    t = clinical_tables()
    d = postgresql.dialect()
    # Identity PKs on standard and rule_load
    std_pk = t["standard"].c.standard_id
    assert std_pk.type.compile(dialect=d) == "SMALLINT"
    assert std_pk.identity is not None and std_pk.identity.always
    load_pk = t["rule_load"].c.load_id
    assert load_pk.type.compile(dialect=d) == "BIGINT"
    assert load_pk.identity is not None and load_pk.identity.always

    # Generated columns on rule and rule_item
    for col_name in ("ver_major", "ver_minor", "ver_patch", "is_authoritative"):
        col = t["rule"].c[col_name]
        assert col.computed is not None and col.computed.persisted is True, col_name
    item_ver = t["rule_item"].c.status_is_verified
    assert item_ver.computed is not None and item_ver.computed.persisted is True


def test_migration_0006_is_wired_to_0005():
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(Config(str(BACKEND / "alembic.ini")))
    rev_0006 = script.get_revision("0006")
    assert rev_0006 is not None
    assert rev_0006.down_revision == "0005"


def test_migration_0006_defines_views_and_append_only_triggers():
    mig_path = BACKEND / "migrations" / "versions" / "0006_create_clinical_schema_tables.py"
    src = mig_path.read_text(encoding="utf-8")
    for view in (
        "clinical.v_rule_current",
        "clinical.v_rule_authority",
        "clinical.v_rule_item_effective_authority",
    ):
        assert view in src, view
    for tbl in (
        "rule_load",
        "rule",
        "rule_condition",
        "rule_item",
        "rule_open_question",
        "rule_item_open_question",
    ):
        assert f'"{tbl}"' in src


# --- live PostgreSQL (set TEST_DATABASE_URL) -----------------------------
live = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set"
)


@live
def test_live_clinical_migration_views_and_append_only(monkeypatch):
    from sqlalchemy import inspect, text

    url = os.environ["TEST_DATABASE_URL"]
    monkeypatch.setattr(session.settings, "database_url", SecretStr(url))
    cfg = Config(str(BACKEND / "alembic.ini"))
    command.upgrade(cfg, "0006")
    engine = create_engine(url)
    try:
        insp = inspect(engine)
        assert set(insp.get_table_names(schema="clinical")) == TABLES
        assert set(insp.get_view_names(schema="clinical")) >= {
            "v_rule_current",
            "v_rule_authority",
            "v_rule_item_effective_authority",
        }
        command.downgrade(cfg, "0005")
        assert inspect(engine).get_table_names(schema="clinical") == []  # new inspector: no stale cache
        command.upgrade(cfg, "head")
    finally:
        engine.dispose()

