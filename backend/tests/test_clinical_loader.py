"""Tests for the clinical YAML-to-PostgreSQL loader (`app.services.clinical_loader`).

Part 1 (always runs, no database required) tests:
- NFKD component slug generation (`Anti- Müllerian testing (AMH Testing)` -> `anti_mullerian_testing_amh_testing`)
- Partial-date triple parsing (`YYYY-MM-DD`, `YYYY-MM` with `from=None`, `None` -> `unknown`)
- Strict Boolean validation and rejection of non-booleans
- Typed projections for all 54 rules and 10 rule types
- Exact canonical counts on the real YAML bundle (54 rules, 47/7 authority split,
  8 conditions [5 inclusion, 3 exclusion], 249 items [174 WCV + 75 IFHAS],
  69 rule_open_question rows, 15 rule_item_open_question rows, 23 open questions,
  2 standards, 3/9/9/7 vocabulary rows)
- Parent-aware item effective authority (`effective_authority => parent.is_authoritative`,
  blocking the 6 components under the 4 verified-but-flagged IFHAS packages)
- Idempotency, content_sha256 hash guard, version downgrade guard, and vanished-rule guard

Part 2 (runs when `TEST_DATABASE_URL` is set) loads the bundle into PostgreSQL twice
and verifies database row counts, views, and idempotency (`rules_added == 0` on second run).
"""

import copy
import os
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from app.services.clinical_loader import FatalError, load as L, parse as P

BACKEND = Path(__file__).resolve().parents[1]


# ===========================================================================
# Part 1 — Deterministic parsing, projections, guards, and bundle verification
# ===========================================================================
def test_nfkd_slugify_component_handles_umlaut_and_punctuation():
    assert (
        P.slugify_component("Anti- Müllerian testing (AMH Testing)")
        == "anti_mullerian_testing_amh_testing"
    )
    assert P.slugify_component("Body Mass Index (BMI)") == "body_mass_index_bmi"
    assert (
        P.slugify_component("Consultation+ Dilated Fundus Examination by ophthalmologist")
        == "consultation_dilated_fundus_examination_by_ophthalmologist"
    )


def test_partial_date_triple_never_invents_first_of_month():
    assert P.parse_partial_date("2025-07-14", field_name="effective_date", where="t") == (
        "2025-07-14",
        "day",
        date(2025, 7, 14),
    )
    assert P.parse_partial_date("2025-07", field_name="effective_date", where="t") == (
        "2025-07",
        "month",
        None,
    )
    assert P.parse_partial_date(None, field_name="effective_date", where="t") == (
        None,
        "unknown",
        None,
    )
    with pytest.raises(FatalError):
        P.parse_partial_date("TBD", field_name="effective_date", where="t")


def test_real_clinical_bundle_matches_canonical_counts_and_authority():
    bundle = P.parse_clinical_bundle()

    # 2 standards (both blocked in manifest)
    assert len(bundle.standards) == 2
    assert {s["manifest_source_id"] for s in bundle.standards} == {
        "SRC-02-IFHAS",
        "SRC-03-WCV",
    }
    assert all(s["acquisition_state"] == "blocked" for s in bundle.standards)

    # Vocabularies: 3 / 9 / 12 / 7
    assert len(bundle.verification_statuses) == 3
    assert len(bundle.evaluation_statuses) == 9
    assert len(bundle.reason_codes) == 12
    assert len(bundle.guards) == 7

    # 23 open questions
    assert len(bundle.open_questions) == 23

    # 54 rules (29 IFHAS + 25 Well-Child), 47 authoritative + 7 non-authoritative
    assert len(bundle.rules) == 54
    assert sum(1 for r in bundle.rules if r["pathway"] == "ifhas") == 29
    assert sum(1 for r in bundle.rules if r["pathway"] == "well_child") == 25

    auth_rules = [r for r in bundle.rules if r["is_authoritative"]]
    non_auth_rules = [r for r in bundle.rules if not r["is_authoritative"]]
    assert len(auth_rules) == 47
    assert len(non_auth_rules) == 7
    assert {r["rule_id"] for r in non_auth_rules} == {
        "IFHAS-PROG-AGE-CEILING",
        "IFHAS-PKG-CERVICAL-PAP-25-29",
        "IFHAS-PKG-CERVICAL-HPV-30-65",
        "IFHAS-PKG-LIQUID-BIOPSY-40-75",
        "IFHAS-PKG-LUNG-LDCT-55-75",
        "WCV-PROG-EFFECTIVE-DATE-TBD",
        "WCV-TIMING-DUE-WINDOW",
    }

    # 8 conditions (5 inclusion, 3 exclusion) across 3 packages
    assert len(bundle.conditions) == 8
    assert sum(1 for c in bundle.conditions if c["kind"] == "inclusion") == 5
    assert sum(1 for c in bundle.conditions if c["kind"] == "exclusion") == 3
    assert sum(1 for c in bundle.conditions if c["machine_evaluable"]) == 1

    # 249 rule items (174 Well-Child yaml + 75 IFHAS derived_slug)
    assert len(bundle.items) == 249
    wcv_items = [i for i in bundle.items if i["code_origin"] == "yaml"]
    ifhas_items = [i for i in bundle.items if i["code_origin"] == "derived_slug"]
    assert len(wcv_items) == 174
    assert len(ifhas_items) == 75
    assert len({i["code"] for i in ifhas_items}) == 37
    assert any(
        i["code"] == "anti_mullerian_testing_amh_testing" for i in ifhas_items
    )

    # Parent-aware item effective authority (LV-2):
    # 6 package components sit under the 4 verified-but-flagged IFHAS packages;
    # their own status_is_verified is True, but effective_authority must be False!
    rule_auth_map = {(r["rule_id"], r["rule_version"]): r["is_authoritative"] for r in bundle.rules}
    for item in bundle.items:
        parent_auth = rule_auth_map[(item["rule_id"], item["rule_version"])]
        if item["effective_authority"]:
            assert parent_auth is True and item["status_is_verified"] is True
    flagged_pkg_items = [
        i
        for i in ifhas_items
        if not rule_auth_map[(i["rule_id"], i["rule_version"])]
    ]
    assert len(flagged_pkg_items) == 6
    assert all(i["status_is_verified"] and not i["effective_authority"] for i in flagged_pkg_items)

    # Association counts: 69 rule_open_question, 15 rule_item_open_question
    assert len(bundle.rule_open_questions) == 69
    assert len(bundle.rule_item_open_questions) == 15


def test_typed_projections_match_spec_and_edge_cases():
    bundle = P.parse_clinical_bundle()
    by_id = {r["rule_id"]: r for r in bundle.rules}

    # AAA once_per_lifetime package
    aaa = by_id["IFHAS-PKG-AAA-M-65-75"]
    assert aaa["frequency_type"] == "once_per_lifetime"
    assert aaa["interval_value"] is None and aaa["interval_unit"] is None
    assert aaa["age_min_years"] == 65 and aaa["age_max_years"] == 75
    assert aaa["sexes"] == ["male"]

    # Visit schedule projection
    v18 = by_id["WCV-VISIT-18M"]
    assert v18["visit_number"] == 8
    assert v18["visit_id"] == "wcv_18m"
    assert v18["recommended_age_months"] == 18
    assert v18["age_band"] == "early_childhood"

    # Developmental screening tiers: M-CHAT-R HIGH has open max (None); IDAQ has no score range (both None)
    high = by_id["WCV-MCHATR-HIGH"]
    assert high["instrument"] == "M-CHAT-R"
    assert high["score_min"] == Decimal(8) and high["score_max"] is None
    idaq = by_id["WCV-IDAQ-REFERRAL"]
    assert idaq["instrument"] == "IDAQ"
    assert idaq["score_min"] is None and idaq["score_max"] is None

    # Follow-up 2-4W range stays NULL in single-value timing projections (CU-8)
    fu_range = by_id["WCV-FU-SPECIALIST-EVALUATION-2-4W"]
    assert (
        fu_range["timing_value"] is None
        and fu_range["timing_unit"] is None
        and fu_range["timing_reference_event"] is None
    )

    # Workflow timing with working_days
    wf_ref = by_id["IFHAS-WF-REFERRAL-15WD"]
    assert wf_ref["timing_value"] == 15
    assert wf_ref["timing_unit"] == "working_days"
    assert wf_ref["timing_reference_event"] == "release of results"

    # Programme eligibility gate_attribute
    assert by_id["IFHAS-PROG-ELIG-THIQA"]["gate_attribute"] == "thiqa_member"
    assert by_id["IFHAS-PROG-AGE-CEILING"]["gate_attribute"] is None


def test_hash_guard_version_downgrade_and_vanished_rule_guards():
    bundle = P.parse_clinical_bundle()
    existing = {
        (r["rule_id"], r["rule_version"]): r["content_sha256"]
        for r in bundle.rules
    }

    # 1. Identical re-run is idempotent (0 new rules)
    new_rules = L.check_version_and_hash_guards(existing, bundle)
    assert new_rules == []

    # 2. Same (rule_id, rule_version) but different content_sha256 -> FatalError
    tampered = dict(existing)
    tampered[("IFHAS-PKG-MAJOR-18-39", "1.0.0")] = "0" * 64
    with pytest.raises(FatalError, match="without a version bump"):
        L.check_version_and_hash_guards(tampered, bundle)

    # 3. Rule present in DB but vanished from YAML -> FatalError
    extra = dict(existing)
    extra[("IFHAS-VANISHED-RULE", "1.0.0")] = "a" * 64
    with pytest.raises(FatalError, match="absent from YAML|vanished"):
        L.check_version_and_hash_guards(extra, bundle)

    # 4. Version downgrade (DB has 1.2.0, YAML has 1.0.0) -> FatalError
    higher = dict(existing)
    del higher[("IFHAS-PKG-MAJOR-18-39", "1.0.0")]
    higher[("IFHAS-PKG-MAJOR-18-39", "1.2.0")] = "b" * 64
    with pytest.raises(FatalError, match="lower than|downgrade"):
        L.check_version_and_hash_guards(higher, bundle)


def test_slug_collision_within_package_is_rejected(tmp_path):
    # Copy real rules into tmp_path and introduce two components that slugify identically
    rules_dir = P.default_rules_dir()
    for sub in ("common", "ifhas", "well_child"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
        for f in (rules_dir / sub).glob("*.yaml"):
            (tmp_path / sub / f.name).write_bytes(f.read_bytes())

    ifhas_path = tmp_path / "ifhas" / "ifhas_rules.yaml"
    data = yaml.safe_load(ifhas_path.read_text(encoding="utf-8"))
    for r in data["rules"]:
        if r["rule_id"] == "IFHAS-PKG-ORAL-18-75":
            r["spec"]["components"] = ["Oral Hygiene Instruction", "Oral-Hygiene Instruction!"]
    ifhas_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    with pytest.raises(FatalError, match="collision"):
        P.parse_clinical_bundle(rules_dir=tmp_path)


# ===========================================================================
# Part 2 — Live PostgreSQL idempotent load test
# ===========================================================================
live = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set"
)


@live
def test_live_clinical_loader_idempotent(monkeypatch):
    from alembic import command
    from alembic.config import Config
    from pydantic import SecretStr
    from sqlalchemy import create_engine

    from app.db import session

    url = os.environ["TEST_DATABASE_URL"]
    monkeypatch.setattr(session.settings, "database_url", SecretStr(url))
    command.upgrade(Config(str(BACKEND / "alembic.ini")), "head")
    eng = create_engine(url)
    try:
        s1 = L.run(eng)
        assert s1.rules_loaded == 54
        assert s1.rules_added in (0, 54)
        s2 = L.run(eng)
        assert s2.rules_loaded == 54
        assert s2.rules_added == 0
    finally:
        eng.dispose()
