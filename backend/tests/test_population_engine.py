"""BE-33 engine: aggregation, trends, hotspots, privacy, alert de-duplication (no HTTP)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.services.population import facts as facts_mod
from app.services.population.alerts import InvalidTransition, sync_alerts, transition
from app.services.population.config import (
    DEFAULT_THRESHOLDS,
    HotspotThresholds,
    PopulationThresholds,
    TrendThresholds,
)
from app.services.population.engine import build_snapshot, classify_hotspot, classify_trend
from app.services.population.facts import (
    ConditionRow,
    CoverageRow,
    FacilityRow,
    MemoryFactsProvider,
    PopulationFacts,
    PopulationRow,
)
from app.services.population.privacy import Suppressor
from app.services.population.store import population_session, reset_population_store
from app.services.synthetic_generator.conditions import generate_condition_records

REF = date(2026, 11, 16)
NOW = datetime(2026, 11, 20, 6, 0, tzinfo=timezone.utc)
REGIONS = [(1, "AD", "Abu Dhabi Region", None), (2, "AIN", "Al Ain Region", None)]
TREND = TrendThresholds()
NO_DELAY = PopulationThresholds(reporting_delay_days=0)


def _facts(population, conditions=(), coverage_start=date(2020, 1, 1), latest=None) -> PopulationFacts:
    cov = {(r.region_id, r.local_label) for r in population}
    return PopulationFacts(
        organization_key="*", source_run_id="SYNTH-RUN-0001", reference_date=REF, latest_data_at=latest,
        regions=REGIONS, population=list(population), conditions=list(conditions),
        coverage=[CoverageRow(rid, lab, datetime.combine(coverage_start, datetime.min.time(), timezone.utc),
                              datetime(2026, 11, 1, tzinfo=timezone.utc), 1, 0) for rid, lab in cov],
    )


def _cond(onset, *, n=1, label="Alpha", region=1, code="diabetes_type_2", resolved=None, first=None, dups=0,
          sex="female", age="adult"):
    return ConditionRow(region, label, sex, age, code, onset, resolved, first or onset or REF, n, dups)


def _snap(f, th=NO_DELAY):
    return build_snapshot(f, th, config_version=0, generated_at=NOW)


def _block(s, area, period="90d", cohort="all", code="diabetes_type_2"):
    return s["areas"][area]["conditions"][code]["periods"][cohort][period]


ALPHA, BETA = "AE-AZ-AD-L-alpha", "AE-AZ-AD-L-beta"
POP = [PopulationRow(1, "Alpha", "female", "adult", 60), PopulationRow(1, "Alpha", "male", "adult", 40),
       PopulationRow(1, "Beta", "female", "adult", 30), PopulationRow(1, None, "male", "adult", 7),
       PopulationRow(2, "Gamma", "female", "child", 25)]


# --- trend classification -------------------------------------------------------------------


@pytest.mark.parametrize("cur,prev,expected", [
    (10, 4, "INCREASING"), (4, 10, "DECREASING"), (10, 9, "STABLE"), (5, 0, "INCREASING"), (1, 1, "INSUFFICIENT_DATA"),
])
def test_trend_directions(cur, prev, expected):
    out = classify_trend(cur, prev, population=100, history_complete=True, completeness=1.0, cfg=TREND)
    assert out["direction"] == expected
    assert out["absolute_change"] == cur - prev


def test_zero_previous_period_has_no_percentage():
    out = classify_trend(5, 0, population=100, history_complete=True, completeness=1.0, cfg=TREND)
    assert out["percentage_change"] is None and "previous_period_zero" in out["reason_codes"]


@pytest.mark.parametrize("kw,reason", [
    ({"population": 5}, "population_below_minimum"),
    ({"history_complete": False}, "history_incomplete"),
    ({"completeness": 0.5}, "completeness_below_minimum"),
])
def test_trend_insufficient_data(kw, reason):
    args = {"population": 100, "history_complete": True, "completeness": 1.0} | kw
    out = classify_trend(10, 2, cfg=TREND, **args)
    assert out["direction"] == "INSUFFICIENT_DATA" and reason in out["reason_codes"]


def test_increase_is_never_called_an_outbreak():
    hs = classify_hotspot(_metric(20, 2), HotspotThresholds())
    assert hs["method"] == "threshold_rules" and hs["statistical_significance"] == "not_assessed"
    assert "outbreak" not in str(hs).lower()


# --- hotspots -------------------------------------------------------------------------------


def _metric(cur, prev, *, population=100, history=True, completeness=1.0):
    return {"new_cases": cur, "previous_new_cases": prev, "population": population, "prevalence": 0.1,
            "completeness": completeness, "history_complete": history,
            "trend": {"percentage_change": (cur - prev) / prev if prev else None}}


@pytest.mark.parametrize("cur,prev,expected", [
    (6, 2, "WATCH"),       # +4, +200% meets base only (tier MODERATE needs +5)
    (9, 3, "MODERATE"),    # +6, +200%
    (12, 3, "HIGH"),       # +9, +300%
    (20, 4, "CRITICAL"),   # +16, +400%
    (4, 0, "NO_ALERT"),    # below min_cases 5
    (6, 4, "NO_ALERT"),    # +2 below min_absolute_increase 3
    (30, 26, "NO_ALERT"),  # +4 but +15% below min_percentage_increase 25%
    (7, 0, "MODERATE"),    # previous zero: percentage rule undefined, absolute rules apply
])
def test_hotspot_threshold_rules(cur, prev, expected):
    assert classify_hotspot(_metric(cur, prev), HotspotThresholds())["classification"] == expected


def test_hotspot_insufficient_data_and_min_population():
    cfg = HotspotThresholds()
    assert classify_hotspot(_metric(20, 2, population=10), cfg)["classification"] == "INSUFFICIENT_DATA"
    assert classify_hotspot(_metric(20, 2, history=False), cfg)["classification"] == "INSUFFICIENT_DATA"
    assert classify_hotspot(_metric(20, 2, completeness=0.5), cfg)["classification"] == "INSUFFICIENT_DATA"


def test_hotspot_thresholds_are_configurable_and_echoed():
    strict = HotspotThresholds(min_cases=25)
    hs = classify_hotspot(_metric(20, 2), strict)
    assert hs["classification"] == "NO_ALERT" and "below_min_cases" in hs["reason_codes"]
    assert hs["thresholds"]["min_cases"] == 25
    with pytest.raises(ValueError):
        HotspotThresholds(tiers=[{"severity": "HIGH", "min_absolute_increase": 1, "min_percentage_increase": 0}])


# --- aggregation ----------------------------------------------------------------------------


def test_counts_windows_and_prevalence():
    end = REF
    rows = [_cond(end - timedelta(days=10), n=3), _cond(end - timedelta(days=100), n=2),
            _cond(date(2022, 1, 1), n=4), _cond(date(2022, 1, 1), n=1, resolved=end - timedelta(days=200))]
    b = _block(_snap(_facts(POP, rows)), ALPHA)
    assert (b["new_cases"], b["previous_new_cases"]) == (3, 2)
    assert b["patients_with_condition"] == 9 and b["existing_patients"] == 6  # resolved one excluded
    assert b["population"] == 100 and b["prevalence"] == 0.09
    assert b["prevalence_status"] == "available"


def test_duplicates_are_reported_not_double_counted():
    b = _block(_snap(_facts(POP, [_cond(REF - timedelta(days=5), n=2, dups=3)])), ALPHA)
    assert b["new_cases"] == 2 and b["duplicate_records"] == 3


def test_undated_diagnoses_count_as_recorded_but_not_new():
    rows = [_cond(None, n=2, first=REF - timedelta(days=20)), _cond(REF - timedelta(days=3), n=8)]
    b = _block(_snap(_facts(POP, rows)), ALPHA, period="30d")
    assert b["new_cases"] == 8 and b["patients_with_condition"] == 10 and b["undated_patients"] == 2
    assert b["completeness"] == 0.8


def test_missing_denominator_makes_prevalence_unavailable():
    pop = [PopulationRow(1, "Alpha", None, None, 50)]
    s = _snap(_facts(pop, [_cond(REF - timedelta(days=5), sex=None, age=None)]))
    b = _block(s, ALPHA, cohort="children")
    assert b["population"] == 0 and b["prevalence"] is None and b["prevalence_status"] == "unavailable_no_denominator"
    f = _facts(pop)
    f.facilities = [FacilityRow(1, "AL WAHDA", "Al Wahda", "clinics", 3, 3, 24.4, 24.5, 54.3, 54.4)]
    city = _snap(f)["areas"]["AE-AZ-AD-C-al-wahda"]
    assert city["population"] is None and "conditions" not in city  # facility-only area: no denominator
    assert city["facilities"]["care_facilities"] == 3


def test_geographic_grouping_rolls_up_and_reports_unassigned():
    rows = [_cond(REF - timedelta(days=5), n=4), _cond(REF - timedelta(days=5), n=2, label="Beta"),
            _cond(REF - timedelta(days=5), n=1, label=None, sex="male")]
    s = _snap(_facts(POP, rows))
    assert _block(s, "AE-AZ-AD")["new_cases"] == 7 and _block(s, "AE")["new_cases"] == 7
    assert s["areas"]["AE-AZ-AD"]["population"]["all"] == 137
    assert s["areas"]["AE-AZ-AD"]["unassigned_local_area_population"] == 7
    assert s["areas"]["AE-AZ-AD"]["data_quality"]["geographic_completeness"] == round(130 / 137, 6)
    assert _block(s, "AE-AZ-AIN")["new_cases"] == 0
    assert s["areas"]["AE-AZ-AD"]["area"]["boundary"] is None  # never fabricated


def test_reporting_delay_shifts_the_complete_through_date():
    s = _snap(_facts(POP, [_cond(REF - timedelta(days=3), n=5)]), DEFAULT_THRESHOLDS)
    assert s["complete_through"] == (REF - timedelta(days=14)).isoformat()
    assert _block(s, ALPHA, period="7d")["new_cases"] == 0  # still within the reporting delay


def test_incomplete_history_gives_insufficient_data():
    rows = [_cond(REF - timedelta(days=10), n=9)]
    s = _snap(_facts(POP, rows, coverage_start=REF - timedelta(days=40)))
    assert _block(s, ALPHA, period="30d")["trend"]["direction"] == "INSUFFICIENT_DATA"
    assert _block(s, ALPHA, period="7d")["history_complete"] is True


def test_cohorts():
    rows = [_cond(REF - timedelta(days=5), n=5), _cond(REF - timedelta(days=5), n=3, sex="male")]
    s = _snap(_facts(POP, rows))
    assert _block(s, ALPHA, cohort="female")["new_cases"] == 5 and _block(s, ALPHA, cohort="male")["new_cases"] == 3
    assert s["areas"][ALPHA]["population"]["female"] == 60


# --- memory facts provider (de-duplication definitions) ----------------------------------------


def test_memory_provider_deduplicates_and_excludes_entered_in_error(monkeypatch):
    rec = lambda d, st="active", day=1: {  # noqa: E731
        "patient_id": "SYNTH-PAT-000001", "condition_code": "hypertension", "diagnosis_date": d, "status": st,
        "resolved_date": None, "recorded_at": datetime(2026, 1, day, tzinfo=timezone.utc)}
    ds = SimpleNamespace(
        patients=[{"patient_id": "SYNTH-PAT-000001", "region_id": 1, "district_label": "Alpha", "sex": "female",
                   "date_of_birth": date(1970, 1, 1), "date_of_death": None},
                  {"patient_id": "SYNTH-PAT-000002", "region_id": 1, "district_label": "Alpha", "sex": "male",
                   "date_of_birth": date(1960, 1, 1), "date_of_death": date(2025, 1, 1)}],
        condition_records=[rec(date(2025, 5, 1)), rec(date(2025, 3, 1), day=2), rec(date(2024, 1, 1), "entered_in_error", 3),
                           {**rec(date(2025, 1, 1)), "patient_id": "SYNTH-PAT-000002"}],
        evaluation_run={"reference_date": REF, "evaluation_run_id": "E"}, generation_run={"run_id": "R"},
        eligibility_evaluations=[], care_gaps=[], ifhas_screenings=[], well_child_visits=[],
    )
    import app.repositories.read_repo as rr

    monkeypatch.setattr(rr, "get_cached_dataset", lambda: ds)
    monkeypatch.setattr(rr, "get_cached_facilities", lambda: [])
    f = MemoryFactsProvider().fetch(facts_mod.ALL_ORGANIZATIONS)
    assert [(c.onset_date, c.n, c.duplicate_records) for c in f.conditions] == [(date(2025, 3, 1), 1, 1)]
    assert sum(r.n for r in f.population) == 1  # deceased person excluded from the denominator
    assert f.coverage[0].entered_in_error == 1 and f.coverage[0].records == 2


# --- seeded demonstration scenarios -----------------------------------------------------------


@pytest.fixture(scope="module")
def seeded():
    from app.repositories.read_repo import get_cached_dataset

    ds = get_cached_dataset()
    return ds, _snap_ds()


def _snap_ds():
    f = MemoryFactsProvider().fetch(facts_mod.ALL_ORGANIZATIONS)
    return build_snapshot(f, DEFAULT_THRESHOLDS, config_version=0, generated_at=NOW)


def test_condition_records_are_synthetic_deterministic_and_coherent(seeded):
    ds, _ = seeded
    pids = {p["patient_id"] for p in ds.patients}
    assert ds.condition_records and all(r["condition_record_id"].startswith("SYNTH-CND-") for r in ds.condition_records)
    for r in ds.condition_records:
        assert r["patient_id"] in pids and r["is_synthetic"]
        assert r["diagnosis_date"] is None or r["diagnosis_date"] <= r["recorded_at"].date()
        assert (r["status"] == "resolved") == (r["resolved_date"] is not None)
    def gen():
        return generate_condition_records([dict(p) for p in ds.patients], reference_date=REF,
                                          run_id="SYNTH-RUN-0001", seed=20261116)

    assert gen() == gen()


@pytest.mark.parametrize("area,code,expected", [
    ("AE-AZ-AD-L-mussafah", "diabetes_type_2", "INCREASING"),
    ("AE-AZ-AD-L-khalifa-city", "hypertension", "STABLE"),
    ("AE-AZ-AD-L-al-bateen", "hypertension", "DECREASING"),
])
def test_seeded_trend_scenarios_are_computed_from_records(seeded, area, code, expected):
    _, s = seeded
    assert _block(s, area, code=code)["trend"]["direction"] == expected


def test_seeded_hotspot_insufficient_history_small_areas_and_missing_geo(seeded):
    _, s = seeded
    assert s["areas"]["AE-AZ-AD-L-mussafah"]["conditions"]["diabetes_type_2"]["hotspot"]["classification"] in (
        "WATCH", "MODERATE", "HIGH", "CRITICAL")
    jimi = _block(s, "AE-AZ-AIN-L-al-jimi", period="30d", code="hypertension")
    assert jimi["history_complete"] is False and jimi["trend"]["direction"] == "INSUFFICIENT_DATA"
    assert s["areas"]["AE-AZ-DHF-L-liwa"]["data_quality"]["small_population"] is True
    assert sum(s["areas"][d]["unassigned_local_area_population"] for d in ("AE-AZ-AD", "AE-AZ-AIN", "AE-AZ-DHF")) > 0


def test_seeded_care_and_facility_signals_come_from_real_inputs(seeded):
    _, s = seeded
    cats = {(c["category"], c["area_id"]) for c in s["alert_candidates"]}
    assert ("facility_coverage_insufficient", "AE-AZ-AIN-L-zakhir") in cats  # 9 published care facilities
    assert any(c == "preventive_coverage_low" for c, _ in cats)
    assert s["areas"]["AE-AZ-DHF-L-ruwais"]["facilities"]["association"]["status"] == "no_matching_facility_label"
    assert s["areas"]["AE-AZ-DHF-L-ruwais"]["facilities"]["care_facilities"] is None  # unknown, never zero
    gap_trend = s["areas"]["AE"]["care"]["all"]["periods"]["90d"]["care_gap_trend"]
    assert gap_trend["direction"] == "INSUFFICIENT_DATA"  # all gaps come from one evaluation date


def test_snapshot_contains_no_patient_identifiers(seeded):
    _, s = seeded
    text = str(s)
    assert "SYNTH-PAT-" not in text and "SYNTH-EID-" not in text and "(synthetic)" not in text


# --- privacy --------------------------------------------------------------------------------


def test_primary_cohort_and_complementary_suppression():
    rows = [_cond(REF - timedelta(days=5), n=3), _cond(REF - timedelta(days=5), n=9, label="Beta"),
            _cond(REF - timedelta(days=5), n=6, label="Beta", sex="male")]
    s = _snap(_facts(POP, rows))
    sup = Suppressor(s, 5)
    path = ("conditions", "diabetes_type_2", "periods", "all", "90d", "new_cases")
    hidden = sup.hidden(path)
    assert ALPHA in hidden  # 3 < 5
    assert BETA in hidden  # AD total 18 - Beta would reveal Alpha (the remainder is unknown but zero here)
    assert "AE-AZ-AD" not in hidden
    female = ("conditions", "diabetes_type_2", "periods", "female", "90d", "new_cases")
    assert BETA in sup.hidden(female)  # complementary cell for the small Alpha female count
    small_pop = _snap(_facts([PopulationRow(1, "Alpha", "female", "adult", 3), *POP[2:]]))
    assert ALPHA in Suppressor(small_pop, 5).small_areas


# --- alerts ---------------------------------------------------------------------------------


@pytest.fixture
def store():
    reset_population_store()
    yield
    reset_population_store()


def _cand(severity="WATCH", key="case_increase|A|diabetes_type_2|90d", **metrics):
    return {"dedup_key": key, "category": "case_increase", "area_id": "A", "condition_code": "diabetes_type_2",
            "severity": severity, "metrics": {"new_cases": 9, **metrics}, "thresholds": {"min_cases": 5},
            "period_key": "90d", "period_start": "2026-08-05", "period_end": "2026-11-02",
            "title_key": "population.alert.case_increase.title", "explanation_key": "population.alert.case_increase.explanation",
            "message_params": {}, "title": "t", "explanation": "e"}


def test_alerts_are_created_updated_cleared_and_not_duplicated(store):
    from app.models.population import PopulationAlert, PopulationAlertEvent
    from sqlalchemy import select

    with population_session() as s:
        assert sync_alerts(s, "org", "r1", [_cand()], NOW, None)["created"] == 1
    with population_session() as s:
        out = sync_alerts(s, "org", "r2", [_cand()], NOW + timedelta(minutes=1), None)
        assert out["created"] == 0 and out["unchanged"] == 1
    with population_session() as s:
        assert sync_alerts(s, "org", "r3", [_cand("HIGH", new_cases=14)], NOW, None)["updated"] == 1
        sync_alerts(s, "other-org", "r3", [_cand()], NOW, None)  # isolated per organization
    with population_session() as s:
        assert sync_alerts(s, "org", "r4", [], NOW, None)["cleared"] == 1
        alerts = list(s.scalars(select(PopulationAlert).where(PopulationAlert.organization_key == "org")))
        assert len(alerts) == 1 and alerts[0].occurrence_count == 3 and alerts[0].severity == "HIGH"
        assert alerts[0].condition_active is False and alerts[0].status == "NEW"
        events = [e.event_type for e in s.scalars(select(PopulationAlertEvent).where(
            PopulationAlertEvent.alert_id == alerts[0].alert_id).order_by(PopulationAlertEvent.occurred_at))]
        assert events.count("created") == 1 and "updated" in events and "condition_cleared" in events


def test_closed_alert_is_not_recreated_while_condition_persists(store):
    from app.models.population import PopulationAlert
    from sqlalchemy import select

    with population_session() as s:
        sync_alerts(s, "org", "r1", [_cand()], NOW, None)
        a = s.scalar(select(PopulationAlert))
        transition(s, a, "DISMISSED", actor_user_id="u1", actor_role="POPULATION_HEALTH_MANAGER", note=None, at=NOW)
    with population_session() as s:
        assert sync_alerts(s, "org", "r2", [_cand()], NOW, None)["suppressed_after_close"] == 1
        assert sync_alerts(s, "org", "r3", [_cand("HIGH")], NOW, None)["created"] == 1  # escalation re-alerts
    with population_session() as s:
        sync_alerts(s, "org", "r4", [], NOW, None)
        # The HIGH alert is still open (only its condition cleared in r4): it recurs, no third alert.
        assert sync_alerts(s, "org", "r5", [_cand()], NOW, None)["recurred"] == 1
        assert len(list(s.scalars(select(PopulationAlert)))) == 2


def test_status_transitions(store):
    from app.models.population import PopulationAlert
    from sqlalchemy import select

    with population_session() as s:
        sync_alerts(s, "org", "r1", [_cand()], NOW, None)
        a = s.scalar(select(PopulationAlert))
        transition(s, a, "ACKNOWLEDGED", actor_user_id="u1", actor_role="X", note="seen", at=NOW)
        transition(s, a, "INVESTIGATING", actor_user_id="u2", actor_role="X", note=None, at=NOW)
        with pytest.raises(InvalidTransition):
            transition(s, a, "NEW", actor_user_id="u2", actor_role="X", note=None, at=NOW)
        transition(s, a, "RESOLVED", actor_user_id="u2", actor_role="X", note=None, at=NOW)
        assert (a.acknowledged_by, a.investigating_by, a.closed_by) == ("u1", "u2", "u2")
        with pytest.raises(InvalidTransition):
            transition(s, a, "DISMISSED", actor_user_id="u2", actor_role="X", note=None, at=NOW)
