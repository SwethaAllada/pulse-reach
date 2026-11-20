"""`GET /api/v1/facilities/points` — the map's facility layer (memory mode)."""

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
