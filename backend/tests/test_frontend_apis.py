"""Frontend-required APIs (BE-16 … BE-21), memory mode.

Facilities (filters, detail, coordinates), care-gap recommended pathway, clinical-review
decisions, open questions, and the evaluation applicability / review-origin markers.
"""

from __future__ import annotations

from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.repositories.followup_repo import reset_memory_writes
from app.repositories.read_repo import get_cached_bundle, get_cached_dataset, get_cached_index
from app.services.care_pathway import recommended_pathway, rule_applicability, rules_index

client = TestClient(app)

PACKAGE_GAP = "SYNTH-GAP-000001"  # IFHAS-PKG-MAJOR-40-64, no_documented_screening
REFERRAL_GAP = "SYNTH-GAP-000026"  # IFHAS-WF-REFERRAL-15WD, referral_not_initiated
VISIT_GAP = "SYNTH-GAP-000048"  # WCV-VISIT-12M, visit_not_attended
ADULT_FEMALE = "SYNTH-PAT-000001"  # born 1981-05-10
CHILD = "SYNTH-PAT-000013"  # born 2025-05-16


@pytest.fixture(autouse=True)
def _reset():
    yield
    reset_memory_writes()
    get_cached_index.cache_clear()
    get_cached_dataset.cache_clear()


# --- facilities --------------------------------------------------------------------------------


def test_facility_filters_are_applied():
    everything = client.get("/api/v1/facilities?limit=200").json()
    assert everything["total"] > 0
    assert "SIMULATED overlay" not in everything["governance_notice"]
    region = client.get("/api/v1/facilities?region_id=3&limit=200").json()
    assert 0 < region["total"] < everything["total"]
    assert {f["region_id"] for f in region["items"]} == {3}
    hospitals = client.get("/api/v1/facilities?facility_type=hospital&limit=200").json()
    assert 0 < hospitals["total"] < everything["total"]
    assert {f["facility_type"] for f in hospitals["items"]} == {"Hospital"}
    layer = client.get("/api/v1/facilities?source_layer=hospitals&limit=1").json()
    assert layer["total"] == hospitals["total"]
    name = hospitals["items"][0]["facility_name"]
    by_name = client.get("/api/v1/facilities", params={"q": name[:6].lower()}).json()
    assert any(f["facility_name"] == name for f in by_name["items"])
    assert client.get("/api/v1/facilities?region_id=9").status_code == 422
    assert client.get("/api/v1/facilities?source_layer=spaceports").status_code == 422


def test_facility_items_carry_published_coordinates_and_no_invented_capability():
    items = client.get("/api/v1/facilities?limit=200").json()["items"]
    for f in items:
        assert f["geo_quality"] == "ok"
        assert 22.0 <= f["latitude"] <= 25.5 and 51.0 <= f["longitude"] <= 56.5
        assert f["simulated_ifhas_service"] is None and f["simulated_wcv_service"] is None
        assert f["capability_basis"] == "unverified_sdi_facts_only"
        assert "Simulated Overlay" not in (f["facility_name"] or "")


def test_facility_detail_by_publisher_key():
    first = client.get("/api/v1/facilities?limit=1").json()["items"][0]
    detail = client.get(f"/api/v1/facilities/{quote(first['ch_fid'], safe='')}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["ch_fid"] == first["ch_fid"] and body["latitude"] == first["latitude"]
    assert "governance_notice" in body and "license_no" in body
    assert client.get("/api/v1/facilities/NOT-A-FACILITY").status_code == 404


# --- recommended pathway -----------------------------------------------------------------------


def test_package_gap_pathway_is_the_printed_package():
    rule = next(r for r in get_cached_bundle().rules if r["rule_id"] == "IFHAS-PKG-MAJOR-40-64")
    p = client.get(f"/api/v1/care-gaps/{PACKAGE_GAP}").json()["recommended_pathway"]
    assert p["status"] == "documented_next_step" and p["next_step"] == "offer_screening_package"
    assert p["details"]["components"] == rule["spec"]["components"]
    assert p["details"]["frequency_as_printed"] == rule["spec"]["frequency"]["as_printed"]
    assert p["source_reference"] == rule["source_reference"]
    assert "not a clinical recommendation" in p["notice"]


def test_referral_and_visit_gap_pathways():
    ref = client.get(f"/api/v1/care-gaps/{REFERRAL_GAP}").json()["recommended_pathway"]
    assert ref["next_step"] == "initiate_referral" and ref["details"]["timing_as_printed"]
    visit = client.get(f"/api/v1/care-gaps/{VISIT_GAP}").json()["recommended_pathway"]
    assert visit["next_step"] == "schedule_well_child_visit"
    assert visit["details"]["preventive_assessments"]


def test_pathway_withheld_for_non_authoritative_rule_and_undocumented_types():
    rule = {"rule_id": "R", "rule_version": "1", "is_authoritative": False, "spec": {"components": ["x"]},
            "rule_type": "screening_package"}
    out = recommended_pathway({"gap_type": "no_documented_screening"}, rule)
    assert out["status"] == "requires_clinical_review" and out["next_step"] is None
    out = recommended_pathway({"gap_type": "interval_elapsed"}, {**rule, "is_authoritative": True, "rule_type": "policy"})
    assert out["status"] == "no_documented_pathway" and out["next_step"] is None


# --- clinical review ---------------------------------------------------------------------------


def test_clinical_review_decisions_are_recorded_and_do_not_change_gap_status():
    body = {"reviewer": "dr.test", "action": "confirmed", "reason": "Reviewed against record."}
    created = client.post(f"/api/v1/care-gaps/{PACKAGE_GAP}/reviews", json=body)
    assert created.status_code == 201
    assert created.json()["review_id"].startswith("SYNTH-REV-")
    dismissed = client.post(f"/api/v1/care-gaps/{PACKAGE_GAP}/reviews", json={**body, "action": "dismissed"})
    assert dismissed.status_code == 201
    listed = client.get(f"/api/v1/care-gaps/{PACKAGE_GAP}/reviews").json()["items"]
    assert [r["action"] for r in listed][-2:] == ["confirmed", "dismissed"]
    detail = client.get(f"/api/v1/care-gaps/{PACKAGE_GAP}").json()
    assert detail["status"] == "open"
    assert {r["review_id"] for r in detail["reviews"]} >= {created.json()["review_id"]}


@pytest.mark.parametrize(
    "body",
    [
        {"reviewer": "dr.test", "action": "priority_overridden", "reason": "r", "new_priority": 0.9},
        {"reviewer": "dr.test", "action": "confirmed", "reason": "r", "new_priority": 0.9},
        {"reviewer": "dr.test", "action": "confirmed", "reason": "   "},
        {"reviewer": " ", "action": "confirmed", "reason": "r"},
        {"reviewer": "dr.test", "action": "approved", "reason": "r"},
    ],
)
def test_invalid_reviews_are_rejected(body):
    assert client.post(f"/api/v1/care-gaps/{PACKAGE_GAP}/reviews", json=body).status_code == 422


def test_review_unknown_gap_is_404():
    body = {"reviewer": "dr.test", "action": "confirmed", "reason": "r"}
    assert client.post("/api/v1/care-gaps/SYNTH-GAP-999999/reviews", json=body).status_code == 404
    assert client.get("/api/v1/care-gaps/SYNTH-GAP-999999/reviews").status_code == 404


# --- open questions ----------------------------------------------------------------------------


def test_open_questions_register():
    bundle = get_cached_bundle()
    resp = client.get("/api/v1/open-questions").json()
    assert resp["total"] == len(bundle.open_questions) > 0
    oq = next(o for o in resp["items"] if o["oq_id"] == "OQ-IFHAS-AGE-CEILING")
    assert "IFHAS-PROG-ELIG-MIN-AGE" in oq["rule_ids"]
    src = next(o for o in bundle.open_questions if o["oq_id"] == "OQ-IFHAS-AGE-CEILING")
    assert (oq["title"], oq["detail"], oq["status"]) == (src["title"], src["detail"], src["status"])
    assert client.get("/api/v1/open-questions/OQ-IFHAS-AGE-CEILING").json()["oq_id"] == "OQ-IFHAS-AGE-CEILING"
    assert client.get("/api/v1/open-questions/OQ-NOPE").status_code == 404
    assert client.get("/api/v1/open-questions?status=resolved").json()["total"] == sum(
        o["status"] == "resolved" for o in bundle.open_questions)
    assert client.get("/api/v1/open-questions?status=maybe").status_code == 422


# --- applicability and review origin -----------------------------------------------------------


def _evals(pid: str) -> dict[str, dict]:
    return {e["rule_id"]: e for e in client.get(f"/api/v1/patients/{pid}/evaluations").json()["evaluations"]}


def test_applicability_marker_for_adult_and_child():
    adult = _evals(ADULT_FEMALE)
    assert (adult["IFHAS-PKG-MAJOR-40-64"]["applicability"], adult["IFHAS-PKG-MAJOR-40-64"]["applicability_basis"]) == ("in_band", "rule_band")
    assert adult["IFHAS-PKG-MAJOR-18-39"]["applicability"] == "out_of_band"
    assert (adult["WCV-VISIT-01M"]["applicability"], adult["WCV-VISIT-01M"]["applicability_basis"]) == ("out_of_band", "programme_scope")
    child = _evals(CHILD)
    # Programme eligibility "eligible" for a child is out of the IFHAS programme scope (F-10).
    assert child["IFHAS-PROG-ELIG-THIQA"]["evaluation_status"] == "eligible"
    assert child["IFHAS-PROG-ELIG-THIQA"]["applicability"] == "out_of_band"
    assert child["WCV-VISIT-01M"]["applicability"] == "in_band"


def test_review_origin_marker():
    evs = _evals(ADULT_FEMALE).values()
    for e in evs:
        if e["evaluation_status"] != "requires_clinical_review":
            assert e["review_origin"] is None
        elif e["reason_code"] in ("rule_requires_clinical_review", "rule_unresolved"):
            assert e["review_origin"] == "rule"
        else:
            assert e["review_origin"] == "record"
    assert any(e["review_origin"] == "rule" for e in evs)


def test_applicability_is_never_assumed_without_attributes():
    rules = rules_index(get_cached_bundle().rules)
    from datetime import date

    pkg = rules["IFHAS-PKG-MAJOR-40-64"]
    assert rule_applicability(pkg, rules, date_of_birth=None, sex="female", reference_date=date(2026, 11, 16))[0] == "not_determined"
    assert rule_applicability(pkg, rules, date_of_birth=date(1980, 1, 1), sex=None, reference_date=date(2026, 11, 16))[0] == "not_determined"
    # 64y11m is inside "40-64 years" (completed years, as the engine); 65y0m is not.
    assert rule_applicability(pkg, rules, date_of_birth=date(1961, 12, 1), sex="male", reference_date=date(2026, 11, 16))[0] == "in_band"
    assert rule_applicability(pkg, rules, date_of_birth=date(1961, 11, 16), sex="male", reference_date=date(2026, 11, 16))[0] == "out_of_band"
    assert rule_applicability(None, rules, date_of_birth=None, sex=None, reference_date=date(2026, 11, 16)) == ("not_determined", None)


def test_post_evaluations_carries_markers():
    out = client.post("/api/v1/evaluations", json={"patient_id": ADULT_FEMALE, "look_ahead_days": 60}).json()
    e = next(e for e in out["evaluations"] if e["rule_id"] == "IFHAS-PKG-MAJOR-40-64")
    assert e["applicability"] == "in_band"
