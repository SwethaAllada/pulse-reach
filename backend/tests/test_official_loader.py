"""Tests for the `official` data loader (app.services.official_loader).

Part 1 needs no database: parsing, normalisation, provenance inputs and the dry run on the real files.
Part 2 (live) uses disposable PostgreSQL databases on the server named by TEST_DATABASE_URL: one unit-level
scenario database that is rolled back per test, and one that receives the real SCAD + SDI load once.
"""
import copy
import hashlib
import json
import os
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
import yaml
from alembic import command
from sqlalchemy import create_engine, text

from app.services.official_loader import load as L
from app.services.official_loader import parse as P
from test_official_integrity import (add, alembic_config, live, new_file, new_source, q, row_digest,
                                     scratch_database)

ROOT = P.repo_root()


# ===================================================================================================
# Part 1 - no database
# ===================================================================================================
# --- values and missing markers -------------------------------------------------------------------
def test_values_are_decimal_and_a_source_zero_stays_zero():
    assert P.normalize_value(Decimal("6.0240963855")) == (Decimal("6.0240963855"), None)
    assert P.normalize_value(0) == (Decimal(0), None)
    assert P.normalize_value(Decimal("0.0")) == (Decimal("0.0"), None)


def test_api_has_no_missing_marker_so_null_and_unknown_strings_are_rejected_not_invented():
    for bad in (None, "-", ":", "n/a", True):
        with pytest.raises(P.UnitError):
            P.normalize_value(bad)


def test_workbook_markers_are_preserved_verbatim_and_never_become_zero():
    assert P.normalize_value("-", P.WORKBOOK_MARKERS) == (None, "-")
    assert P.normalize_value(":", P.WORKBOOK_MARKERS) == (None, ":")
    with pytest.raises(P.UnitError):
        P.normalize_value("--", P.WORKBOOK_MARKERS)  # only the source-defined markers


# --- dimension members -----------------------------------------------------------------------------
@pytest.mark.parametrize("dim,label,role", [
    ("gender", None, "unlabelled"), ("gender", "Total", "aggregate"), ("age_group", "Total", "aggregate"),
    ("region", "Emirate of Abu Dhabi", "aggregate"), ("citizenship", "Emirate of Abu Dhabi", "leaf"),
    ("region", "Missing/Unknown", "missing_unknown"), ("citizenship", "Unknown", "missing_unknown"),
    ("citizenship", "Not Stated", "not_stated"), ("citizenship", "not stated", "not_stated"),
    ("region", "Abroad", "abroad"), ("region", "abroad", "abroad"), ("cause_of_death", "Other diseases", "other"),
    ("cause_of_death", "Others", "other"), ("cause_of_death", "Not applicable", "leaf"),
    ("gender", "Male", "leaf"), ("gender", "Totals", "leaf"),
])
def test_member_roles_follow_the_ordered_rules(dim, label, role):
    assert P.member_role(dim, label) == role


def test_region_members_link_to_regions_only_by_the_exact_scad_label():
    assert P.member_spec("region", "Al Ain Region", "x")["region_id"] == 2
    assert P.member_spec("region", "Emirate of Abu Dhabi", "x")["region_id"] is None
    assert P.member_spec("region", "Abroad", "x")["region_id"] is None


def test_age_labels_stay_strings_and_get_month_bounds_only_when_unambiguous():
    five = P.member_spec("age_group", "5-9", "ar")
    assert (five["raw_label_en"], five["age_min_months"], five["age_max_months"], five["scheme_code"]) == (
        "5-9", 60, 119, "5y")
    assert P.member_spec("age_group", "1-4", "ar")["scheme_code"] == "custom"
    assert P.member_spec("age_group", "15-29", "ar")["scheme_code"] == "15y"
    op = P.member_spec("age_group", "80+", "ar")
    assert (op["age_min_months"], op["age_max_months"], op["scheme_code"]) == (960, None, "open")
    inf = P.member_spec("age_group", "Less than one year", "ar")
    assert (inf["age_min_months"], inf["age_max_months"]) == (0, 11)
    tot = P.member_spec("age_group", "Total", "ar")
    assert (tot["age_min_months"], tot["scheme_code"], tot["member_role"]) == (None, None, "aggregate")


@pytest.mark.parametrize("label", ["2026-05-09", "2026-10-14", "2026-01-04"])
def test_date_like_age_labels_are_kept_verbatim_pending_and_never_corrected(label):
    s = P.member_spec("age_group", label, "ar")
    assert s["raw_label_en"] == label and isinstance(s["raw_label_en"], str)  # no date coercion
    assert s["correction_state"] == "pending"
    assert (s["age_min_months"], s["age_max_months"], s["scheme_code"]) == (None, None, None)
    assert s["label_corrected_en"] is None and s["correction_basis"] is None  # a candidate is never written


def test_a_date_like_label_on_a_non_age_dimension_fails_the_unit():
    with pytest.raises(P.UnitError, match="non-age"):
        P.member_spec("gender", "2026-05-09", "ar")


def test_canonical_key_only_folds_case_and_whitespace_and_the_placeholder_is_reserved():
    assert P.member_spec("citizenship", "  Non   Emirati ", None)["canonical_key"] == "non emirati"
    assert P.member_spec("cause_of_death", "Mental and behavioral disorders", None)["canonical_key"] != \
        P.member_spec("cause_of_death", "Mental and Behavioural Disorders", None)["canonical_key"]
    u = P.member_spec("gender", None, None)
    assert (u["raw_label_en"], u["raw_label_ar"], u["canonical_key"]) == (P.UNLABELLED, None, P.UNLABELLED)
    with pytest.raises(P.UnitError):
        P.member_spec("gender", P.UNLABELLED, None)


# --- indicator files ------------------------------------------------------------------------------
def indicator_json(tmp_path, ind=9001, dims=("GENDER",), rows=None, title="Things by Gender - Annually",
                   unit="People", time_unit=("Yearly",), total=None, slug="things_by_gender", raw_values=None):
    rows = rows if rows is not None else []
    doc = {"TotalItems": len(rows) if total is None else total, "Data": {
        "Metadata": {"component_title": title, "component_subtitle": "A sub-title.",
                     "updated": "2026-08-05T00:00:00"},
        "Properties": "|".join(f"D{i}:Total" for i, _ in enumerate(dims)),
        "Configuration": [{"indicatorId": str(ind), "unit": unit, "timeUnit": list(time_unit)}],
        "Data": rows}}
    text_ = json.dumps(doc, ensure_ascii=False)
    for token, raw in (raw_values or {}).items():  # keep a literal such as 6.0240963855 exactly as published
        text_ = text_.replace(token, raw)
    rel = f"data/raw/statad_api/indicator_detail/{ind}_{slug}.json"
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text_, encoding="utf-8")
    return rel


def row(value, year, **labels):
    r = {"VALUE": value, "OBS_DT": f"{year}-01-01", "YEAR": str(year), "MONTH_EN": None, "MONTH_AR": None,
         "QUARTER_EN": None, "QUARTER_AR": None, "MAX_VALUE": 9.0, "Name": str(year)}
    for col, label in labels.items():
        r[f"{col}_EN"], r[f"{col}_AR"] = label, (None if label is None else f"ar-{label}")
    return r


def test_rows_become_leaf_or_aggregate_by_their_members_and_nothing_is_summed(tmp_path):
    rows = [row(3.0, 2021, GENDER="Male"), row(4.0, 2021, GENDER="Female"), row(7.0, 2021, GENDER="Total")]
    u = P.parse_indicator_file(tmp_path, indicator_json(tmp_path, rows=rows), {})
    assert [(o["row_role"], o["value"]) for o in u.observations] == [
        ("leaf", Decimal("3.0")), ("leaf", Decimal("4.0")), ("aggregate", Decimal("7.0"))]  # stored as published
    assert [o["source_row_ordinal"] for o in u.observations] == [0, 1, 2]
    assert {o["quality_flag"] for o in u.observations} == {None}
    assert [d["dimension_type"] for d in u.dimensions] == ["gender"]


def test_a_row_aggregated_on_any_dimension_is_an_aggregate_row(tmp_path):
    rows = [row(1.0, 2021, GENDER="Male", REGION="Al Ain Region"), row(5.0, 2021, GENDER="Male", REGION="Emirate of Abu Dhabi"),
            row(9.0, 2021, GENDER="Total", REGION="Al Ain Region")]
    u = P.parse_indicator_file(tmp_path, indicator_json(tmp_path, dims=("GENDER", "REGION"), rows=rows), {})
    assert [o["row_role"] for o in u.observations] == ["leaf", "aggregate", "aggregate"]
    assert [d["source_column"] for d in u.dimensions] == ["GENDER_EN", "REGION_EN"]  # first-row key order


def test_values_keep_the_published_decimal_text(tmp_path):
    rows = [row(1.5, 2021, GENDER="Male")]
    rel = indicator_json(tmp_path, rows=rows, raw_values={"1.5": "6.0240963855"})
    u = P.parse_indicator_file(tmp_path, rel, {})
    assert u.observations[0]["value"] == Decimal("6.0240963855")  # no binary-float round trip


def test_age_band_labels_survive_parsing_as_strings(tmp_path):
    labels = ["5-9", "10-14", "1-4", "2026-05-09", "80+", "Total"]
    rows = [row(float(i), 2021, AGE_GROUP=lab) for i, lab in enumerate(labels)]
    u = P.parse_indicator_file(tmp_path, indicator_json(tmp_path, dims=("AGE_GROUP",), rows=rows), {})
    assert {k[1] for k in u.members} == set(labels)
    assert all(isinstance(k[1], str) for k in u.members)
    assert u.members[("age_group", "2026-05-09", "ar-2026-05-09")]["correction_state"] == "pending"


def test_projection_titles_must_match_the_known_projected_set(tmp_path):
    rows = [row(1.0, 2030, GENDER="Male")]
    with pytest.raises(P.UnitError, match="projection"):
        P.parse_indicator_file(tmp_path, indicator_json(tmp_path, rows=rows, title="Population Projection"), {})
    u = P.parse_indicator_file(tmp_path, indicator_json(tmp_path, ind=4869, rows=rows, title="Population Projection"), {})
    assert u.indicator["series_kind"] == "projected"
    plain = P.parse_indicator_file(tmp_path, indicator_json(tmp_path, ind=9002, rows=rows, slug="x"), {})
    assert plain.indicator["series_kind"] == "observed"


def test_nothing_is_classified_additive_without_a_reviewed_mapping(tmp_path):
    u = P.parse_indicator_file(tmp_path, indicator_json(tmp_path, rows=[row(1.0, 2021, GENDER="Male")]), {})
    assert u.indicator["measure_kind"] == "unclassified" and u.indicator["unit_raw"] == "People"


@pytest.mark.parametrize("mutate,message", [
    (lambda rows: rows[0].update(VALUE=None), "missing VALUE"),
    (lambda rows: rows[0].update(VALUE="-"), "missing marker|neither a number"),
    (lambda rows: rows[0].update(YEAR="2020"), "does not match OBS_DT"),
    (lambda rows: rows[0].update(NEW_THING_EN="x", NEW_THING_AR="y"), "unknown dimension column"),
])
def test_invalid_rows_fail_the_unit_instead_of_being_dropped(tmp_path, mutate, message):
    rows = [row(3.0, 2021, GENDER="Male"), row(4.0, 2021, GENDER="Female")]
    mutate(rows)
    if "NEW_THING_EN" in rows[0]:
        for r in rows[1:]:
            r.update(NEW_THING_EN="x", NEW_THING_AR="y")
    with pytest.raises(P.UnitError, match=message):
        P.parse_indicator_file(tmp_path, indicator_json(tmp_path, rows=rows), {})


def test_row_count_period_and_indicator_id_assertions(tmp_path):
    rows = [row(3.0, 2021, GENDER="Male")]
    with pytest.raises(P.UnitError, match="TotalItems"):
        P.parse_indicator_file(tmp_path, indicator_json(tmp_path, rows=rows, total=2), {})
    with pytest.raises(P.UnitError, match="timeUnit"):
        P.parse_indicator_file(tmp_path, indicator_json(tmp_path, rows=rows, time_unit=("Monthly",)), {})
    rel = indicator_json(tmp_path, rows=rows)
    wrong = tmp_path / "data/raw/statad_api/indicator_detail/9999_things_by_gender.json"
    wrong.write_bytes((tmp_path / rel).read_bytes())
    with pytest.raises(P.UnitError, match="differs from the file-name prefix"):
        P.parse_indicator_file(tmp_path, "data/raw/statad_api/indicator_detail/9999_things_by_gender.json", {})


def test_only_the_known_duplicate_rows_are_flagged_and_all_of_them(tmp_path):
    rows = [row(float(i), 1300 + i, GENDER="Male") for i in range(700)]
    dup = copy.deepcopy(rows[104])
    dup["VALUE"] = 1708.0
    rows[657] = dup  # same natural key as row 104, a different value
    u = P.parse_indicator_file(tmp_path, indicator_json(tmp_path, ind=3422, rows=rows, slug="deaths"), {})
    flagged = [o["source_row_ordinal"] for o in u.observations if o["quality_flag"] == "duplicate_key_conflict"]
    assert flagged == [104, 657]  # both rows: none is chosen, summed, averaged or dropped
    assert len(u.observations) == 700


def test_an_unexpected_duplicate_fails_the_file(tmp_path):
    rows = [row(1.0, 2021, GENDER="Male"), row(2.0, 2021, GENDER="Male")]
    with pytest.raises(P.UnitError, match="unexpected duplicate"):
        P.parse_indicator_file(tmp_path, indicator_json(tmp_path, rows=rows), {})
    rows = [row(float(i), 1300 + i, GENDER="Male") for i in range(700)]
    rows[600] = copy.deepcopy(rows[3])  # 3422 is allowed only the two known rows
    with pytest.raises(P.UnitError, match="unexpected duplicate"):
        P.parse_indicator_file(tmp_path, indicator_json(tmp_path, ind=3422, rows=rows, slug="deaths"), {})


# --- facilities ------------------------------------------------------------------------------------
def feature(oid, lon, lat, **props):
    p = {"OBJECTID": oid, "CH_FID": f"CH_{oid}", "FACILITYLICENSE": f"MF{oid}", "FACILITYNAME": f"Facility {oid}",
         "FACILITYNAMEAR": "ar", "LICENSESTATUS": "Active", "TYPE": "Hospital", "CATEGORY": "General",
         "SUBTYPE": "Medical", "REGION": "Abu Dhabi", "CITY": "X", "ISPUBLIC": "No", "HASINSURANCE": "Yes",
         "INPATIENTBEDCAPACITY": "0", "BEDS": "", "SPECIALITIES": "", "PROFESSIONALS": "p",
         "EMERGENCYDEPARTMENT": "No", "PEDIATRICEMERGENCYDEPARTMENT": "No", "MATERNITYEMERGENCYCARE": "No",
         "HOMECARESERVICES": "Yes", "THIQA": "N/A", "BASIC": "N/A", "ENHANCED": "N/A",
         "FACILITYEMAIL": "someone@example.org", "FACILITYPHONE": "+971"}
    p.update(props)
    return {"type": "Feature", "id": oid, "geometry": {"type": "Point", "coordinates": [lon, lat]}, "properties": p}


def sdi_root(tmp_path, by_layer: dict[str, list]) -> dict[str, str]:
    d = tmp_path / "data/raw/abudhabi_sdi"
    d.mkdir(parents=True, exist_ok=True)
    log, rels = {}, {}
    for i, layer in enumerate(P.SDI_LAYERS):
        feats = by_layer.get(layer, [])
        (d / f"{layer}.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": feats}))
        log[str(i)] = {"slug": layer, "feature_count": len(feats)}
        rels[layer] = f"data/raw/abudhabi_sdi/{layer}.geojson"
    (d / "acquisition_log.json").write_text(json.dumps(log))
    return rels


REGION_IDS = {"Abu Dhabi": 1, "Al Ain": 2, "Al Dhafra": 3}


def parse_fac(tmp_path, feats, layer="hospitals"):
    rels = sdi_root(tmp_path, {layer: feats})
    return P.parse_facilities(tmp_path, REGION_IDS, rels)


def test_bed_capacity_keeps_three_source_states_apart():
    assert P.parse_bed_capacity("0", True) == 0          # source-stated zero
    assert P.parse_bed_capacity("220", True) == 220
    assert P.parse_bed_capacity("", True) is None        # not recorded: never 0
    assert P.parse_bed_capacity(None, False) is None     # unidentified record
    for bad, identified in (("", False), (None, True), ("12 beds", True), ("-1", True), (5, True)):
        with pytest.raises(P.UnitError):
            P.parse_bed_capacity(bad, identified)


def test_facility_rows_preserve_bed_states_identity_and_raw_values(tmp_path):
    feats = [feature(1, 54.4, 24.4, INPATIENTBEDCAPACITY="0"), feature(2, 54.4, 24.4, INPATIENTBEDCAPACITY=""),
             feature(3, 54.4, 24.4, INPATIENTBEDCAPACITY="120", FACILITYNAME="Name  Two Spaces", ISPUBLIC="N",
                     HASINSURANCE=""),
             feature(4, 54.4, 24.4, FACILITYLICENSE=None, FACILITYNAME=None, FACILITYNAMEAR=None, TYPE=None,
                     CATEGORY=None, SUBTYPE=None, REGION=None, CITY=None, LICENSESTATUS=None, ISPUBLIC=None,
                     HASINSURANCE=None, INPATIENTBEDCAPACITY=None, EMERGENCYDEPARTMENT=None,
                     PEDIATRICEMERGENCYDEPARTMENT=None, MATERNITYEMERGENCYCARE=None, HOMECARESERVICES=None,
                     PROFESSIONALS=None)]
    fu = parse_fac(tmp_path, feats, layer="rehabilitation_center")
    zero, empty, big, unid = fu.rows
    assert zero["inpatient_bed_capacity"] == 0 and empty["inpatient_bed_capacity"] is None
    assert big["inpatient_bed_capacity"] == 120 and unid["inpatient_bed_capacity"] is None
    assert (zero["identity_status"], unid["identity_status"]) == ("identified", "unidentified")
    assert unid["license_no"] is None and unid["facility_name_en"] is None  # NULL, never ''
    assert big["facility_name_en"] == "Name  Two Spaces"                    # verbatim, no trimming
    assert (big["is_public_raw"], big["is_public"], big["has_insurance"]) == ("N", False, None)
    assert zero["beds_raw"] is None and zero["professionals_raw"] == "p"    # '' -> NULL for composite strings


def test_ifhas_and_contact_fields_are_never_loaded_or_interpreted(tmp_path):
    fu = parse_fac(tmp_path, [feature(1, 54.4, 24.4)])
    cols = set(fu.rows[0])
    assert not cols & {"thiqa", "basic", "enhanced", "ifhas_eligible", "facility_email", "facility_phone"}
    assert not any("ifhas" in c.lower() or "thiqa" in c.lower() for c in cols)
    assert "someone@example.org" not in json.dumps(fu.rows[0], default=str)


def test_original_and_corrected_coordinates_and_their_quality_classes(tmp_path):
    feats = [feature(1, 54.4, 24.4),                 # inside the rectangle
             feature(2, 24.45, 54.37),               # swapped
             feature(3, 0.0, 0.0),                   # placeholder
             feature(4, 34.4539, 24.4539),           # out of bounds (not "fixed" to 54.45)
             feature(5, 37.76, 26.75)]
    ok, swapped, zero, oob, far = parse_fac(tmp_path, feats).rows
    assert (ok["geo_quality"], ok["longitude"], ok["latitude"]) == ("ok", 54.4, 24.4)
    assert (swapped["geo_quality"], swapped["source_longitude"], swapped["source_latitude"]) == (
        "swapped_repaired", 24.45, 54.37)
    assert (swapped["longitude"], swapped["latitude"]) == (54.37, 24.45)
    assert (zero["geo_quality"], zero["source_longitude"], zero["source_latitude"], zero["longitude"],
            zero["latitude"]) == ("missing_placeholder", 0.0, 0.0, None, None)
    assert (oob["geo_quality"], oob["source_longitude"], oob["longitude"], oob["latitude"]) == (
        "out_of_bounds", 34.4539, None, None)
    assert (far["geo_quality"], far["longitude"]) == ("out_of_bounds", None)


def test_null_geometry_and_ambiguous_records_fail_the_register_unit(tmp_path):
    bad_geom = feature(1, 54.4, 24.4)
    bad_geom["geometry"] = None
    for feats, message in (
        ([bad_geom], "Point"),
        ([feature(1, 54.4, 24.4, FACILITYLICENSE=None)], "exactly one"),
        ([feature(1, 54.4, 24.4, FACILITYLICENSE="  ")], "blank"),
        ([feature(1, 54.4, 24.4, REGION="Dubai")], "unknown REGION"),
        ([feature(1, 54.4, 24.4, ISPUBLIC="Maybe")], "ISPUBLIC"),
        ([feature(1, 54.4, 24.4, EMERGENCYDEPARTMENT="Sometimes")], "EMERGENCYDEPARTMENT"),
        ([feature(1, 54.4, 24.4, INPATIENTBEDCAPACITY="many")], "digit string"),
        ([feature(1, 54.4, 24.4, CH_FID=None)], "CH_FID"),
        ([feature(1, 54.4, 24.4), feature(1, 54.5, 24.5, CH_FID="other")], "duplicate"),
        ([feature(1, 54.4, 24.4), feature(2, 54.5, 24.5, CH_FID="CH_1")], "ch_fid"),
        ([feature(1, 54.4, 24.4), feature(2, 54.5, 24.5, FACILITYLICENSE="MF1")], "license_no"),
    ):
        with pytest.raises(P.UnitError, match=message):
            parse_fac(tmp_path, feats)


def test_a_feature_count_that_disagrees_with_the_acquisition_log_fails(tmp_path):
    rels = sdi_root(tmp_path, {"hospitals": [feature(1, 54.4, 24.4)]})
    log = json.loads((tmp_path / "data/raw/abudhabi_sdi/acquisition_log.json").read_text())
    next(v for v in log.values() if v["slug"] == "hospitals")["feature_count"] = 2
    (tmp_path / "data/raw/abudhabi_sdi/acquisition_log.json").write_text(json.dumps(log))
    with pytest.raises(P.UnitError, match="acquisition log"):
        P.parse_facilities(tmp_path, REGION_IDS, rels)


# --- checksums, file ownership and the manifest -------------------------------------------------------
def tiny_repo(tmp_path, files: dict[str, bytes], listed: dict[str, str] | None = None):
    for rel, data in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_bytes(data)
    listed = listed if listed is not None else {r: hashlib.sha256(d).hexdigest() for r, d in files.items()}
    ref = tmp_path / "data/reference"
    ref.mkdir(parents=True, exist_ok=True)
    (ref / "raw_checksums.sha256").write_text("# header\n" + "".join(f"{h}  {r}\n" for r, h in listed.items()))


def test_verification_recomputes_hashes_and_accepts_an_exact_inventory(tmp_path):
    tiny_repo(tmp_path, {"data/raw/a/x.json": b"{}", "data/raw/.gitkeep": b""},  # .gitkeep is not evidence
              {"data/raw/a/x.json": hashlib.sha256(b"{}").hexdigest()})
    got = P.verify_raw_files(tmp_path)
    assert got == {"data/raw/a/x.json": {"sha256": hashlib.sha256(b"{}").hexdigest(), "byte_size": 2}}


def test_a_checksum_mismatch_a_missing_or_an_extra_file_is_fatal(tmp_path):
    tiny_repo(tmp_path, {"data/raw/a.json": b"{}"}, {"data/raw/a.json": "0" * 64})
    with pytest.raises(P.FatalError, match="checksum mismatch"):
        P.verify_raw_files(tmp_path)
    tiny_repo(tmp_path, {"data/raw/a.json": b"{}", "data/raw/b.json": b"{}"},
              {"data/raw/a.json": hashlib.sha256(b"{}").hexdigest()})
    with pytest.raises(P.FatalError, match="inventory"):
        P.verify_raw_files(tmp_path)
    tiny_repo(tmp_path, {"data/raw/a.json": b"{}"},
              {"data/raw/a.json": hashlib.sha256(b"{}").hexdigest(), "data/raw/gone.json": "1" * 64})
    with pytest.raises(P.FatalError, match="inventory"):
        P.verify_raw_files(tmp_path)


@pytest.mark.parametrize("rel,source,role,data", [
    ("data/raw/statad_api/indicator_detail/2584_x.json", "SRC-17-SCAD-STATISTICS-API", "indicator_detail", True),
    ("data/raw/statad_api/indicator_metadata/2584_x_metadata.xlsx", "SRC-17-SCAD-STATISTICS-API", "indicator_metadata", True),
    ("data/raw/statad_api/acquisition_log.json", "SRC-17-SCAD-STATISTICS-API", "other", False),
    ("data/raw/abudhabi_sdi/hospitals.geojson", "SRC-18-ABUDHABI-SDI-FACILITIES", "facility_geojson", True),
    ("data/raw/scad/scad_birth_statistics_2025_en.xlsx", "SRC-19-SCAD-VITAL-2025", "publication_workbook", True),
    ("data/raw/abudhabi_opendata/metadata/mohap_x.json", "SRC-21-MOHAP-NURSES-2008", "catalogue", True),
    ("data/raw/abudhabi_opendata/metadata/doh_x.json", "SRC-20-ABUDHABI-OPENDATA-CATALOGUE", "catalogue", True),
    ("data/raw/abudhabi_opendata/files/govdigital_clinics.xlsx", "SRC-20-ABUDHABI-OPENDATA-CATALOGUE", "other", False),
    ("data/raw/abudhabi_opendata/files/mohap_nurses_a.xlsx", "SRC-21-MOHAP-NURSES-2008", "other", True),
])
def test_file_ownership_is_by_path(rel, source, role, data):
    fc = P.classify_file(rel)
    assert (fc.source_id, fc.file_role, fc.contains_data) == (source, role, data)


def test_only_the_known_orphan_workbook_may_be_unmapped():
    assert P.classify_file("data/raw/scad/scad_health_tables_en.xlsx") is None
    info = {"sha256": "0" * 64, "byte_size": 1}
    with pytest.raises(P.FatalError, match="unmapped_file"):
        P.source_file_rows(ROOT, {"data/raw/mystery/new.bin": info}, {"sources": []})


@pytest.fixture(scope="module")
def manifest():
    return yaml.safe_load((ROOT / "data/reference/source_manifest.yaml").read_text())


def test_sources_come_from_the_manifest_with_the_stated_rules(manifest):
    rows = {r["source_id"]: r for r in P.source_rows(manifest)}
    assert len(rows) == 24 and {r["manifest_version"] for r in rows.values()} == {"2.0.0"}
    assert rows["SRC-02-IFHAS"]["acquisition_state"] == rows["SRC-03-WCV"]["acquisition_state"] == "blocked"
    assert rows["SRC-02-IFHAS"]["acquisition_reason"] and rows["SRC-02-IFHAS"]["validation_state"] is None
    assert sorted(r["validation_state"] for r in rows.values() if r["validation_state"]) == ["structural"] * 7
    scad = next(s for s in manifest["sources"] if s["id"] == "SRC-17-SCAD-STATISTICS-API")
    assert rows["SRC-17-SCAD-STATISTICS-API"]["url"] == scad["landing_page"]  # first of url, landing_page, service_url
    assert rows["SRC-17-SCAD-STATISTICS-API"]["licence_text"] == scad["permitted_reuse"]
    assert all(r["attribution_statement"] is None and r["fit_for_use"] is None for r in rows.values())


def test_the_standards_must_stay_blocked_and_nothing_may_be_clinically_validated(manifest):
    bad = copy.deepcopy(manifest)
    next(s for s in bad["sources"] if s["id"] == "SRC-02-IFHAS")["acquisition"]["state"] = "dataset_obtained"
    with pytest.raises(P.FatalError, match="blocked"):
        P.source_rows(bad)
    bad = copy.deepcopy(manifest)
    next(s for s in bad["sources"] if s["id"] == "SRC-17-SCAD-STATISTICS-API")["validation"] = "clinical"
    with pytest.raises(P.FatalError, match="clinical"):
        P.source_rows(bad)
    bad = copy.deepcopy(manifest)
    bad["sources"].append(copy.deepcopy(bad["sources"][0]))
    with pytest.raises(P.FatalError, match="duplicated"):
        P.source_rows(bad)


# --- real files, no database ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def dry():
    return L.run(root=ROOT, dry_run=True)


def test_dry_run_parses_every_real_file_without_quarantine_and_matches_the_expected_counts(dry):
    assert dry["status"] == "DRY-RUN" and dry["quarantined"] == []
    assert dry["files_verified"] == 215 and dry["files_registered"] == 214
    assert dry["files_unmapped"] == ["data/raw/scad/scad_health_tables_en.xlsx"]
    assert all(c["ok"] for c in dry["expected_checks"]), [c for c in dry["expected_checks"] if not c["ok"]]
    assert dry["planned_counts"]["observation"] == 14913 and dry["planned_counts"]["facility"] == 5339


def test_a_count_that_differs_from_the_reviewed_expectation_stops_the_run_before_any_write(monkeypatch):
    monkeypatch.setitem(P.EXPECTED, "observation", (14912, True))
    with pytest.raises(P.FatalError, match="expected counts differ"):
        L.run(root=ROOT, dry_run=True)


def test_cli_dry_run_exits_zero_and_a_fatal_input_exits_two(tmp_path, capsys):
    from app.services.official_loader.__main__ import main
    assert main(["--dry-run", "--report-file", str(tmp_path / "r.json")]) == 0
    assert json.loads((tmp_path / "r.json").read_text())["status"] == "DRY-RUN"
    assert main(["--dry-run", "--root", str(tmp_path)]) == 2  # no manifest/checksums there: nothing is written


def test_provenance_inputs_retrieval_is_recorded_only_where_a_tool_wrote_it():
    plan = L.Plan(ROOT)
    by_path = {f["relative_path"]: f for f in plan.files}
    sdi = [f for f in plan.files if f["file_role"] == "facility_geojson"]
    assert len(sdi) == 9 and all(f["retrieved_at"].date().isoformat() == "2026-11-14" for f in sdi)
    assert all(f["retrieved_at"].tzinfo is timezone.utc for f in sdi)
    scad = [f for f in plan.files if f["file_role"] in ("indicator_detail", "indicator_metadata")]
    assert len(scad) == 157 and all(f["retrieved_at"] is None for f in scad)  # a date is not a timestamp
    assert by_path["data/raw/statad_api/indicator_detail/2584_deaths_by_cause_and_age_group.json"][
        "source_effective_note"] == "Metadata.updated=2026-08-05T00:00:00"
    assert by_path["data/raw/scad/scad_birth_statistics_2025_en.xlsx"]["source_effective_note"].startswith(
        "HTTP Last-Modified: 2026-09-30 13:08:58")
    nurses = [f for f in plan.files if "mohap_nurses_" in f["relative_path"] and f["relative_path"].endswith(".xlsx")]
    assert [f["fit_for_use"] for f in nurses] == [False, False]
    listed = P.read_checksum_list(ROOT)
    assert all(listed[f["relative_path"]] == f["sha256"] for f in plan.files)
    assert {f["loader_version"] for f in plan.files} == {P.LOADER_VERSION}


def test_blocked_standards_have_no_files_and_the_loader_never_registers_them():
    plan = L.Plan(ROOT)
    assert {f["source_id"] for f in plan.files}.isdisjoint({"SRC-02-IFHAS", "SRC-03-WCV"})


def test_facility_repair_is_equivalent_to_the_validated_transformation_report():
    """The loader re-implements build_facilities.py (OFF §9.1); counts per layer and geo_quality must agree."""
    report = json.loads((ROOT / "data/processed/facilities/quality_report.json").read_text())
    plan = L.Plan(ROOT)
    fu = plan.facilities
    assert fu.layer_counts == {k: v["input_features"] for k, v in report["per_layer"].items()}
    for quality in ("ok", "swapped_repaired", "missing_placeholder", "out_of_bounds"):
        assert fu.geo_counts[quality] == sum(v[quality] for v in report["per_layer"].values())
    csv_path = ROOT / "data/processed/facilities/abu_dhabi_health_facilities.csv"
    if csv_path.exists():  # git-ignored artefact: compare coordinates for usable rows when it is present
        import csv
        ref = {(r["source_layer"], int(r["facility_id"])): r for r in csv.DictReader(csv_path.open(encoding="utf-8"))}
        for r in fu.rows:
            if r["geo_quality"] in ("ok", "swapped_repaired"):
                c = ref[(r["source_layer"], r["source_object_id"])]
                assert (float(c["longitude"]), float(c["latitude"])) == (r["longitude"], r["latitude"])


# ===================================================================================================
# Part 2 - live PostgreSQL
# ===================================================================================================
@pytest.fixture
def unit_conn():
    """Empty scratch database at head; every test's writes are rolled back."""
    with scratch_database() as url:
        command.upgrade(alembic_config(), "head")
        eng = create_engine(url, connect_args={"connect_timeout": 60})
        c = eng.connect()
        tx = c.begin()
        try:
            yield c
        finally:
            tx.rollback()
            c.close()
            eng.dispose()


def unit_fails(conn, match):
    """The block must raise UnitError and leave no write behind (a savepoint stands in for the unit's transaction)."""
    import contextlib

    @contextlib.contextmanager
    def cm():
        with pytest.raises(P.UnitError, match=match):
            with conn.begin_nested():
                yield
    return cm()


def synthetic_unit(tmp_path, rows, **kw):
    rel = indicator_json(tmp_path, rows=rows, **kw)
    return P.parse_indicator_file(tmp_path, rel, {}), rel


def register(conn, rel):
    sid = new_source(conn, "dataset_obtained")
    return add(conn, L.m.SourceFile, source_id=sid, relative_path=rel, sha256="c" * 64, byte_size=1,
               file_role="indicator_detail", contains_data=True, loader_version="t")


@live
def test_an_indicator_unit_loads_once_and_a_rerun_changes_nothing(unit_conn, tmp_path):
    rows = [row(3.0, 2021, GENDER="Male"), row(4.0, 2021, GENDER="Female"), row(7.0, 2021, GENDER="Total"),
            row(5.0, 2022, GENDER="Male"), row(5.0, 2022, GENDER="Female"), row(99.0, 2022, GENDER="Total")]
    u, rel = synthetic_unit(tmp_path, rows)
    fid = register(unit_conn, rel)
    ctr = L.Counter()
    L._load_indicator(unit_conn, None, u, {rel: fid}, ctr)
    assert ctr.t["observation"] == {"planned": 6, "inserted": 6, "skipped": 0}
    before = row_digest_conn(unit_conn)
    ctr2 = L.Counter()
    L._load_indicator(unit_conn, None, u, {rel: fid}, ctr2)  # same input again
    assert ctr2.t["observation"] == {"planned": 6, "inserted": 0, "skipped": 6}
    assert ctr2.t["dimension_member"]["inserted"] == 0 and ctr2.t["indicator"]["skipped"] == 1
    assert row_digest_conn(unit_conn) == before


def row_digest_conn(conn):
    return {t: conn.execute(text(f"SELECT count(*), md5(coalesce(string_agg(x::text, '|' ORDER BY x::text), '')) "
                                 f"FROM official.{t} x")).one()
            for t in ("indicator", "indicator_dimension", "dimension_member", "observation")}


@live
def test_a_reconciliation_mismatch_loads_and_is_only_reported(unit_conn, tmp_path):
    rows = [row(3.0, 2021, GENDER="Male"), row(4.0, 2021, GENDER="Female"), row(7.0, 2021, GENDER="Total"),
            row(5.0, 2022, GENDER="Male"), row(5.0, 2022, GENDER="Female"), row(99.0, 2022, GENDER="Total")]
    u, rel = synthetic_unit(tmp_path, rows)
    fid = register(unit_conn, rel)
    L._load_indicator(unit_conn, None, u, {rel: fid}, L.Counter())
    got = q(unit_conn, "SELECT period_year, cell_state, mismatch_class, aggregate_value, leaf_sum "
                       "FROM official.v_indicator_year_shape WHERE indicator_id = :i ORDER BY 1", i=9001)
    assert [(g[0], g[1], g[2]) for g in got] == [(2021, "reconciles", None), (2022, "mismatch", "RC-RESIDUAL-BELOW")]
    assert (got[1][3], got[1][4]) == (99, 10)  # stored as published; nothing rewritten
    stored = q(unit_conn, "SELECT value FROM official.observation WHERE value = 99")
    assert len(stored) == 1


@live
def test_aggregate_and_detail_rows_are_stored_side_by_side_and_never_added(unit_conn, tmp_path):
    rows = [row(3.0, 2021, GENDER="Male"), row(4.0, 2021, GENDER="Female"), row(7.0, 2021, GENDER="Total")]
    u, rel = synthetic_unit(tmp_path, rows)
    L._load_indicator(unit_conn, None, u, {rel: register(unit_conn, rel)}, L.Counter())
    assert q(unit_conn, "SELECT row_role, value FROM official.observation ORDER BY source_row_ordinal") == [
        ("leaf", 3), ("leaf", 4), ("aggregate", 7)]
    # the default read path holds the leaves only (aggregates would double the total) and no view re-adds them
    assert q(unit_conn, "SELECT sum(value) FROM official.v_observation_current WHERE indicator_id = 9001")[0][0] == 14
    assert q(unit_conn, "SELECT count(*), sum(value) FROM official.v_observation_leaf WHERE indicator_id = 9001"
             )[0] == (2, 7)


@live
def test_a_changed_input_for_a_loaded_file_fails_the_unit_and_never_inserts_a_subset(unit_conn, tmp_path):
    rows = [row(3.0, 2021, GENDER="Male"), row(4.0, 2021, GENDER="Female")]
    u, rel = synthetic_unit(tmp_path, rows)
    fid = register(unit_conn, rel)
    L._load_indicator(unit_conn, None, u, {rel: fid}, L.Counter())
    changed = [row(3.0, 2021, GENDER="Male"), row(4.5, 2021, GENDER="Female")]
    u2, _ = synthetic_unit(tmp_path, changed)
    with unit_fails(unit_conn, "differ"):
        L._load_indicator(unit_conn, None, u2, {rel: fid}, L.Counter())
    grown = rows + [row(1.0, 2022, GENDER="Male")]
    u3, _ = synthetic_unit(tmp_path, grown)
    with unit_fails(unit_conn, "differ"):
        L._load_indicator(unit_conn, None, u3, {rel: fid}, L.Counter())
    assert q(unit_conn, "SELECT count(*) FROM official.observation")[0][0] == 2


@live
def test_a_second_source_file_for_an_indicator_is_refused_while_retrieval_times_are_unknown(unit_conn, tmp_path):
    rows = [row(3.0, 2021, GENDER="Male")]
    u, rel = synthetic_unit(tmp_path, rows)
    L._load_indicator(unit_conn, None, u, {rel: register(unit_conn, rel)}, L.Counter())
    other = register(unit_conn, "data/raw/statad_api/indicator_detail/9001_newer.json")
    with unit_fails(unit_conn, "second vintage"):
        L._load_indicator(unit_conn, None, u, {rel: other}, L.Counter())


@live
def test_a_stored_indicator_definition_is_never_silently_overwritten(unit_conn, tmp_path):
    rows = [row(3.0, 2021, GENDER="Male")]
    u, rel = synthetic_unit(tmp_path, rows)
    fid = register(unit_conn, rel)
    L._load_indicator(unit_conn, None, u, {rel: fid}, L.Counter())
    u2, _ = synthetic_unit(tmp_path, rows, unit="Number")
    with unit_fails(unit_conn, "definition differs"):
        L._load_indicator(unit_conn, None, u2, {rel: fid}, L.Counter())


@live
def test_the_dimension_member_checks_and_roles_survive_the_load(unit_conn, tmp_path):
    rows = [row(1.0, 2021, AGE_GROUP="2026-05-09"), row(2.0, 2021, AGE_GROUP="5-9"), row(3.0, 2021, AGE_GROUP=None),
            row(6.0, 2021, AGE_GROUP="Total")]
    u, rel = synthetic_unit(tmp_path, rows, dims=("AGE_GROUP",), slug="ages")
    L._load_indicator(unit_conn, None, u, {rel: register(unit_conn, rel)}, L.Counter())
    got = {r[0]: r[1:] for r in q(unit_conn, """SELECT raw_label_en, member_role, correction_state, age_min_months
                                                FROM official.dimension_member""")}
    assert got == {"2026-05-09": ("leaf", "pending", None), "5-9": ("leaf", "none", 60),
                   P.UNLABELLED: ("unlabelled", "none", None), "Total": ("aggregate", "none", None)}


@live
def test_facilities_load_all_or_nothing_and_a_changed_register_is_refused(unit_conn, tmp_path):
    feats = [feature(1, 54.4, 24.4), feature(2, 24.45, 54.37, INPATIENTBEDCAPACITY="")]
    rels = sdi_root(tmp_path, {"hospitals": feats})
    plan = type("PlanStub", (), {})()
    plan.facilities = P.parse_facilities(tmp_path, REGION_IDS, rels)
    for i, name in enumerate(("Abu Dhabi Region", "Al Ain Region", "Al Dhafra Region"), start=1):
        add(unit_conn, L.m.Region, region_id=i, region_code=("AD", "AIN", "DHF")[i - 1], name_en=name,
            scad_label=name, sdi_label=("Abu Dhabi", "Al Ain", "Al Dhafra")[i - 1])
    fid = register(unit_conn, "data/raw/abudhabi_sdi/hospitals.geojson")
    plan.files = [{"relative_path": "data/raw/abudhabi_sdi/hospitals.geojson", "file_role": "facility_geojson"}]
    ctr = L.Counter()
    L._load_facilities(unit_conn, plan, {"data/raw/abudhabi_sdi/hospitals.geojson": fid}, ctr)
    assert ctr.t["facility"]["inserted"] == 2 and ctr.t["license_status_map"]["inserted"] == 1
    stored = q(unit_conn, "SELECT inpatient_bed_capacity, geo_quality, source_longitude, longitude FROM official.facility "
                          "ORDER BY source_object_id")
    assert stored == [(0, "ok", 54.4, 54.4), (None, "swapped_repaired", 24.45, 54.37)]
    assert q(unit_conn, "SELECT review_state, is_operating FROM official.license_status_map") == [("unreviewed", None)]
    ctr2 = L.Counter()
    L._load_facilities(unit_conn, plan, {"data/raw/abudhabi_sdi/hospitals.geojson": fid}, ctr2)
    assert ctr2.t["facility"] == {"planned": 2, "inserted": 0, "skipped": 2}
    sdi_root(tmp_path, {"hospitals": [feats[0], feature(2, 24.45, 54.37, INPATIENTBEDCAPACITY="7")]})
    plan.facilities = P.parse_facilities(tmp_path, REGION_IDS, rels)
    with unit_fails(unit_conn, "differ"):
        L._load_facilities(unit_conn, plan, {"data/raw/abudhabi_sdi/hospitals.geojson": fid}, L.Counter())


@live
def test_a_reviewed_licence_status_row_is_never_touched_by_the_loader(unit_conn, tmp_path):
    add(unit_conn, L.m.LicenseStatusMap, raw_value="Active", review_state="confirmed", status_group="g",
        is_operating=True, reviewed_by="reviewer", reviewed_on=datetime(2026, 11, 1).date())
    rels = sdi_root(tmp_path, {"hospitals": [feature(1, 54.4, 24.4)]})
    plan = type("PlanStub", (), {})()
    plan.facilities = P.parse_facilities(tmp_path, REGION_IDS, rels)
    plan.files = [{"relative_path": "data/raw/abudhabi_sdi/hospitals.geojson", "file_role": "facility_geojson"}]
    for i, name in enumerate(("Abu Dhabi Region", "Al Ain Region", "Al Dhafra Region"), start=1):
        add(unit_conn, L.m.Region, region_id=i, region_code=("AD", "AIN", "DHF")[i - 1], name_en=name,
            scad_label=name, sdi_label=("Abu Dhabi", "Al Ain", "Al Dhafra")[i - 1])
    fid = register(unit_conn, "data/raw/abudhabi_sdi/hospitals.geojson")
    L._load_facilities(unit_conn, plan, {"data/raw/abudhabi_sdi/hospitals.geojson": fid}, L.Counter())
    assert q(unit_conn, "SELECT review_state, is_operating, reviewed_by FROM official.license_status_map") == [
        ("confirmed", True, "reviewer")]


# --- the real SCAD + SDI load -----------------------------------------------------------------------
@pytest.fixture(scope="module")
def real():
    if not os.getenv("TEST_DATABASE_URL"):
        pytest.skip("TEST_DATABASE_URL not set")
    with scratch_database() as url:
        command.upgrade(alembic_config(), "head")
        eng = create_engine(url, connect_args={"connect_timeout": 60})
        report = L.run(root=ROOT, engine=eng)
        yield eng, report
        eng.dispose()


def scalar(eng, sql, **p):
    with eng.connect() as c:
        return c.execute(text(sql), p).scalar()


@live
def test_real_ingestion_populates_the_nine_tables_and_quarantines_nothing(real):
    eng, report = real
    assert report["status"] == "INGESTED" and report["quarantined"] == []  # ingestion, not reconciliation
    counts = {t: scalar(eng, f"SELECT count(*) FROM official.{t}") for t in (
        "source", "source_file", "region", "indicator", "indicator_dimension", "dimension_member", "observation",
        "facility", "license_status_map")}
    assert counts == {"source": 24, "source_file": 214, "region": 3, "indicator": 86, "indicator_dimension": 87,
                      "dimension_member": 195, "observation": 14913, "facility": 5339, "license_status_map": 14}
    assert report["post_load_checks"] == {k: 0 for k in report["post_load_checks"]}
    assert set(report["tables"]) == set(counts)
    assert scalar(eng, "SELECT count(*) FROM pg_tables WHERE schemaname IN ('clinical','synthetic')") == 0


@live
def test_real_load_is_idempotent_a_rerun_inserts_and_changes_nothing(real):
    eng, first = real
    before = row_digest(eng)
    again = L.run(root=ROOT, engine=eng)
    assert again["status"] == "INGESTED" and again["quarantined"] == []
    assert all(t["inserted"] == 0 and t["skipped"] == t["planned"] for t in again["tables"].values())
    assert row_digest(eng) == before


@live
def test_real_provenance_checksums_timestamps_and_versions(real):
    eng, _ = real
    listed = P.read_checksum_list(ROOT)
    with eng.connect() as c:
        files = c.execute(text("SELECT relative_path, sha256, retrieved_at, loader_version, file_role, source_id "
                               "FROM official.source_file")).all()
    assert {f[0]: f[1] for f in files} == {k: v for k, v in listed.items() if k in {f[0] for f in files}}
    assert len(files) == 214 and "data/raw/scad/scad_health_tables_en.xlsx" not in {f[0] for f in files}
    sdi = [f for f in files if f[4] == "facility_geojson"]
    assert all(f[2] and f[2].astimezone(timezone.utc).date().isoformat() == "2026-11-14" for f in sdi)
    assert all(f[2] is None for f in files if f[4] != "facility_geojson")
    assert {f[3] for f in files} == {P.LOADER_VERSION}
    assert scalar(eng, "SELECT count(DISTINCT loader_version) FROM official.observation") == 1
    assert scalar(eng, "SELECT DISTINCT transform_version FROM official.facility") == P.TRANSFORM_VERSION
    assert scalar(eng, "SELECT DISTINCT manifest_version FROM official.source") == "2.0.0"


@live
def test_real_blocked_standards_stay_blocked_with_no_files(real):
    eng, _ = real
    with eng.connect() as c:
        rows = c.execute(text("SELECT source_id, acquisition_state, validation_state, acquisition_reason IS NOT NULL "
                              "FROM official.source WHERE source_id IN ('SRC-02-IFHAS','SRC-03-WCV') ORDER BY 1")).all()
        files = c.execute(text("SELECT count(*) FROM official.source_file WHERE source_id IN ('SRC-02-IFHAS',"
                               "'SRC-03-WCV')")).scalar()
    assert rows == [("SRC-02-IFHAS", "blocked", None, True), ("SRC-03-WCV", "blocked", None, True)]
    assert files == 0
    assert scalar(eng, "SELECT count(*) FROM official.source WHERE validation_state = 'clinical'") == 0


@live
def test_real_aggregates_are_flagged_and_the_leaf_path_never_adds_them(real):
    eng, _ = real
    assert scalar(eng, "SELECT count(*) FROM official.observation WHERE row_role = 'aggregate'") == 5001
    assert scalar(eng, "SELECT count(*) FROM official.observation WHERE row_role = 'leaf'") == 9912
    # births 2025 by gender (3466): total 41,235 = leaves 21,471 + 19,762 + 2, stored once each
    leaf = scalar(eng, "SELECT sum(value) FROM official.v_observation_leaf WHERE indicator_id = 3466 AND period_year = 2025")
    everything = scalar(eng, "SELECT sum(value) FROM official.v_observation_current WHERE indicator_id = 3466 "
                             "AND period_year = 2025")
    assert (leaf, everything) == (41235, 2 * 41235)


@live
def test_real_projected_series_are_excluded_from_observed_views(real):
    eng, _ = real
    assert set(scalar_list(eng, "SELECT indicator_id FROM official.indicator WHERE series_kind = 'projected'")) == {
        4866, 4868, 4869, 4870}
    assert scalar(eng, "SELECT count(*) FROM official.v_observation_leaf WHERE indicator_id IN (4866,4868,4869,4870)") == 0
    assert scalar(eng, "SELECT count(*) FROM official.v_observation_current WHERE indicator_id = 4866") > 0
    assert scalar(eng, "SELECT count(*) FROM official.v_derived_total_additive") == 0  # nothing reviewed additive


def scalar_list(eng, sql):
    with eng.connect() as c:
        return [r[0] for r in c.execute(text(sql))]


@live
def test_real_missing_markers_there_are_none_in_the_api_and_none_were_invented(real):
    eng, _ = real
    assert scalar(eng, "SELECT count(*) FROM official.observation WHERE value IS NULL OR value_marker_raw IS NOT NULL") == 0
    # 'Missing/Unknown' is a dimension member carrying real numbers, never a null marker
    assert scalar(eng, "SELECT count(*) FROM official.dimension_member WHERE member_role = 'missing_unknown'") > 0


@live
def test_real_duplicate_rows_of_3422_are_both_flagged_and_excluded_from_the_default_view(real):
    eng, _ = real
    with eng.connect() as c:
        flagged = c.execute(text("SELECT source_row_ordinal, value FROM official.observation "
                                 "WHERE quality_flag = 'duplicate_key_conflict' ORDER BY 1")).all()
        in_leaf = c.execute(text("SELECT count(*) FROM official.v_observation_leaf WHERE quality_flag IS NOT NULL")).scalar()
    assert flagged == [(104, 1), (657, 1708)] and in_leaf == 0


@live
def test_real_age_band_labels_are_strings_and_the_corrupted_ones_are_pending(real):
    eng, report = real
    with eng.connect() as c:
        pending = c.execute(text("SELECT DISTINCT raw_label_en FROM official.dimension_member "
                                 "WHERE correction_state = 'pending' ORDER BY 1")).scalars().all()
        bounds = c.execute(text("SELECT count(*) FROM official.dimension_member WHERE correction_state = 'pending' "
                                "AND (age_min_months IS NOT NULL OR age_max_months IS NOT NULL OR scheme_code IS NOT NULL "
                                "OR label_corrected_en IS NOT NULL)")).scalar()
        bands = c.execute(text("SELECT raw_label_en FROM official.dimension_member WHERE dimension_type = 'age_group' "
                               "AND member_role = 'leaf' AND correction_state = 'none'")).scalars().all()
        indicators = c.execute(text("SELECT DISTINCT o.indicator_id FROM official.observation o JOIN official.dimension_member m "
                                    "ON m.member_id = o.age_group_member_id WHERE m.correction_state = 'pending' "
                                    "ORDER BY 1")).scalars().all()
    assert pending == ["2026-01-04", "2026-05-09", "2026-10-14"] and bounds == 0
    assert indicators == [2584, 3276, 3535, 4868]
    assert {"15-19", "60+", "Less than one year"} <= set(bands) and all(isinstance(b, str) for b in bands)
    # spaced variants ("15 - 19") match no mapping rule: kept verbatim, no bounds, and reported as a finding
    assert "15 - 19" in bands
    assert any(f.startswith("age_group labels without month bounds") and "'15 - 19'" in f for f in report["findings"])


@live
def test_real_bed_capacity_zero_empty_and_null_are_three_different_things(real):
    eng, _ = real
    with eng.connect() as c:
        rows = dict(c.execute(text("""
            SELECT CASE WHEN inpatient_bed_capacity IS NULL THEN identity_status || '/null'
                        WHEN inpatient_bed_capacity = 0 THEN 'source_zero' ELSE 'positive' END, count(*)
            FROM official.facility GROUP BY 1""")).all())
        hospitals = c.execute(text("SELECT count(*) FILTER (WHERE inpatient_bed_capacity > 0), "
                                   "count(*) FILTER (WHERE inpatient_bed_capacity = 0) "
                                   "FROM official.facility WHERE source_layer = 'hospitals'")).one()
    # "0" -> 0 (2,586) · "" -> NULL on identified rows (2,208, never 0) · JSON null -> NULL on unidentified rows (434)
    assert rows == {"source_zero": 2586, "positive": 111, "identified/null": 2208, "unidentified/null": 434}
    assert tuple(hospitals) == (111, 3)


@live
def test_real_original_and_corrected_coordinates_with_their_quality_classes(real):
    eng, _ = real
    with eng.connect() as c:
        counts = dict(c.execute(text("SELECT geo_quality, count(*) FROM official.facility GROUP BY 1")).all())
        swapped = c.execute(text("SELECT count(*) FROM official.facility WHERE geo_quality = 'swapped_repaired' "
                                 "AND longitude = source_latitude AND latitude = source_longitude")).scalar()
        zero = c.execute(text("SELECT count(*) FROM official.facility WHERE geo_quality = 'missing_placeholder' "
                              "AND source_longitude = 0 AND source_latitude = 0 AND longitude IS NULL")).scalar()
        vip = c.execute(text("SELECT source_longitude, longitude, geo_quality FROM official.facility "
                             "WHERE source_layer = 'provision_health_service' AND source_object_id = 334")).one()
        unusable = c.execute(text("SELECT count(*) FROM official.facility WHERE geo_quality NOT IN ('ok','swapped_repaired') "
                                  "AND (longitude IS NOT NULL OR latitude IS NOT NULL)")).scalar()
    assert counts == {"ok": 5299, "swapped_repaired": 31, "missing_placeholder": 6, "out_of_bounds": 3}
    assert (swapped, zero, unusable) == (31, 6, 0)
    assert tuple(vip) == (34.45391845703125, None, "out_of_bounds")  # geometry as published, not "fixed" to 54.45


@live
def test_real_licence_status_is_loaded_raw_unreviewed_and_nothing_is_operating(real):
    eng, _ = real
    with eng.connect() as c:
        rows = c.execute(text("SELECT raw_value, review_state, is_operating, status_group FROM official.license_status_map "
                              "ORDER BY 1")).all()
        usable = c.execute(text("SELECT count(*) FROM official.v_facility_usable")).scalar()
        identified = c.execute(text("SELECT count(*), count(license_status_raw) FROM official.facility "
                                    "WHERE identity_status = 'identified'")).one()
    assert len(rows) == 14 and {r[1:] for r in rows} == {("unreviewed", None, None)}
    assert "Preliminary -Cancelled by Law" in {r[0] for r in rows}  # the typo variant is its own row
    assert "Preliminary - Cancelled by Law" in {r[0] for r in rows}
    assert usable == 0 and tuple(identified) == (4905, 4905)


@live
def test_real_facilities_carry_no_ifhas_eligibility_and_no_contact_data(real):
    eng, _ = real
    cols = set(scalar_list(eng, "SELECT column_name FROM information_schema.columns WHERE table_schema = 'official' "
                                "AND table_name = 'facility'"))
    assert not {c for c in cols if any(w in c for w in ("thiqa", "basic", "enhanced", "ifhas", "email", "phone", "fax"))}


@live
def test_real_reconciliation_report_ingestion_success_is_not_reconciliation_success(real):
    eng, report = real
    rec = report["reconciliation"]
    one = rec["single_dimension"]
    assert one["cells_by_state"] == {"reconciles": 484, "no_aggregate": 141, "aggregate_only": 11, "mismatch": 44}
    assert one["mismatch_classes"] == {"RC-ZERO-LEAVES": 33, "RC-PROJ-ROUNDING": 4, "RC-RESIDUAL-BELOW": 4,
                                       "RC-UNEXPLAINED": 1, "RC-LEAVES-ABOVE": 2}
    # the one unexplained cell: 4868, 2024, age bands exceed the stated total by 10,940
    assert rec["rc_unexplained_cells"] == [["4868", "2024", "age_group", "4135985.0", "4146925.0", "10940.0"]]
    # the 2 extra RC-LEAVES-ABOVE cells are 2622 (2016, 2017): a 1e-9 float artefact in the published decimals
    tiny = scalar_list(eng, """SELECT indicator_id * 10000 + period_year FROM official.v_indicator_year_shape
                               WHERE indicator_id = 2622 AND mismatch_class = 'RC-LEAVES-ABOVE'
                                 AND abs(difference) < 0.000001""")
    assert sorted(tiny) == [2622 * 10000 + 2016, 2622 * 10000 + 2017]
    base = rec["phase3_baseline_screen_multi_dimension"]
    assert (base["tested"], base["reconcile"], base["mismatch"], base["not_tested"]) == (4858, 4379, 479, 432)
    assert (base["mismatch_leaves_all_zero"], base["mismatch_leaves_below"], base["mismatch_leaves_above"]) == (299, 128, 52)
    multi = rec["multi_dimension"]
    assert multi["not_testable_by_reason"] == {"aggregate_in_fixed_dimension": 1762}
    assert "RC-HIERARCHY" not in multi["mismatch_classes"] and "RC-UNEXPLAINED" not in multi["mismatch_classes"]
    assert multi["mismatch_classes"]["None"] == 13  # leaves below the aggregate with a residual already counted
    assert scalar(eng, "SELECT count(*) FROM official.v_indicator_year_shape WHERE mismatch_class = 'RC-HIERARCHY'") == 0
