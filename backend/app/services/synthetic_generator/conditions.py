"""Deterministic synthetic condition (problem-list) records with BE-33 demonstration scenarios.

Runs after the main generator on its own `random.Random` stream, so every pre-existing synthetic
record (patients, evaluations, care gaps, ...) is unchanged except the documented scenario 7
patients whose `district_label` is cleared. Nothing here is calibrated to real Abu Dhabi
prevalence; rates are illustrative and the records are labelled synthetic.

Scenarios (anchored to `reference_date` R and the default 14-day reporting delay, so the
complete-through date is T = R - 14; offsets below are days before T):

- S1 `BE33-S1` Mussafah, type 2 diabetes: 10 new diagnoses in the latest 90 days, 1 in the
  previous 90 days (recorded increase).
- S2 `BE33-S2` Khalifa City, hypertension: 4 new diagnoses in each 90-day window for two years
  (stable).
- S3 `BE33-S3` Al Bateen (region 1), hypertension: 2 in the latest 90 days, 9 in the previous
  90 days (recorded decrease).
- S4 high preventive-care gaps and S5 limited facility coverage are not generated: they come
  from the real evaluation-engine care gaps and the published SDI facility register.
- S6 `BE33-S6` Al Jimi: the record feed only starts 50 days before R (insufficient history).
- S7 missing geography: patients with `idx >= 60 and idx % 41 == 0` have no local area.

A scenario is skipped (background records are generated instead) when its area does not have
enough eligible people, e.g. for small `total_patients` values.

The backend computes every trend from these records; no expected result is stored anywhere.
"""

from __future__ import annotations

import random
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

CONDITION_CODES = ("diabetes_type_2", "hypertension", "dyslipidaemia", "asthma")
SOURCE_SYSTEMS = ("synthetic_ehr_problem_list", "synthetic_claims_diagnosis")
SCENARIO_REPORTING_DELAY_DAYS = 14
HISTORY_DAYS = 5 * 365
FEED_START_DAYS_S6 = 50
MISSING_GEO_MIN_IDX, MISSING_GEO_MODULUS = 60, 41

# (district, condition, tag, offsets before T of each new diagnosis)
_SCENARIOS: tuple[tuple[str, str, str, tuple[int, ...]], ...] = (
    ("Mussafah", "diabetes_type_2", "BE33-S1-increasing-diabetes",
     (12, 18, 25, 31, 38, 46, 53, 61, 68, 77, 130, 260, 420, 610, 900)),
    ("Khalifa City", "hypertension", "BE33-S2-stable-hypertension",
     tuple(90 * k + d for k in range(8) for d in (12, 34, 56, 78))),
    ("Al Bateen", "hypertension", "BE33-S3-decreasing-hypertension",
     (30, 70, 95, 104, 113, 122, 131, 140, 149, 158, 167, 300, 520, 800, 1100)),
)
_S6_DISTRICT, _S6_TAG = "Al Jimi", "BE33-S6-recent-history"

# Illustrative background probabilities per eligible person (not real prevalence).
_BACKGROUND_P = {"diabetes_type_2": 0.08, "hypertension": 0.12, "dyslipidaemia": 0.10, "asthma": 0.06}
_P_UNDATED, _P_DUPLICATE, _P_ENTERED_IN_ERROR, _P_ASTHMA_RESOLVED = 0.03, 0.06, 0.01, 0.2
_MAX_RECORDING_LAG_DAYS = 10
_ADULT_YEARS, _ASTHMA_MIN_AGE_DAYS = 18, 2 * 365


def _age_years(dob: date | None, on: date) -> int | None:
    if dob is None:
        return None
    return on.year - dob.year - ((on.month, on.day) < (dob.month, dob.day))


def _idx(patient_id: str) -> int:
    return int(patient_id.rsplit("-", 1)[-1])


def generate_condition_records(
    patients: list[dict[str, Any]], *, reference_date: date, run_id: str, seed: int
) -> list[dict[str, Any]]:
    """Return condition records for `patients` (and clear scenario-7 local areas in place)."""
    rng = random.Random(f"{seed}:be33-conditions")
    cap = datetime.combine(reference_date, time(8, 0), timezone.utc)
    t_end = reference_date - timedelta(days=SCENARIO_REPORTING_DELAY_DAYS)
    rows: list[dict[str, Any]] = []

    def recorded(diag: date | None, span: int = HISTORY_DAYS) -> datetime:
        base = diag or reference_date - timedelta(days=rng.randint(1, span))
        return min(datetime.combine(base + timedelta(days=rng.randint(0, _MAX_RECORDING_LAG_DAYS)),
                                    time(10, 0), timezone.utc), cap)

    def add(p: dict[str, Any], code: str, diag: date | None, *, tag: str | None = None,
            status: str = "active", resolved: date | None = None, rec_at: datetime | None = None) -> None:
        rows.append({
            "run_id": run_id, "patient_id": p["patient_id"], "is_synthetic": True,
            "condition_code": code, "diagnosis_date": diag,
            "recorded_at": rec_at or recorded(diag), "status": status, "resolved_date": resolved,
            "source_system": SOURCE_SYSTEMS[0], "scenario_tag": tag,
        })

    def eligible(p: dict[str, Any], code: str, on: date) -> bool:
        if p.get("date_of_death") is not None and p["date_of_death"] <= on:
            return False
        dob = p["date_of_birth"]
        if code == "asthma":
            return dob is None or (on - dob).days >= _ASTHMA_MIN_AGE_DAYS
        age = _age_years(dob, on)
        return age is not None and age >= _ADULT_YEARS

    ordered = sorted(patients, key=lambda p: p["patient_id"])
    scenario_cells = {(d, c) for d, c, _, _ in _SCENARIOS}

    # Scenario 7 first: these people keep their region but have no recorded local area.
    for p in ordered:
        i = _idx(p["patient_id"])
        if i >= MISSING_GEO_MIN_IDX and i % MISSING_GEO_MODULUS == 0:
            p["district_label"] = None

    for district, code, tag, offsets in _SCENARIOS:
        dates = sorted((t_end - timedelta(days=o) for o in offsets), reverse=True)
        pool = [p for p in ordered if p["district_label"] == district and p["region_id"] == 1
                and eligible(p, code, min(dates))]
        if len(pool) < len(dates):  # small generated cohorts: the scenario is not generated
            scenario_cells.discard((district, code))
            continue
        for p, diag in zip(rng.sample(pool, len(dates)), dates):
            add(p, code, diag, tag=tag)

    for p in ordered:
        district = p["district_label"]
        for code in CONDITION_CODES:
            if (district, code) in scenario_cells or not eligible(p, code, reference_date):
                continue
            p_cond = _BACKGROUND_P[code] * (1.8 if code == "hypertension"
                                            and (_age_years(p["date_of_birth"], reference_date) or 0) >= 50 else 1)
            if rng.random() >= p_cond:
                continue
            recent_feed = district == _S6_DISTRICT
            span = FEED_START_DAYS_S6 if recent_feed else HISTORY_DAYS
            diag = reference_date - timedelta(days=rng.randint(1, span))
            dob = p["date_of_birth"]
            if dob is not None and diag <= dob + timedelta(days=_ASTHMA_MIN_AGE_DAYS if code == "asthma"
                                                            else 365 * _ADULT_YEARS):
                continue
            tag = _S6_TAG if recent_feed else None
            if rng.random() < _P_UNDATED:
                add(p, code, None, tag=tag, rec_at=recorded(None, span))
                continue
            resolved = None
            if code == "asthma" and rng.random() < _P_ASTHMA_RESOLVED:
                candidate = diag + timedelta(days=rng.randint(365, 3 * 365))
                resolved = candidate if candidate < reference_date else None
            add(p, code, diag, tag=tag, status="resolved" if resolved else "active", resolved=resolved)
            if rng.random() < _P_DUPLICATE:  # same condition entered again from a second source
                dup_diag = min(diag + timedelta(days=rng.randint(0, 30)), reference_date - timedelta(days=1))
                dup_resolved = resolved if resolved and resolved >= dup_diag else None
                add(p, code, dup_diag, tag=tag, status="resolved" if dup_resolved else "active",
                    resolved=dup_resolved)
                rows[-1]["source_system"] = SOURCE_SYSTEMS[1]
            if rng.random() < _P_ENTERED_IN_ERROR:
                add(p, code, diag, tag=tag, status="entered_in_error")

    rows.sort(key=lambda r: (r["patient_id"], r["condition_code"], r["diagnosis_date"] or date.min,
                             r["recorded_at"], r["status"]))
    for n, r in enumerate(rows, start=1):
        r["condition_record_id"] = f"SYNTH-CND-{n:06d}"
    return rows
