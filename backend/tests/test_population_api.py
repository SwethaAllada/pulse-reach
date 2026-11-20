"""BE-33 `/api/v1/population/*`: RBAC, organization isolation, privacy, filters, alert lifecycle,
staleness and concurrent refresh (AUTH_MODE=users, memory mode)."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone

import pytest

from app.core.config import settings
from app.models.population import AggregationRun
from app.services.population.service import RefreshInProgress, get_population_service
from app.services.population.store import population_session, reset_population_store
from identity_fixtures import client, users_mode, world  # noqa: F401

P = "/api/v1/population"
ROLES = ("admin_a", "phm_a", "cc_a", "clin_a", "patient_a")


@pytest.fixture
def pw(world):
    reset_population_store()
    get_population_service().reset()
    yield world
    reset_population_store()
    get_population_service().reset()


def _get(w, alias, path, **kw):
    return client.get(f"{P}{path}", headers=w.h(alias), **kw)


def _first_alert(w, alias="phm_a", **params):
    r = _get(w, alias, "/alerts", params={"limit": 200, **params})
    assert r.status_code == 200, r.text
    return r.json()["items"][0]


# --- RBAC -----------------------------------------------------------------------------------

MATRIX = [
    ("get", "/summary", None, (403, 200, 403, 200, 403)),
    ("get", "/map?condition=diabetes_type_2", None, (403, 200, 403, 200, 403)),
    ("get", "/trends?condition=hypertension", None, (403, 200, 403, 200, 403)),
    ("get", "/hotspots", None, (403, 200, 403, 200, 403)),
    ("get", "/areas/AE-AZ-AD", None, (403, 200, 403, 200, 403)),
    ("get", "/alerts", None, (403, 200, 403, 200, 403)),
    ("get", "/updates", None, (200, 200, 403, 200, 403)),
    ("get", "/config", None, (200, 200, 403, 200, 403)),
    ("post", "/refresh", None, (200, 200, 403, 403, 403)),
]


@pytest.mark.parametrize("method,path,body,expected", MATRIX, ids=[f"{m} {p}" for m, p, _, _ in MATRIX])
def test_population_role_matrix(pw, method, path, body, expected):
    got = tuple(client.request(method, f"{P}{path}", json=body, headers=pw.h(r)).status_code for r in ROLES)
    assert got == expected, dict(zip(ROLES, got))


def test_alert_lifecycle_requires_manage_permission(pw):
    alert = _first_alert(pw)
    for alias in ("clin_a", "cc_a", "patient_a", "admin_a"):
        r = client.patch(f"{P}/alerts/{alert['alert_id']}", json={"status": "ACKNOWLEDGED"}, headers=pw.h(alias))
        assert r.status_code == 403, alias
    assert _get(pw, "clin_a", f"/alerts/{alert['alert_id']}").status_code == 200  # read-only access


def test_unauthenticated_requests_are_rejected(pw):
    assert client.get(f"{P}/summary").status_code == 401


# --- isolation and privacy --------------------------------------------------------------------


def test_aggregates_are_limited_to_the_callers_organization(pw):
    a = _get(pw, "phm_a", "/summary").json()
    b = _get(pw, "phm_b", "/summary").json()
    assert a["total_population"] == len(pw.patients_a) - _deceased(pw.patients_a)
    assert b["total_population"] == len(pw.patients_b) - _deceased(pw.patients_b)
    mussafah_b = _get(pw, "phm_b", "/areas/AE-AZ-AD-L-mussafah")
    assert mussafah_b.status_code == 404  # org B has no patients there, so the area is not in its snapshot
    region_a = _get(pw, "phm_a", "/map", params={"geography": "district"}).json()["items"]
    assert {i["area"]["area_id"]: i["population"] for i in region_a}["AE-AZ-AIN"] == 0


def _deceased(pids):
    from app.repositories.read_repo import get_cached_index

    idx = get_cached_index()
    return sum(1 for pid in pids if idx.patients_by_id[pid].get("date_of_death"))


def test_alerts_of_another_organization_are_concealed(pw):
    alert = _first_alert(pw)
    assert _get(pw, "phm_b", f"/alerts/{alert['alert_id']}").status_code == 404
    r = client.patch(f"{P}/alerts/{alert['alert_id']}", json={"status": "DISMISSED"}, headers=pw.h("phm_b"))
    assert r.status_code == 404
    ids_b = {i["alert_id"] for i in _get(pw, "phm_b", "/alerts", params={"limit": 200}).json()["items"]}
    assert alert["alert_id"] not in ids_b


def test_no_patient_level_data_in_any_population_response(pw):
    from app.repositories.read_repo import get_cached_index

    idx = get_cached_index()
    names = {p["family_name"] for p in idx.patients_by_id.values()}
    paths = ["/summary", "/map?condition=diabetes_type_2", "/map?geography=district&metric=population",
             "/trends?condition=hypertension&geography=local_area", "/hotspots?min_classification=INSUFFICIENT_DATA",
             "/areas/AE-AZ-AD-L-mussafah", "/areas/AE-AZ-AD", "/alerts?limit=200"]
    for path in paths:
        body = _get(pw, "phm_a", path).text
        assert "SYNTH-PAT-" not in body and "SYNTH-EID-" not in body and "+971-" not in body, path
        assert "@example.invalid" not in body and not any(n in body for n in names), path


def _counts(obj, out):
    keys = {"population", "new_cases", "previous_new_cases", "patients_with_condition", "existing_patients",
            "undated_patients", "open_care_gaps", "patients_with_open_gap", "in_scope_patients",
            "unassigned_local_area_population"}
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in keys and isinstance(v, int) and not isinstance(v, bool):
                out.append(v)
            _counts(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _counts(v, out)
    return out


@pytest.mark.parametrize("path", [
    "/map?condition=diabetes_type_2&geography=local_area", "/map?condition=hypertension&cohort=female",
    "/map?condition=asthma&cohort=children&geography=district", "/trends?condition=diabetes_type_2&geography=local_area",
    "/areas/AE-AZ-AD-L-baniyas", "/areas/AE-AZ-AD?cohort=male", "/summary",
])
def test_small_cells_are_suppressed_everywhere(pw, path):
    k = settings.population_min_cell_size
    body = _get(pw, "phm_a", path).json()
    assert all(v == 0 or v >= k for v in _counts(body, [])), path


def test_suppressed_values_are_flagged(pw):
    items = _get(pw, "phm_a", "/map", params={"condition": "diabetes_type_2", "period": "12m"}).json()["items"]
    flagged = [i for i in items if "new_cases" in i["suppressed"]]
    assert flagged and all(i["disease"]["new_cases"] is None for i in flagged)
    assert all(i["disease"]["prevalence"] is None for i in items if "patients_with_condition" in i["suppressed"])


def test_repeated_filtering_returns_the_same_suppression(pw):
    a = _get(pw, "phm_a", "/map", params={"condition": "hypertension", "geography": "local_area"}).json()
    b = _get(pw, "phm_a", "/map", params={"condition": "hypertension", "geography": "local_area", "sort": "name",
                                          "limit": 2}).json()
    by_id = {i["area"]["area_id"]: i["suppressed"] for i in a["items"]}
    assert all(by_id[i["area"]["area_id"]] == i["suppressed"] for i in b["items"])


# --- filters and contracts --------------------------------------------------------------------


def test_map_ranks_areas_by_recorded_cases(pw):
    r = _get(pw, "phm_a", "/map", params={"condition": "diabetes_type_2", "period": "90d"}).json()
    top = r["items"][0]
    assert top["area"]["area_id"] == "AE-AZ-AD-L-mussafah" and top["disease"]["trend"]["direction"] == "INCREASING"
    assert top["hotspot_classification"] in ("WATCH", "MODERATE", "HIGH", "CRITICAL")
    assert top["area"]["boundary"] is None and r["aggregation"]["status"] == "succeeded"


@pytest.mark.parametrize("params,status", [
    ({"metric": "prevalence"}, 422),  # disease metric without a condition
    ({"condition": "influenza"}, 422),
    ({"period": "2y"}, 422),
    ({"geography": "planet"}, 422),
    ({"bbox": "1,2,3"}, 422),
    ({"bbox": "56,25,54,24"}, 422),  # min > max
    ({"limit": 0}, 422),
])
def test_invalid_map_inputs(pw, params, status):
    assert _get(pw, "phm_a", "/map", params=params).status_code == status


def test_bbox_filters_by_published_facility_extent(pw):
    # Al Dhafra's published facility points end at longitude ~54.46 (extents, not boundaries).
    r = _get(pw, "phm_a", "/map", params={"geography": "district", "bbox": "54.5,24.2,55.0,24.5"}).json()
    ids = {i["area"]["area_id"] for i in r["items"]}
    assert "AE-AZ-AD" in ids and "AE-AZ-DHF" not in ids
    local = _get(pw, "phm_b", "/map", params={"geography": "local_area", "bbox": "51,22,56.5,25.5"}).json()
    assert local["excluded_without_geometry"] == 1  # Ruwais: no matching published facility label
    assert "AE-AZ-DHF-L-ruwais" not in {i["area"]["area_id"] for i in local["items"]}


def test_unknown_area_and_empty_results(pw):
    assert _get(pw, "phm_a", "/areas/AE-AZ-XX").status_code == 404
    assert _get(pw, "phm_a", "/trends", params={"condition": "asthma", "area_id": "nope"}).status_code == 404
    r = _get(pw, "phm_a", "/alerts", params={"category": "follow_up_completion_decline"}).json()
    assert r["total"] == 0 and r["items"] == []


def test_area_detail_contents(pw):
    d = _get(pw, "phm_a", "/areas/AE-AZ-AD-L-mussafah").json()
    assert [a["area_id"] for a in d["ancestors"]] == ["AE", "AE-AZ", "AE-AZ-AD"]
    diab = next(c for c in d["conditions"] if c["condition_code"] == "diabetes_type_2")
    assert set(diab["comparisons"]) == {"7d", "30d", "90d", "6m", "12m"} and len(diab["series"]) == 12
    assert d["facilities"]["association"] == {"status": "published_city_label", "basis": "transliteration_crosswalk"}
    assert d["facilities"]["nearest_facility_distance"]["available"] is False
    assert d["preventive_care"]["preventive_coverage"] is not None
    assert any(a["category"] == "case_increase" for a in d["active_alerts"])


def test_trends_compare_equal_periods(pw):
    item = _get(pw, "phm_a", "/trends", params={"condition": "hypertension",
                                                "area_id": "AE-AZ-AD-L-khalifa-city"}).json()["items"][0]
    for c in item["comparisons"].values():
        cur = datetime.fromisoformat(c["current_end"]) - datetime.fromisoformat(c["current_start"])
        prev = datetime.fromisoformat(c["previous_end"]) - datetime.fromisoformat(c["previous_start"])
        assert cur == prev == timedelta(days=c["period_days"] - 1)
    assert item["comparisons"]["90d"]["trend"]["direction"] == "STABLE"


def test_hotspots_carry_evidence(pw):
    r = _get(pw, "phm_a", "/hotspots").json()
    hs = next(h for h in r["items"] if h["area"]["area_id"] == "AE-AZ-AD-L-mussafah")
    assert hs["reason_codes"] and hs["thresholds"]["min_cases"] == 5 and hs["comparison_period"] == "90d"
    assert hs["detected_at"] and hs["data_freshness_at"] and "not a confirmed outbreak" in hs["notice"]
    assert _get(pw, "phm_a", "/hotspots", params={"period": "7d"}).json()["period"] == "7d"


def test_localized_alert_text(pw):
    alert = _first_alert(pw, category="case_increase")
    ar = _get(pw, "phm_a", f"/alerts/{alert['alert_id']}", params={"lang": "ar"}).json()
    assert re.search(r"[\u0600-\u06FF]", ar["title"]) and ar["condition_name"] == "داء السكري من النوع الثاني"


# --- alerts lifecycle -----------------------------------------------------------------------


def test_alert_lifecycle_is_attributed_audited_and_enforced(pw):
    alert = _first_alert(pw)
    url = f"{P}/alerts/{alert['alert_id']}"
    for status in ("ACKNOWLEDGED", "INVESTIGATING"):
        r = client.patch(url, json={"status": status, "note": f"{status} by test"}, headers=pw.h("phm_a"))
        assert r.status_code == 200 and r.json()["status"] == status
    r = client.patch(url, json={"status": "ACKNOWLEDGED"}, headers=pw.h("phm_a"))
    assert r.status_code == 409 and r.json()["error"]["code"] == "conflict"
    done = client.patch(url, json={"status": "RESOLVED"}, headers=pw.h("phm_a")).json()
    assert done["closed_by"] == pw.users["phm_a"] and done["allowed_transitions"] == []
    changes = [h for h in done["history"] if h["event_type"] == "status_changed"]
    assert [h["to_status"] for h in changes] == ["ACKNOWLEDGED", "INVESTIGATING", "RESOLVED"]
    assert all(h["actor_user_id"] == pw.users["phm_a"] for h in changes)
    assert client.patch(url, json={"status": "NEW"}, headers=pw.h("phm_a")).status_code == 422
    events = client.get("/api/v1/audit-events", params={"resource_type": "population_alert", "limit": 50},
                        headers=pw.h("admin_a")).json()["items"]
    assert {e["outcome"] for e in events} == {"success", "failed"}
    assert all(e["actor_user_id"] == pw.users["phm_a"] for e in events)
    assert "note" not in json.dumps([e["details"] for e in events])


def test_repeated_refresh_updates_instead_of_duplicating(pw):
    before = _get(pw, "phm_a", "/alerts", params={"limit": 200}).json()
    client.post(f"{P}/refresh", headers=pw.h("phm_a"))
    after = _get(pw, "phm_a", "/alerts", params={"limit": 200}).json()
    assert after["total"] == before["total"] > 0
    assert all(a["occurrence_count"] == 2 for a in after["items"])


def test_resolved_alert_is_not_recreated_by_the_next_run(pw):
    alert = _first_alert(pw)
    client.patch(f"{P}/alerts/{alert['alert_id']}", json={"status": "DISMISSED"}, headers=pw.h("phm_a"))
    run = client.post(f"{P}/refresh", headers=pw.h("phm_a")).json()
    assert run["summary"]["alerts"]["suppressed_after_close"] == 1 and run["summary"]["alerts"]["created"] == 0


# --- configuration --------------------------------------------------------------------------


def test_threshold_configuration_changes_classification_and_is_audited(pw):
    cfg = _get(pw, "phm_a", "/config").json()
    assert cfg["is_default"] and cfg["version"] == 0
    th = cfg["thresholds"]
    th["hotspot"]["min_cases"] = 50
    r = client.patch(f"{P}/config", json=th, headers=pw.h("phm_a"))
    assert r.status_code == 200 and r.json()["version"] == 1
    hs = _get(pw, "phm_a", "/hotspots").json()
    assert all(h["area"]["area_id"] != "AE-AZ-AD-L-mussafah" for h in hs["items"])
    assert _get(pw, "phm_b", "/config").json()["is_default"] is True  # per organization
    bad = {**th, "hotspot": {**th["hotspot"], "min_cases": 0}}
    assert client.patch(f"{P}/config", json=bad, headers=pw.h("phm_a")).status_code == 422
    assert client.patch(f"{P}/config", json={**th, "extra": 1}, headers=pw.h("phm_a")).status_code == 422
    assert client.patch(f"{P}/config", json=th, headers=pw.h("clin_a")).status_code == 403
    events = client.get("/api/v1/audit-events", params={"action": "population.config_updated"},
                        headers=pw.h("admin_a")).json()["items"]
    assert len(events) == 1 and events[0]["actor_user_id"] == pw.users["phm_a"]


# --- freshness, staleness and concurrency -------------------------------------------------------


def test_updates_report_freshness_and_stale_data_triggers_refresh(pw, monkeypatch):
    monkeypatch.setattr(settings, "population_freshness_check_seconds", 0)
    first = _get(pw, "phm_a", "/summary").json()["aggregation"]
    u = _get(pw, "phm_a", "/updates").json()
    assert u["aggregation_status"] == "succeeded" and u["stale"] is False
    assert u["dataset_version"]["source_run_id"] == "SYNTH-RUN-0001" and u["recommended_poll_seconds"]["map"] == 60
    r = client.post(f"/api/v1/care-gaps/{pw.gap_a}/follow-ups", json={"event_type": "note_recorded", "note": "x"},
                    headers=pw.h("cc_a"))
    assert r.status_code == 201
    stale = _get(pw, "phm_a", "/summary").json()["aggregation"]
    assert stale["run_id"] == first["run_id"] and stale["stale"] and stale["refresh_scheduled"]
    fresh = _get(pw, "phm_a", "/summary").json()["aggregation"]  # background refresh ran after the response
    assert fresh["run_id"] != first["run_id"] and fresh["stale"] is False


def test_before_first_aggregation_updates_reports_never_aggregated(pw):
    assert _get(pw, "phm_a", "/updates").json()["aggregation_status"] == "never_aggregated"


def test_concurrent_refresh_is_refused(pw):
    svc = get_population_service()
    org = pw.org_a
    lock = svc._lock(org)
    lock.acquire()
    try:
        r = client.post(f"{P}/refresh", headers=pw.h("phm_a"))
        assert r.status_code == 409
    finally:
        lock.release()
    with population_session() as s:  # another worker's running aggregation (database guard)
        s.add(AggregationRun(run_id="other-worker", organization_key=org, status="running", trigger="scheduled",
                             started_at=datetime.now(timezone.utc), engine_version="1.0.0", summary={}))
    with pytest.raises(RefreshInProgress):
        svc.refresh(org, trigger="manual")
    with population_session() as s:  # abandoned after the timeout -> failed, refresh proceeds
        s.get(AggregationRun, "other-worker").started_at = datetime.now(timezone.utc) - timedelta(hours=1)
    assert svc.refresh(org, trigger="manual")["status"] == "succeeded"
    with population_session() as s:
        assert s.get(AggregationRun, "other-worker").error_code == "abandoned"


def test_legacy_mode_uses_the_unrestricted_scope(pw, monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", "legacy")
    r = client.get(f"{P}/summary")
    assert r.status_code == 200 and r.json()["total_population"] >= 500


# --- differencing (Phase 6) -------------------------------------------------------------------


def _levels(w, condition, cohort, period):
    out = {}
    for level in ("state", "district", "local_area"):
        items = _get(w, "phm_a", "/map", params={"condition": condition, "cohort": cohort, "period": period,
                                                 "geography": level, "limit": 500}).json()["items"]
        out.update({i["area"]["area_id"]: i for i in items})
    return out


@pytest.mark.parametrize("condition", ["diabetes_type_2", "hypertension", "asthma"])
@pytest.mark.parametrize("cohort", ["all", "female", "children"])
def test_parent_minus_visible_children_never_reveals_a_small_cell(pw, condition, cohort):
    """For every published parent (state, district) whose children hide exactly one value, the
    difference parent − Σ visible children must not be a small count (1…k−1)."""
    k = settings.population_min_cell_size
    leaks = []
    for period in ("30d", "12m"):
        areas = _levels(pw, condition, cohort, period)
        groups: dict[str, list[dict]] = {}
        for item in areas.values():
            if item["area"]["parent_area_id"] in areas:
                groups.setdefault(item["area"]["parent_area_id"], []).append(item)
        for parent_id, children in groups.items():
            parent = areas[parent_id]
            for field in ("new_cases", "patients_with_condition"):
                pv = (parent["disease"] or {}).get(field)
                vals = [(c["disease"] or {}).get(field) for c in children if c["disease"] is not None]
                if pv is None or sum(v is None for v in vals) != 1:
                    continue
                diff = pv - sum(v for v in vals if v is not None)
                if 0 < diff < k:
                    leaks.append((period, parent_id, field, diff))
    assert leaks == []


def test_cohort_complements_never_reveal_a_small_cell(pw):
    k = settings.population_min_cell_size
    for condition in ("diabetes_type_2", "hypertension"):
        by = {c: {i["area"]["area_id"]: i["disease"] for i in _get(pw, "phm_a", "/map", params={
            "condition": condition, "cohort": c, "period": "12m", "limit": 500}).json()["items"] if i["disease"]}
            for c in ("all", "female", "male", "adults", "children")}
        for aid, total in by["all"].items():
            for a, b in (("female", "male"), ("adults", "children")):
                t, x, y = (total or {}).get("patients_with_condition"), by[a][aid]["patients_with_condition"], \
                    by[b][aid]["patients_with_condition"]
                if t is not None and (x is None) != (y is None):
                    known = x if x is not None else y
                    assert not 0 < t - known < k, (condition, aid, a, b)
