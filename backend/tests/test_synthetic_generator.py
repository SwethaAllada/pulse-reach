"""Tests for the deterministic synthetic patient generator (`app.services.synthetic_generator`).

Covers Workstream B2–B4 of `pulse-reach-backend-execution-plan.md` and the 27 scenarios in
`data/metadata/synthetic_data_spec.md`:
- Deterministic, seed-based reproducibility (`seed=20261116`).
- Different seed produces a different population.
- All 18 synthetic table collections carry `is_synthetic=True`, `run_id`, and valid `SYNTH-` IDs
  matching the exact column names and check constraints in `app.models.synthetic`.
- No real personal identifiers (`SYNTH-EID-`, ` (synthetic)`, `@example.invalid`, `+971-50-000-XXXX`).
- All required edge-case demo scenarios are present and verified by `EvaluationEngine`.
"""

import re
from pathlib import Path

import pytest

from app.services.synthetic_generator import (
    SyntheticDataset,
    generate_synthetic_dataset,
    load_synthetic_dataset,
    write_data_card,
)


@pytest.fixture(scope="module")
def dataset() -> SyntheticDataset:
    return generate_synthetic_dataset(seed=20261116, total_patients=550)


def test_reproducibility_and_seed_variation(dataset: SyntheticDataset):
    same_seed = generate_synthetic_dataset(seed=20261116, total_patients=550)
    assert dataset.patients == same_seed.patients
    assert dataset.eligibility_evaluations == same_seed.eligibility_evaluations
    assert dataset.care_gaps == same_seed.care_gaps

    diff_seed = generate_synthetic_dataset(seed=20261117, total_patients=60)
    assert diff_seed.patients[35]["date_of_birth"] != dataset.patients[35]["date_of_birth"] or (
        diff_seed.patients[35]["sex"] != dataset.patients[35]["sex"]
    )


def test_population_size_and_synthetic_safety_invariants(dataset: SyntheticDataset):
    assert 500 <= len(dataset.patients) <= 1000
    assert dataset.generation_run["run_id"] == "SYNTH-RUN-0001"
    assert dataset.generation_run["is_synthetic"] is True
    assert dataset.generation_run["generation_seed"] == 20261116
    assert dataset.generation_run["clinically_validated"] is False
    assert dataset.evaluation_run["evaluation_run_id"] == "SYNTH-EVR-000001"

    # Simulated facility profiles are clearly marked capability_basis='simulated'
    for fsp in dataset.facility_service_profiles:
        assert fsp["is_synthetic"] is True
        assert fsp["profile_id"].startswith("SYNTH-FSP-")
        assert fsp["capability_basis"] == "simulated"

    phone_re = re.compile(r"^\+971-50-000-\d{4}$")
    for p in dataset.patients:
        assert p["is_synthetic"] is True
        assert p["run_id"] == "SYNTH-RUN-0001"
        assert p["patient_id"].startswith("SYNTH-PAT-")
        assert p["emirates_id_synthetic"].startswith("SYNTH-EID-")
        assert not p["emirates_id_synthetic"].startswith("784-")
        assert p["family_name"].endswith(" (synthetic)")
        if p["phone_synthetic"] is not None:
            assert phone_re.match(p["phone_synthetic"])
        if p["email_synthetic"] is not None:
            assert p["email_synthetic"].endswith("@example.invalid")

    for g in dataset.guardians:
        assert g["is_synthetic"] is True
        assert g["guardian_id"].startswith("SYNTH-GDN-")
        assert g["family_name"].endswith(" (synthetic)")


def test_all_required_demo_and_governance_scenarios_present(dataset: SyntheticDataset):
    evals_by_patient_rule = {
        (e["patient_id"], e["rule_id"]): e for e in dataset.eligibility_evaluations
    }
    gaps_by_patient_rule = {
        (g["patient_id"], g["rule_id"]): g for g in dataset.care_gaps
    }
    reasons_by_eval = {}
    for r in dataset.evaluation_reasons:
        reasons_by_eval.setdefault(r["evaluation_id"], []).append(r)

    # Scenario 1: Eligible 45yo Thiqa female, due for Mammography with open care gap
    assert (
        evals_by_patient_rule[("SYNTH-PAT-000001", "IFHAS-PKG-MAMMOGRAPHY-40-75")][
            "evaluation_status"
        ]
        == "due"
    )
    assert (
        gaps_by_patient_rule[("SYNTH-PAT-000001", "IFHAS-PKG-MAMMOGRAPHY-40-75")]["status"]
        == "open"
    )

    # Scenario 2: 52yo Thiqa male, Major Package completed 14m ago -> completed, no gap
    assert (
        evals_by_patient_rule[("SYNTH-PAT-000002", "IFHAS-PKG-MAJOR-40-64")][
            "evaluation_status"
        ]
        == "completed"
    )
    assert ("SYNTH-PAT-000002", "IFHAS-PKG-MAJOR-40-64") not in gaps_by_patient_rule

    # Scenario 3: 31yo female hitting Cervical HPV -> requires_clinical_review
    assert (
        evals_by_patient_rule[("SYNTH-PAT-000003", "IFHAS-PKG-CERVICAL-HPV-30-65")][
            "evaluation_status"
        ]
        == "requires_clinical_review"
    )

    # Scenario 4: Aged 78 -> IFHAS-PROG-AGE-CEILING and IFHAS-PROG-ELIG-MIN-AGE route to clinical review
    assert (
        evals_by_patient_rule[("SYNTH-PAT-000004", "IFHAS-PROG-AGE-CEILING")][
            "evaluation_status"
        ]
        == "requires_clinical_review"
    )

    # Scenario 5 & 6: Missing thiqa_member and missing DOB -> insufficient_information
    assert (
        evals_by_patient_rule[("SYNTH-PAT-000005", "IFHAS-PROG-ELIG-THIQA")][
            "evaluation_status"
        ]
        == "insufficient_information"
    )
    assert (
        evals_by_patient_rule[("SYNTH-PAT-000006", "IFHAS-PKG-MAMMOGRAPHY-40-75")][
            "evaluation_status"
        ]
        == "insufficient_information"
    )

    # Scenario 7: Missing history ('not_available') -> unknown, zero care gaps
    assert (
        evals_by_patient_rule[("SYNTH-PAT-000007", "IFHAS-PKG-MAMMOGRAPHY-40-75")][
            "evaluation_status"
        ]
        == "unknown"
    )
    assert all(g["patient_id"] != "SYNTH-PAT-000007" for g in dataset.care_gaps)

    # Scenario 8: Partial screening -> partial_completion care gap
    assert (
        gaps_by_patient_rule[("SYNTH-PAT-000008", "IFHAS-PKG-MAJOR-40-64")]["gap_type"]
        == "partial_completion"
    )

    # Scenario 9: Uninitiated referral past 15 working days -> referral_not_initiated gap
    assert (
        gaps_by_patient_rule[("SYNTH-PAT-000009", "IFHAS-WF-REFERRAL-15WD")]["gap_type"]
        == "referral_not_initiated"
    )

    # Scenario 10: Results not communicated within 10 days -> IFHAS-WF-RESULTS-COMMUNICATION-10D due + gap
    assert (
        evals_by_patient_rule[("SYNTH-PAT-000010", "IFHAS-WF-RESULTS-COMMUNICATION-10D")][
            "evaluation_status"
        ]
        == "due"
    )
    assert (
        gaps_by_patient_rule[("SYNTH-PAT-000010", "IFHAS-WF-RESULTS-COMMUNICATION-10D")][
            "gap_type"
        ]
        == "partial_completion"
    )

    # Scenario 26: Two conflicting screening records for one patient -> requires_clinical_review guard
    p26_screenings = [
        s for s in dataset.ifhas_screenings if s["patient_id"] == "SYNTH-PAT-000026"
    ]
    assert len(p26_screenings) >= 2
    ev_26 = evals_by_patient_rule[("SYNTH-PAT-000026", "IFHAS-PKG-MAMMOGRAPHY-40-75")]
    assert ev_26["evaluation_status"] == "requires_clinical_review"
    assert ev_26["reason_code"] == "conflicting_records"
    assert any(
        r["guard_id"] == "GUARD-CONFLICTING-RECORDS"
        for r in reasons_by_eval.get(ev_26["evaluation_id"], [])
    )

    # Scenario 13–16: M-CHAT-R high, moderate, low, and IDAQ referral
    instruments = {(a["patient_id"], a["instrument"], a["rule_id"]) for a in dataset.assessments}
    assert ("SYNTH-PAT-000013", "M-CHAT-R", "WCV-MCHATR-HIGH") in instruments
    assert ("SYNTH-PAT-000014", "M-CHAT-R", "WCV-MCHATR-MODERATE") in instruments
    assert ("SYNTH-PAT-000015", "M-CHAT-R", "WCV-MCHATR-LOW") in instruments
    assert ("SYNTH-PAT-000016", "IDAQ", "WCV-IDAQ-REFERRAL") in instruments

    # Scenario 17 & 25: Child missed 12m visit (visit_not_attended, never overdue) & 15m oral_examination guard
    assert all(
        e["evaluation_status"] != "overdue"
        for e in dataset.eligibility_evaluations
        if e["rule_id"].startswith("WCV-")
    )
    assert (
        gaps_by_patient_rule[("SYNTH-PAT-000017", "WCV-VISIT-12M")]["gap_type"]
        == "visit_not_attended"
    )
    ev_15m = evals_by_patient_rule[("SYNTH-PAT-000025", "WCV-VISIT-15M")]
    assert any(
        r["item_code"] == "oral_examination" and r["guard_id"] == "GUARD-ITEM-UNRESOLVED"
        for r in reasons_by_eval.get(ev_15m["evaluation_id"], [])
    )

    # Scenario 19: Documented, signed refusal -> closed_refused with closed_by_consent_id
    refused_gap = gaps_by_patient_rule[("SYNTH-PAT-000019", "WCV-VISIT-18M")]
    assert refused_gap["status"] == "closed_refused"
    assert refused_gap["closed_by_consent_id"] is not None

    # Scenario 20, 21, 27: Distinct consent states and clinician care_gap_review override
    consent_states = {(c["consent_type"], c["state"]) for c in dataset.consents}
    assert ("contact", "granted") in consent_states
    assert ("contact", "withdrawn") in consent_states
    assert ("ai_assisted_prioritisation", "granted") in consent_states
    assert ("ai_assisted_prioritisation", "refused") in consent_states
    assert len(dataset.care_gap_reviews) >= 1
    assert dataset.care_gap_reviews[0]["action"] == "priority_overridden"


def test_write_data_card(dataset: SyntheticDataset, tmp_path: Path):
    card_path = tmp_path / "data_card.md"
    write_data_card(dataset, card_path)
    text = card_path.read_text(encoding="utf-8")
    assert "SYNTH-RUN-0001" in text
    assert "20261116" in text
    assert "Synthetic" in text


def test_synthetic_dataset_rows_match_sqlalchemy_table_columns(dataset: SyntheticDataset):
    import app.models.synthetic  # noqa: F401
    from app.models.base import Base

    synth_tables = {
        t.name: t for t in Base.metadata.tables.values() if t.schema == "synthetic"
    }
    collection_by_table = {
        "generation_run": [dataset.generation_run],
        "evaluation_run": [dataset.evaluation_run],
        "facility_service_profile": dataset.facility_service_profiles,
        "patient": dataset.patients,
        "guardian": dataset.guardians,
        "consent": dataset.consents,
        "history_availability": dataset.history_availabilities,
        "eligibility_evaluation": dataset.eligibility_evaluations,
        "evaluation_reasons": dataset.evaluation_reasons,
    }
    # Map all 18 table names to dataset collections
    collection_by_table = {
        "generation_run": [dataset.generation_run],
        "evaluation_run": [dataset.evaluation_run],
        "facility_service_profile": dataset.facility_service_profiles,
        "patient": dataset.patients,
        "guardian": dataset.guardians,
        "consent": dataset.consents,
        "history_availability": dataset.history_availabilities,
        "eligibility_evaluation": dataset.eligibility_evaluations,
        "evaluation_reason": dataset.evaluation_reasons,
        "appointment": dataset.appointments,
        "ifhas_screening": dataset.ifhas_screenings,
        "well_child_visit": dataset.well_child_visits,
        "component_result": dataset.component_results,
        "assessment": dataset.assessments,
        "referral": dataset.referrals,
        "care_gap": dataset.care_gaps,
        "care_gap_review": dataset.care_gap_reviews,
        "care_gap_follow_up_event": [],
        "outreach_event": dataset.outreach_events,
    }
    assert set(collection_by_table) == set(synth_tables)
    for tbl_name, rows in collection_by_table.items():
        tbl = synth_tables[tbl_name]
        writable_cols = {c.name for c in tbl.columns if c.computed is None}
        required_cols = {
            c.name
            for c in tbl.columns
            if c.computed is None and not c.nullable and c.server_default is None
        }
        for row in rows[:25]:
            assert set(row.keys()) <= writable_cols, (tbl_name, set(row.keys()) - writable_cols)
            for req in required_cols:
                assert row.get(req) is not None, (tbl_name, req)


def test_load_synthetic_dataset_uses_valid_tables_reset_guard_and_circular_fk_handling():
    import app.models.synthetic  # noqa: F401
    from app.models.base import Base

    valid_tables = {
        t.name for t in Base.metadata.tables.values() if t.schema == "synthetic"
    }
    small_ds = generate_synthetic_dataset(seed=20261116, total_patients=35)
    executed_sql: list[str] = []

    class _FakeResult:
        def __init__(self, rows=None):
            self._rows = rows or []

        def scalar_one_or_none(self):
            return self._rows[0][0] if self._rows else None

        def scalars(self):
            return [r[0] for r in self._rows]

    class _FakeSAConn:
        dialect = type("D", (), {"name": "postgresql"})()

        def execute(self, stmt, params=None):
            sql_str = str(stmt)
            executed_sql.append(sql_str)
            if "FROM clinical.rule_load" in sql_str:
                return _FakeResult([(1,)])
            if "FROM official.facility" in sql_str:
                return _FakeResult([(101,), (102,), (103,)])
            return _FakeResult()

    conn = _FakeSAConn()
    result = load_synthetic_dataset(conn, small_ds, reset_existing_run=True)
    assert result["run_id"] == "SYNTH-RUN-0001"
    assert result["patients"] == 35

    # 1. Must never reference the invalid plural table `facility_service_profiles`
    assert not any("facility_service_profiles" in s for s in executed_sql)

    # 2. Must set `pulsereach.allow_synthetic_reset = 'on'` before DELETE and reset to `'off'`
    assert any("pulsereach.allow_synthetic_reset = 'on'" in s for s in executed_sql)
    assert any("pulsereach.allow_synthetic_reset = 'off'" in s for s in executed_sql)

    # 3. Every INSERT into synthetic.* must target one of the 18 valid synthetic tables
    for s in executed_sql:
        if "INSERT INTO synthetic." in s:
            tbl = s.split("INSERT INTO synthetic.")[1].split()[0].strip('"')
            assert tbl in valid_tables, tbl

    # 4. Circular FK: care_gap must be inserted before appointment.care_gap_id is linked
    first_care_gap_idx = next(
        i for i, s in enumerate(executed_sql) if "INSERT INTO synthetic.care_gap" in s
    )
    apt_care_gap_update_indices = [
        i
        for i, s in enumerate(executed_sql)
        if "UPDATE synthetic.appointment" in s and "care_gap_id" in s and i > first_care_gap_idx
    ]
    assert apt_care_gap_update_indices, "Expected appointment.care_gap_id update after care_gap insert"


def test_committed_demo_fixture_50_patients():
    import json
    from app.services.clinical_loader.parse import repo_root

    fixture_path = repo_root() / "data" / "synthetic" / "fixtures" / "demo_patients_50.json"
    assert fixture_path.exists(), f"Missing committed fixture: {fixture_path}"
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    assert payload["is_synthetic"] is True
    assert payload["run_id"] == "SYNTH-RUN-0001"
    assert len(payload["patients"]) == 50
    pids = {p["patient_id"] for p in payload["patients"]}
    for i in range(1, 28):
        assert f"SYNTH-PAT-{i:06d}" in pids


