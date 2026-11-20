"""`GET /api/v1/facilities/points` — the map's facility layer (memory mode)."""

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_points_have_usable_coordinates_only_and_default_to_care_layers():
    r = client.get("/api/v1/facilities/points")
    assert r.status_code == 200
    body = r.json()
    assert body["source_layers"] == ["hospitals", "health_centres", "clinics"]
    assert body["total"] == len(body["items"]) > 0
    assert body["excluded_without_coordinates"] >= 0  # unusable geometry is counted, never plotted
    for p in body["items"]:
        assert p["geo_quality"] in ("ok", "swapped_repaired")
        assert 22.0 <= p["latitude"] <= 25.5 and 51.0 <= p["longitude"] <= 56.5
        assert p["source_layer"] in body["source_layers"]


def test_points_filter_by_layer_and_reject_unknown_layers():
    r = client.get("/api/v1/facilities/points", params={"source_layer": "hospitals"})
    assert r.status_code == 200
    assert {p["source_layer"] for p in r.json()["items"]} == {"hospitals"}
    assert client.get("/api/v1/facilities/points", params={"source_layer": "nope"}).status_code == 422


def test_points_route_is_not_shadowed_by_facility_detail():
    assert client.get("/api/v1/facilities/points").json().get("governance_notice")


def test_representative_point_is_the_median_of_associated_facilities_or_unmapped():
    from app.api.population import MIN_REPRESENTATIVE_FACILITIES, representative_point

    pts = [(1, "MUSAFFAH", 24.30, 54.50), (1, "MUSAFFAH", 24.35, 54.52), (1, "MUSAFFAH", 24.90, 52.60),  # outlier
           (2, "MUSAFFAH", 24.0, 55.7), (1, "BANI YAS", 24.3, 54.6)]
    la = {"level": "local_area", "region_id": 1, "name_en": "Mussafah"}
    rp = representative_point(la, "published_city_label", pts)
    assert rp == {"latitude": 24.35, "longitude": 54.5, "facility_count": 3,
                  "kind": "median_of_published_care_facility_points_approximate"}
    assert representative_point(la, "no_matching_facility_label", pts) is None
    assert representative_point({**la, "name_en": "Baniyas"}, "published_city_label", pts) is None  # < minimum
    assert MIN_REPRESENTATIVE_FACILITIES == 3
    assert representative_point({"level": "district", "region_id": 1, "name_en": "x"}, "region_of_record", pts)["facility_count"] == 4


def test_points_reconcile_with_the_published_register():
    """1,625 = care layers ∩ identified ∩ geo ok ∩ Active licence (docs/geospatial-population-intelligence.md)."""
    from collections import Counter

    items = client.get("/api/v1/facilities/points").json()["items"]
    if not items:  # raw register absent in this checkout
        return
    assert len(items) == 1625
    assert Counter(p["source_layer"] for p in items) == {"hospitals": 71, "health_centres": 808, "clinics": 746}
    assert {p["license_status"] for p in items} == {"Active"}
    assert len({p["ch_fid"] for p in items}) == len(items)


def _points(**params):
    r = client.get("/api/v1/facilities/points", params=params)
    assert r.status_code == 200, r.text
    body = r.json()
    if not body["items"]:
        pytest.skip("raw SDI facility register absent in this checkout")
    return body


def _assert_reconciles(body):
    reg = body["register"]
    assert reg["mappable"] == body["total"] == len(body["items"])
    assert reg["in_layers"] == (reg["excluded_unidentified"] + reg["excluded_license_status"]
                                + reg["excluded_invalid_coordinates"] + reg["mappable"])
    assert reg["register_total"] >= reg["in_layers"]
    assert body["excluded_without_coordinates"] == reg["excluded_invalid_coordinates"]


def test_register_summary_reconciles_the_published_register_for_care_layers():
    body = _points()
    _assert_reconciles(body)
    assert body["register"] == {
        "register_total": 5339, "in_layers": 2654, "excluded_unidentified": 0, "excluded_license_status": 1028,
        "excluded_invalid_coordinates": 1, "mappable": 1625, "license_statuses_included": ["Active"],
    }
    assert body["excluded_without_coordinates"] == 1
    assert body["governance_notice"]


def test_register_summary_for_hospitals_only():
    body = _points(source_layer="hospitals")
    _assert_reconciles(body)
    reg = body["register"]
    assert reg["register_total"] == 5339
    assert reg["mappable"] == 71
    assert reg["license_statuses_included"] == ["Active"]


def test_points_never_carry_patient_fields():
    from app.schemas.v1 import FacilityPointOut

    body = _points()
    fields = set(FacilityPointOut.model_fields)
    assert all(set(p) == fields for p in body["items"])
    assert not any("patient" in k for k in body) and not any("patient" in k for k in body["register"])


def test_register_summary_applies_exclusions_in_order():
    from app.api.v1 import facility_register_summary

    counts = [
        ("clinics", "unidentified", "missing", None, 2),
        ("clinics", "identified", "missing", "Expired", 3),
        ("clinics", "identified", "invalid", "Active", 1),
        ("clinics", "identified", "ok", "Active", 5),
        ("clinics", "identified", "ok", "Temporary Closure", 4),
        ("pharmacies", "identified", "ok", "Active", 7),
    ]
    s = facility_register_summary(counts, ("clinics",))
    assert s.model_dump() == {
        "register_total": 22, "in_layers": 15, "excluded_unidentified": 2, "excluded_license_status": 3,
        "excluded_invalid_coordinates": 1, "mappable": 9, "license_statuses_included": ["Active", "Temporary Closure"],
    }
