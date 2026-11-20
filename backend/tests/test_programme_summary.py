"""Programme API alignment: programme-scoped `/patients` filters and
`GET /api/v1/programmes/{pathway}/summary` (RBAC, organization isolation, aggregate consistency,
small-cell suppression, missing evaluation history). Memory mode."""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.repositories.read_repo import get_cached_bundle, get_cached_index
from app.services.programmes import _partition, build_programme_summary
from identity_fixtures import client, users_mode, world  # noqa: F401

S = "/api/v1/programmes/{}/summary"
legacy = TestClient(app)  # conftest: AUTH_MODE=legacy for this client unless a test switches modes


def _rule_pathway() -> dict[str, str]:
    return {r["rule_id"]: r["pathway"] for r in get_cached_bundle().rules}


def _open_in(pid: str, pathway: str) -> int:
    rp = _rule_pathway()
    return sum(1 for g in get_cached_index().care_gaps_by_patient.get(pid, [])
               if g["status"] == "open" and rp[g["rule_id"]] == pathway)


def _members(pathway: str, pids=None) -> list[str]:
    idx = get_cached_index()
    return [p["patient_id"] for p in idx.dataset.patients
            if pathway in idx.history_by_patient.get(p["patient_id"], {}) and (pids is None or p["patient_id"] in pids)]


def _total(c: TestClient, qs: str, headers=None) -> int:
    r = c.get(f"/api/v1/patients?limit=1&{qs}", headers=headers or {})
    assert r.status_code == 200, r.text
    return r.json()["total"]


# --- /patients: open-gap and history filters follow the selected programme --------------------


@pytest.mark.parametrize("pathway", ["ifhas", "well_child"])
def test_patient_filters_are_programme_scoped(pathway):
    idx = get_cached_index()
    members = _members(pathway)
    with_gap = [pid for pid in members if _open_in(pid, pathway) > 0]
    assert _total(legacy, f"pathway={pathway}&has_open_care_gaps=true") == len(with_gap)
    assert _total(legacy, f"pathway={pathway}&has_open_care_gaps=false") == len(members) - len(with_gap)
    for h in ("available", "partial", "not_available"):
        expected = [pid for pid in members if idx.history_by_patient[pid][pathway] == h]
        assert _total(legacy, f"pathway={pathway}&history_status={h}") == len(expected)


def test_programme_scoping_differs_from_cross_programme_semantics():
    # People with a well-child history whose only open gaps are IFHAS gaps must not appear in a
    # well-child open-gap filter (they did before: the filter matched any programme).
    idx = get_cached_index()
    cross = [pid for pid in _members("well_child")
             if _open_in(pid, "well_child") == 0 and _open_in(pid, "ifhas") > 0]
    total_any = sum(1 for p in idx.dataset.patients if _open_in(p["patient_id"], "ifhas") + _open_in(p["patient_id"], "well_child"))
    assert _total(legacy, "has_open_care_gaps=true") == total_any  # no pathway: any programme (unchanged)
    scoped = legacy.get("/api/v1/patients?limit=200&pathway=well_child&has_open_care_gaps=true").json()["items"]
    assert not {p["patient_id"] for p in scoped} & set(cross)


# --- Summary: aggregate consistency ----------------------------------------------------------


@pytest.mark.parametrize("pathway", ["ifhas", "well_child"])
def test_summary_matches_programme_scoped_patient_queries(pathway):
    d = legacy.get(S.format(pathway)).json()
    assert d["patient_scope"] == "unrestricted"
    members = _members(pathway)
    assert d["members"] == len(members) == _total(legacy, f"pathway={pathway}")
    seg = {s["segment"]: s["people"] for s in d["segments"]}
    pub = lambda v, n: v is None or v == n  # noqa: E731 - suppressed cells are null, never wrong
    assert pub(seg["open_gap"], _total(legacy, f"pathway={pathway}&has_open_care_gaps=true"))
    for h in ("available", "partial", "not_available"):
        assert pub(seg[h], _total(legacy, f"pathway={pathway}&has_open_care_gaps=false&history_status={h}"))
        assert pub(d["history"][h], _total(legacy, f"pathway={pathway}&history_status={h}"))
    assert d["people_with_open_gap"] == seg["open_gap"]
    rp = _rule_pathway()
    gaps = [g for pid in members for g in get_cached_index().care_gaps_by_patient.get(pid, []) if rp[g["rule_id"]] == pathway]
    assert pub(d["care_gaps"]["total"], len(gaps))
    for status, n in d["care_gaps"].items():
        if status != "total":
            assert pub(n, sum(1 for g in gaps if g["status"] == status))
    # Eligibility comes from the dashboard semantics restricted to the members.
    dash = legacy.get("/api/v1/dashboard/summary").json()["pathway_breakdown"][pathway]
    assert pub(d["eligibility"]["due_or_upcoming_patients"], dash["due_or_upcoming_patients"])


def test_summary_filters_are_applied_server_side():
    d = legacy.get(S.format("ifhas") + "?region_id=2&sex=female").json()
    assert d["filters"] == {"region_id": 2, "sex": "female", "age_band": None}
    assert d["members"] == _total(legacy, "pathway=ifhas&region_id=2&sex=female")
    banded = legacy.get(S.format("ifhas") + "?age_band=adult_40_59").json()
    assert banded["members"] == _total(legacy, "pathway=ifhas&age_band=adult_40_59")
    assert legacy.get(S.format("dental")).status_code == 422


# --- Missing history: no manufactured trend ---------------------------------------------------


def test_trend_is_not_drawn_without_evaluation_history():
    t = legacy.get(S.format("ifhas")).json()["trend"]
    assert t["evaluation_runs"] == 1
    assert t["previous_period_observed"] is False
    assert t["previous_care_gaps_identified"] is None  # not observed — never 0
    assert t["previous_gaps_closed_completed"] is None
    assert t["care_gap_trend"]["direction"] == "INSUFFICIENT_DATA"
    assert t["care_gap_trend"]["reason_codes"] == ["evaluation_history_incomplete"]
    # Even the short windows (where the earliest gap record predates the previous window) stay
    # insufficient: the gap records come from a single evaluation run.
    for period in ("7d", "30d"):
        assert legacy.get(S.format("ifhas") + f"?period={period}").json()["trend"]["care_gap_trend"]["direction"] == "INSUFFICIENT_DATA"


def _summary(members, gaps, dates, k=5, period="90d"):
    return build_programme_summary(
        pathway="ifhas", members=members, gaps=gaps, eligibility={}, evaluation_dates=dates,
        evaluation_run_id="EVR", reference_date=date(2026, 11, 16), patient_scope="organization",
        filters={}, period=period, min_cell_size=k)


def test_trend_compares_periods_only_when_evaluations_cover_them():
    members = [(f"P{i}", "available") for i in range(40)]
    gaps = [(f"P{i}", "no_documented_screening", "open", date(2026, 10, 1), None) for i in range(20)]
    gaps += [(f"P{i}", "no_documented_screening", "closed_completed", date(2026, 6, 1), date(2026, 7, 1))
             for i in range(20, 26)]
    t = _summary(members, gaps, [date(2026, 5, 1), date(2026, 8, 1), date(2026, 11, 16)])["trend"]
    assert t["previous_period_observed"] is True
    assert (t["care_gaps_identified"], t["previous_care_gaps_identified"]) == (20, 6)
    assert t["previous_gaps_closed_completed"] == 6
    assert t["care_gap_trend"]["direction"] == "INCREASING"
    t = _summary(members, gaps, [date(2026, 8, 1), date(2026, 11, 16)])["trend"]
    assert t["previous_care_gaps_identified"] is None
    assert t["care_gap_trend"]["direction"] == "INSUFFICIENT_DATA"


# --- Privacy ----------------------------------------------------------------------------------


def test_small_member_sets_suppress_every_count():
    d = _summary([("P1", "available"), ("P2", "not_available")], [("P1", "no_documented_screening", "open", date(2026, 11, 16), None)], [date(2026, 11, 16)])
    assert d["members"] is None and d["suppressed"] == ["all"]
    assert all(s["people"] is None for s in d["segments"])
    assert set(d["history"].values()) == {None} and set(d["care_gaps"].values()) == {None}
    assert d["trend"]["care_gaps_identified"] is None


def test_partition_suppresses_a_complementary_cell():
    assert _partition({"a": 3, "b": 40, "c": 10}, 5, True) == {"a", "c"}
    assert _partition({"a": 3, "b": 40, "c": 10}, 5, False) == {"a"}
    assert _partition({"a": 0, "b": 40}, 5, True) == set()
    members = [(f"P{i}", "available") for i in range(30)] + [("Q1", "partial"), ("Q2", "partial")]
    d = _summary(members, [], [date(2026, 11, 16)])
    assert d["history"] == {"available": None, "partial": None, "not_available": 0}
    assert {"history.partial", "history.available"} <= set(d["suppressed"])


# --- RBAC and organization isolation (AUTH_MODE=users) ---------------------------------------


def test_summary_requires_authentication_and_permissions(world):
    assert client.get(S.format("ifhas")).status_code == 401
    for alias in ("admin_a", "patient_a", "outsider"):
        r = client.get(S.format("ifhas"), headers=world.h(alias))
        assert r.status_code == 403, alias
        assert "members" not in r.text


def test_summary_is_limited_to_the_callers_organization(world):
    a = client.get(S.format("ifhas"), headers=world.h("phm_a")).json()
    b = client.get(S.format("ifhas"), headers=world.h("phm_b")).json()
    assert a["patient_scope"] == b["patient_scope"] == "organization"
    assert a["members"] == len(_members("ifhas", set(world.patients_a)))
    assert b["members"] == len(_members("ifhas", set(world.patients_b)))
    assert a["members"] == _total(client, "pathway=ifhas", world.h("phm_a"))
    # Client-supplied filters cannot widen the scope to another organization's region.
    other_region = get_cached_index().patients_by_id[world.pid_b]["region_id"]
    cross = client.get(S.format("ifhas") + f"?region_id={other_region}", headers=world.h("phm_a")).json()
    assert cross["members"] == 0


def test_assigned_scope_summaries_respect_the_minimum_cell_size(world):
    for alias in ("cc_a", "clin_a"):
        d = client.get(S.format("ifhas"), headers=world.h(alias)).json()
        assert d["patient_scope"] == "assigned"
        # One assigned patient: below the threshold, so nothing but the suppression is returned.
        assert d["members"] is None and d["suppressed"] == ["all"]
