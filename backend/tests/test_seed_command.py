"""Tests for the database seed command (`python -m app.services.synthetic_generator.seed`, F-02).

Part 1 (no database): the command imports and runs the real clinical loader; missing, invalid or
malformed clinical inputs, a missing `DATABASE_URL` and an unreachable database all exit 2.

Part 2 (`TEST_DATABASE_URL`, disposable database): runs `alembic upgrade head`, the real official
loader and the seed command, then checks prerequisites, row counts, referential integrity,
repeatability, loader failure propagation and `--no-replace` failure.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from pydantic import SecretStr
from sqlalchemy import create_engine, text

from app.core.config import settings
from app.db.session import get_engine
from app.services import clinical_loader
from app.services.clinical_loader.parse import default_rules_dir
from app.services.synthetic_generator import seed as seed_cmd

BACKEND = Path(__file__).resolve().parents[1]
IFHAS_RULES = Path("ifhas") / "ifhas_rules.yaml"


@pytest.fixture
def rules_copy(tmp_path, monkeypatch) -> Path:
    """A writable copy of the real clinical rules, used as `RULES_DIR` for the seed command."""
    dst = tmp_path / "rules"
    shutil.copytree(default_rules_dir(), dst)
    monkeypatch.setattr(settings, "rules_dir", str(dst))
    return dst


@pytest.fixture
def no_database(monkeypatch):
    monkeypatch.setattr(settings, "database_url", None)
    get_engine.cache_clear()
    yield
    get_engine.cache_clear()


def _edit_rule(rules_dir: Path, rule_id: str, **changes) -> None:
    path = rules_dir / IFHAS_RULES
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    next(r for r in doc["rules"] if r["rule_id"] == rule_id).update(changes)
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")


# ---------------------------------------------------------------------------
# Part 1 - no database
# ---------------------------------------------------------------------------


def test_seed_uses_the_real_clinical_loader():
    assert seed_cmd.load_clinical_bundle is clinical_loader.run


def test_documented_seed_module_starts_from_backend_directory():
    proc = subprocess.run(
        [sys.executable, "-m", "app.services.synthetic_generator.seed", "--help"],
        cwd=BACKEND, capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    assert "--total-patients" in proc.stdout


def test_seed_without_database_url_exits_2(no_database, capsys):
    assert seed_cmd.main([]) == 2
    assert "DATABASE_URL is not set" in capsys.readouterr().err


def test_seed_with_missing_clinical_file_exits_2(rules_copy, no_database, capsys):
    (rules_copy / IFHAS_RULES).unlink()
    assert seed_cmd.main([]) == 2
    assert "missing clinical YAML file: ifhas/ifhas_rules.yaml" in capsys.readouterr().err


def test_seed_with_invalid_clinical_data_exits_2(rules_copy, no_database, capsys):
    _edit_rule(rules_copy, "IFHAS-PKG-VISION-40-75", requires_clinical_review="yes")
    assert seed_cmd.main([]) == 2
    err = capsys.readouterr().err
    assert "invalid clinical bundle" in err and "requires_clinical_review" in err


def test_seed_with_malformed_clinical_yaml_exits_2(rules_copy, no_database, capsys):
    (rules_copy / IFHAS_RULES).write_text("rules: [unterminated\n", encoding="utf-8")
    assert seed_cmd.main([]) == 2
    assert "invalid clinical bundle" in capsys.readouterr().err


def test_seed_with_unreachable_database_exits_2(monkeypatch, capsys):
    monkeypatch.setattr(
        settings, "database_url", SecretStr("postgresql+psycopg://u:p@127.0.0.1:59999/nope")
    )
    monkeypatch.setattr(settings, "db_connect_timeout", 1)
    get_engine.cache_clear()
    try:
        assert seed_cmd.main([]) == 2
    finally:
        get_engine.cache_clear()
    assert "database error (OperationalError)" in capsys.readouterr().err


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
    eng = create_engine(url)
    try:
        yield eng
    finally:
        eng.dispose()
        get_engine.cache_clear()


def _scalar(eng, sql: str, **params):
    with eng.connect() as conn:
        return conn.execute(text(sql), params).scalar_one()


def _synthetic_counts(eng) -> dict[str, int]:
    return {t: _scalar(eng, f"SELECT count(*) FROM synthetic.{t}") for t in seed_cmd._RECONCILED_TABLES}


def _ensure_official_loaded(eng) -> None:
    from app.services import official_loader

    if _scalar(eng, "SELECT count(*) FROM official.facility") == 0:
        report = official_loader.run(engine=eng)
        assert report["quarantined"] == [], report["quarantined"]


@live
def test_live_seed_refuses_without_official_facilities(live_db, capsys):
    if _scalar(live_db, "SELECT count(*) FROM official.facility") > 0:
        pytest.skip("official.facility already loaded in this database")
    loads_before = _scalar(live_db, "SELECT count(*) FROM clinical.rule_load")
    assert seed_cmd.main([]) == 2
    assert "Run `python -m app.services.official_loader` first" in capsys.readouterr().err
    assert _scalar(live_db, "SELECT count(*) FROM clinical.rule_load") == loads_before
    assert _scalar(live_db, "SELECT count(*) FROM synthetic.patient") == 0


@live
def test_live_seed_loads_reconciles_and_preserves_integrity(live_db, capsys):
    _ensure_official_loaded(live_db)
    assert seed_cmd.main([]) == 0
    out = capsys.readouterr().out
    assert '"reconciliation"' in out

    bundle = clinical_loader.parse_clinical_bundle()
    assert _scalar(live_db, "SELECT count(*) FROM clinical.rule") == len(bundle.rules)
    assert _scalar(live_db, "SELECT count(*) FROM clinical.rule_item") == len(bundle.items)
    ds = seed_cmd.generate_synthetic_dataset(bundle=bundle)
    counts = _synthetic_counts(live_db)
    for table, attr in seed_cmd._RECONCILED_TABLES.items():
        assert counts[table] == len(getattr(ds, attr)), table
    latest_load = _scalar(live_db, "SELECT max(load_id) FROM clinical.rule_load")
    assert _scalar(live_db, "SELECT rule_bundle_load_id FROM synthetic.generation_run") == latest_load
    orphans = {
        "fsp->official.facility": "SELECT count(*) FROM synthetic.facility_service_profile f "
        "LEFT JOIN official.facility o ON o.facility_id = f.facility_id WHERE o.facility_id IS NULL",
        "evaluation->clinical.rule": "SELECT count(*) FROM synthetic.eligibility_evaluation e "
        "LEFT JOIN clinical.rule r ON (r.rule_id, r.rule_version) = (e.rule_id, e.rule_version) "
        "WHERE r.rule_id IS NULL",
        "care_gap->evaluation": "SELECT count(*) FROM synthetic.care_gap g "
        "LEFT JOIN synthetic.eligibility_evaluation e ON e.evaluation_id = g.evaluation_id "
        "WHERE e.evaluation_id IS NULL",
    }
    assert {k: _scalar(live_db, q) for k, q in orphans.items()} == dict.fromkeys(orphans, 0)


@live
def test_live_seed_is_repeatable_and_clinical_load_idempotent(live_db):
    _ensure_official_loaded(live_db)
    first = seed_cmd.seed_database(engine=live_db)
    again = seed_cmd.seed_database(engine=live_db)
    assert again["clinical"]["rules_added"] == 0
    assert again["reconciliation"] == first["reconciliation"]


@live
def test_live_clinical_loader_failure_propagates(live_db, rules_copy, capsys):
    _ensure_official_loaded(live_db)
    seed_cmd.seed_database(engine=live_db)
    before = _synthetic_counts(live_db)
    loads_before = _scalar(live_db, "SELECT count(*) FROM clinical.rule_load")
    _edit_rule(rules_copy, "IFHAS-PKG-VISION-40-75", description="Edited without a version bump.")
    assert seed_cmd.main([]) == 2
    assert "content_sha256 changed without a version bump" in capsys.readouterr().err
    assert _scalar(live_db, "SELECT count(*) FROM clinical.rule_load") == loads_before
    assert _synthetic_counts(live_db) == before


@live
def test_live_seed_no_replace_on_existing_run_exits_2(live_db, capsys):
    _ensure_official_loaded(live_db)
    seed_cmd.seed_database(engine=live_db)
    before = _synthetic_counts(live_db)
    assert seed_cmd.main(["--no-replace"]) == 2
    assert "database error (IntegrityError)" in capsys.readouterr().err
    assert _synthetic_counts(live_db) == before
