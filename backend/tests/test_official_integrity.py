"""Tests for revisions 0003, 0004 and 0005: official views, deferred integrity controls, the locked
reconciliation rules and the reconciliation precision tolerance.

Every test runs against a *disposable* PostgreSQL database that this module creates on the server named by
TEST_DATABASE_URL and drops afterwards (so the shared test database is never touched). Without
TEST_DATABASE_URL, or without the privilege to create a database, the live tests are skipped.
"""
import contextlib
import os
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from pydantic import SecretStr
from sqlalchemy import create_engine, insert, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.db import session
from app.models import official as m

BACKEND = Path(__file__).resolve().parents[1]
live = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set")

VIEWS = {"v_observation_current", "v_observation_leaf", "v_indicator_year_shape",
         "v_derived_total_additive", "v_facility_usable"}
FUNCTIONS = {"enforce_obtained_source_has_source_file", "enforce_observation_member_dimension_type",
             "forbid_retyping_referenced_dimension_member"}
TRIGGERS = {"trg_source_obtained_requires_source_file", "trg_source_file_keeps_obtained_source_covered",
            "trg_observation_member_dimension_type", "trg_dimension_member_type_not_retyped"}
DIMENSIONS = {  # dimension_type -> observation column
    "region": "region_member_id", "citizenship": "citizenship_member_id", "gender": "gender_member_id",
    "age_group": "age_group_member_id", "cause_of_death": "cause_of_death_member_id",
    "disease_type": "disease_type_member_id", "measure_item": "measure_item_member_id",
    "insurance_type": "insurance_type_member_id", "sector": "sector_member_id", "bed_type": "bed_type_member_id",
}
T_OLD = datetime(2025, 1, 1, tzinfo=timezone.utc)
T_NEW = datetime(2026, 1, 1, tzinfo=timezone.utc)
SOURCE_CONSTRAINT = "source_obtained_requires_source_file"
TYPE_CONSTRAINT = "observation_member_dimension_type"


# --- disposable database and migration plumbing ----------------------------
def alembic_config() -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    return cfg


@contextlib.contextmanager
def scratch_database():
    """Create an empty database on the test server, point the app settings at it, drop it afterwards."""
    base = make_url(os.environ["TEST_DATABASE_URL"])
    name = f"pr_integ_{uuid.uuid4().hex[:12]}"
    admin = create_engine(base, isolation_level="AUTOCOMMIT", connect_args={"connect_timeout": 60})
    try:
        with admin.connect() as c:
            c.execute(text(f'CREATE DATABASE "{name}"'))
    except DBAPIError as exc:  # no CREATE DATABASE privilege
        admin.dispose()
        pytest.skip(f"cannot create a disposable database: {exc.orig}")
    url = base.set(database=name).render_as_string(hide_password=False)
    mp = pytest.MonkeyPatch()
    mp.setattr(session.settings, "database_url", SecretStr(url))
    mp.setattr(session.settings, "db_connect_timeout", 60)
    session.get_engine.cache_clear()
    try:
        yield url
    finally:
        mp.undo()
        session.get_engine.cache_clear()
        with admin.connect() as c:
            c.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture(scope="module")
def engine():
    with scratch_database() as url:
        command.upgrade(alembic_config(), "head")
        eng = create_engine(url, connect_args={"connect_timeout": 60})
        yield eng
        eng.dispose()


@pytest.fixture
def conn(engine):
    """A connection inside a transaction that is always rolled back."""
    c = engine.connect()
    tx = c.begin()
    try:
        yield c
    finally:
        tx.rollback()
        c.close()


# --- row helpers ------------------------------------------------------------
_n = iter(range(1, 10**6))


def n():
    return next(_n)


def add(conn, model, **values):
    return conn.execute(insert(model).values(**values).returning(*model.__table__.primary_key.columns)).one()[0]


def q(conn, sql, **p):
    return conn.execute(text(sql), p).all()


def new_source(conn, state="researched", **o):
    return add(conn, m.Source, **{"source_id": f"SRC-I{n()}", "name": "n", "publisher": "p",
                                  "acquisition_state": state, "manifest_version": "2.0.0", **o})


def new_file(conn, source_id=None, **o):
    return add(conn, m.SourceFile, **{
        "source_id": source_id or new_source(conn, "dataset_obtained"), "relative_path": f"raw/i{n()}.json",
        "sha256": "b" * 64, "byte_size": 1, "file_role": "indicator_detail", "contains_data": True,
        "loader_version": "t", **o})


def new_indicator(conn, **o):
    i = n()
    return add(conn, m.Indicator, **{"indicator_id": i, "slug": f"i{i}_slug", "title_en": "t", "unit_raw": "Number",
                                     "measure_kind": "count", "series_kind": "observed", "periodicity": "annual",
                                     "region_basis": "residence", **o})


def new_member(conn, dimension_type="gender", role="leaf", label=None, **o):
    return add(conn, m.DimensionMember, **{"dimension_type": dimension_type, "raw_label_en": label or f"L{n()}",
                                           "canonical_key": "k", "member_role": role, **o})


def obs(conn, indicator_id, file_id, year=2025, value=1, row_role="leaf", **o):
    return add(conn, m.Observation, **{
        "indicator_id": indicator_id, "source_file_id": file_id, "period_year": year, "period_type": "year",
        "obs_date_raw": f"{year}-12-31", "value": value, "row_role": row_role, "source_row_ordinal": n(),
        "loader_version": "t", **o})


def rejected(conn, constraint, fn, sqlstate="23514"):
    """`fn` must fail on exactly this named constraint."""
    with pytest.raises(IntegrityError) as ei:
        with conn.begin_nested():
            fn()
    assert ei.value.orig.diag.constraint_name == constraint, ei.value.orig
    assert ei.value.orig.sqlstate == sqlstate


def check_deferred(conn):
    conn.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    conn.execute(text("SET CONSTRAINTS ALL DEFERRED"))


# --- catalogue: what the migration creates -----------------------------------
@live
def test_exactly_the_designed_views_triggers_and_functions_exist(engine):
    with engine.connect() as c:
        views = {(s, v) for s, v in c.execute(text("SELECT schemaname, viewname FROM pg_views "
                                                  "WHERE schemaname IN ('official','clinical','synthetic')"))}
        funcs = {r[0] for r in c.execute(text("""SELECT p.proname FROM pg_proc p JOIN pg_namespace n
                                                ON n.oid = p.pronamespace WHERE n.nspname = 'official'"""))}
        trigs = c.execute(text("""SELECT t.tgname, t.tgdeferrable, t.tginitdeferred, t.tgenabled
                                  FROM pg_trigger t JOIN pg_class r ON r.oid = t.tgrelid
                                  JOIN pg_namespace n ON n.oid = r.relnamespace
                                  WHERE n.nspname = 'official' AND NOT t.tgisinternal""")).all()
    assert views == {("official", v) for v in VIEWS}
    assert funcs == FUNCTIONS
    assert {t[0] for t in trigs} == TRIGGERS
    assert {t[0]: (t[1], t[2]) for t in trigs if "obtained" in t[0] or "covered" in t[0]} == {
        "trg_source_obtained_requires_source_file": (True, True),
        "trg_source_file_keeps_obtained_source_covered": (True, True)}  # deferrable, initially deferred
    assert all(t[3] == "O" for t in trigs)  # enabled


@live
def test_no_view_joins_facility_to_observations_or_reaches_other_schemas(engine):
    """R-O4 (no facility <-> SCAD view) and the official -> synthetic isolation rule."""
    with engine.connect() as c:
        rows = c.execute(text("""
            SELECT v.relname, d.refobjid::regclass::text FROM pg_class v
            JOIN pg_namespace n ON n.oid = v.relnamespace AND n.nspname = 'official'
            JOIN pg_rewrite rw ON rw.ev_class = v.oid
            JOIN pg_depend d ON d.objid = rw.oid AND d.refclassid = 'pg_class'::regclass
            WHERE v.relkind = 'v' AND d.refobjid <> v.oid""")).all()
    deps = {}
    for view, ref in rows:
        deps.setdefault(view, set()).add(ref)
    assert deps["v_facility_usable"] <= {"official.facility", "official.license_status_map"}
    for view in VIEWS - {"v_facility_usable"}:
        assert not any("facility" in r for r in deps[view]), view
    assert not any(r.split(".")[0] in {"clinical", "synthetic"} for refs in deps.values() for r in refs)


# --- v_observation_current ---------------------------------------------------
@live
def test_v_observation_current_selects_latest_vintage_per_indicator(conn):
    ind, single, tie = new_indicator(conn), new_indicator(conn), new_indicator(conn)
    old = new_file(conn, retrieved_at=T_OLD)
    new = new_file(conn, retrieved_at=T_NEW)
    undated = new_file(conn)  # retrieved_at NULL = unknown = oldest
    o_old, o_new, o_undated = obs(conn, ind, old), obs(conn, ind, new), obs(conn, ind, undated)
    only = obs(conn, single, new_file(conn))  # a single file is current whatever its retrieved_at
    t1, t2 = new_file(conn), new_file(conn)  # both NULL: deterministic tie-break on the higher id
    obs(conn, tie, t1)
    o_t2 = obs(conn, tie, t2)

    rows = q(conn, "SELECT observation_id, series_kind FROM official.v_observation_current "
                   "WHERE indicator_id = ANY(:ids)", ids=[ind, single, tie])
    assert {r[0] for r in rows} == {o_new, only, o_t2}  # not o_old, not the undated file of `ind`
    assert {o_old, o_undated}.isdisjoint({r[0] for r in rows})
    assert {r[1] for r in rows} == {"observed"}


@live
def test_v_observation_current_does_not_filter_projected_and_exposes_series_kind(conn):
    proj = new_indicator(conn, series_kind="projected")
    f = new_file(conn)
    o = obs(conn, proj, f)
    assert q(conn, "SELECT series_kind FROM official.v_observation_current WHERE observation_id = :o", o=o) == [
        ("projected",)]


# --- v_observation_leaf ------------------------------------------------------
@live
def test_v_observation_leaf_is_leaf_clean_observed_current(conn):
    ind = new_indicator(conn)
    proj = new_indicator(conn, series_kind="projected")
    old = new_file(conn, retrieved_at=T_OLD)
    cur = new_file(conn, retrieved_at=T_NEW)
    pf = new_file(conn)
    keep = obs(conn, ind, cur, year=2024)
    obs(conn, ind, cur, year=2025, row_role="aggregate")               # aggregate row
    obs(conn, ind, cur, year=2026, quality_flag="duplicate_key_conflict")  # flagged
    obs(conn, ind, old, year=2027)                                     # superseded vintage
    obs(conn, proj, pf, year=2030)                                     # projected series
    got = q(conn, "SELECT observation_id, series_kind, row_role, quality_flag FROM official.v_observation_leaf "
                  "WHERE indicator_id = ANY(:ids)", ids=[ind, proj])
    assert got == [(keep, "observed", "leaf", None)]


# --- v_indicator_year_shape and v_derived_total_additive ----------------------
def gender_members(conn):
    return {
        "m": new_member(conn, "gender", "leaf", f"Male{n()}"),
        "f": new_member(conn, "gender", "leaf", f"Female{n()}"),
        "ns": new_member(conn, "gender", "not_stated", f"NotStated{n()}"),
        "total": new_member(conn, "gender", "aggregate", f"Total{n()}"),
        "total2": new_member(conn, "gender", "aggregate", f"AllPersons{n()}"),
    }


def put(conn, ind, f, year, spec, mem):
    """spec: {member key: value}; aggregate rows get row_role 'aggregate'."""
    for key, value in spec.items():
        role = "aggregate" if key.startswith("total") else "leaf"
        obs(conn, ind, f, year=year, value=value, row_role=role, gender_member_id=mem[key])


def shape(conn, ind):
    rows = q(conn, """SELECT period_year, cell_state, mismatch_class, has_aggregate, n_leaf_members,
                             n_aggregate_members, aggregate_value, leaf_sum, difference, dimension_type, fixed_members
                      FROM official.v_indicator_year_shape WHERE indicator_id = :i ORDER BY period_year""", i=ind)
    return {r[0]: r for r in rows}


@live
def test_v_indicator_year_shape_classifies_every_cell_state_and_mismatch_class(conn):
    ind = new_indicator(conn)
    f = new_file(conn)
    mem = gender_members(conn)
    put(conn, ind, f, 2020, {"m": 3, "f": 4, "total": 7}, mem)                 # reconciles
    put(conn, ind, f, 2021, {"m": 3, "f": 4}, mem)                             # no_aggregate
    put(conn, ind, f, 2022, {"total": 7}, mem)                                 # aggregate_only
    put(conn, ind, f, 2023, {"m": 0, "f": 0, "total": 9}, mem)                 # RC-ZERO-LEAVES
    put(conn, ind, f, 2024, {"m": 3, "f": 4, "total": 10}, mem)                # RC-RESIDUAL-BELOW
    put(conn, ind, f, 2025, {"m": 3, "f": 4, "total": 5}, mem)                 # RC-LEAVES-ABOVE
    put(conn, ind, f, 2026, {"m": 3, "ns": 2, "total": 9}, mem)                # residual present -> unresolved
    put(conn, ind, f, 2027, {"m": 3, "f": 4, "total": 7, "total2": 9}, mem)    # two aggregates -> not testable
    put(conn, ind, f, 2028, {"m": 3, "f": 4, "total": 5, "total2": 5}, mem)    # hierarchy is never inferred
    got = shape(conn, ind)

    def cell(year):
        r = got[year]
        return r[1], r[2]

    assert cell(2020) == ("reconciles", None)
    assert cell(2021) == ("no_aggregate", None)
    assert cell(2022) == ("aggregate_only", None)
    assert cell(2023) == ("mismatch", "RC-ZERO-LEAVES")
    assert cell(2024) == ("mismatch", "RC-RESIDUAL-BELOW")
    assert cell(2025) == ("mismatch", "RC-LEAVES-ABOVE")
    # leaves below the aggregate with a residual member already among them: the residual does not explain the
    # shortfall, and RC-UNEXPLAINED is not a fall-through -> a mismatch left unresolved (class NULL)
    assert cell(2026) == ("mismatch", None)
    # two aggregate members prove nothing about nesting: RC-HIERARCHY is never inferred
    assert cell(2027) == ("not_testable", None) and cell(2028) == ("not_testable", None)
    reasons = dict(q(conn, "SELECT period_year, not_testable_reason FROM official.v_indicator_year_shape "
                           "WHERE indicator_id = :i AND cell_state = 'not_testable'", i=ind))
    assert reasons == {2027: "multiple_aggregate_members_unverified_hierarchy",
                       2028: "multiple_aggregate_members_unverified_hierarchy"}
    assert not q(conn, "SELECT 1 FROM official.v_indicator_year_shape WHERE mismatch_class = 'RC-HIERARCHY'")
    # numbers are preserved, nothing is rewritten
    assert got[2024][6:9] == (10, 7, -3) and got[2025][6:9] == (5, 7, 2)
    assert got[2021][3] is False and got[2020][3] is True and got[2022][4] == 0
    assert all(r[9] == "gender" and r[10] == {} for r in got.values())  # single dimension: nothing fixed


@live
def test_v_indicator_year_shape_projection_tolerance(conn):
    proj = new_indicator(conn, series_kind="projected")
    f = new_file(conn)
    mem = gender_members(conn)
    put(conn, proj, f, 2030, {"m": 1000, "f": 2000, "total": 3500}, mem)   # |diff| 500 <= 2 * 1000 / 2
    put(conn, proj, f, 2035, {"m": 1000, "f": 2000, "total": 6000}, mem)   # exceeds the tolerance
    put(conn, proj, f, 2024, {"m": 10, "f": 20, "total": 40}, mem)         # step 5: |diff| 10 > 2 * 5 / 2
    put(conn, proj, f, 2040, {"m": 1000, "f": 2000, "total": 3000}, mem)   # exact
    put(conn, proj, f, 2045, {"m": 1000, "f": 2000, "total": 3500}, mem)   # 2030+ tolerance applies from 2030 on
    # No tolerance is defined for 2025-2029 and none is extrapolated: the same 500 gap that is rounding in
    # 2030 is an unresolved mismatch in 2027 (never RC-PROJ-ROUNDING, never RC-UNEXPLAINED either).
    put(conn, proj, f, 2027, {"m": 1000, "f": 2000, "total": 3500}, mem)
    got = shape(conn, proj)
    assert (got[2030][1], got[2030][2]) == ("mismatch", "RC-PROJ-ROUNDING")
    assert (got[2035][1], got[2035][2]) == ("mismatch", "RC-UNEXPLAINED")
    assert (got[2024][1], got[2024][2]) == ("mismatch", "RC-UNEXPLAINED")  # never RC-LEAVES-ABOVE
    assert (got[2040][1], got[2040][2]) == ("reconciles", None)
    assert (got[2045][1], got[2045][2]) == ("mismatch", "RC-PROJ-ROUNDING")
    assert (got[2027][1], got[2027][2]) == ("mismatch", None)
    series = {r[0] for r in q(conn, "SELECT series_kind FROM official.v_indicator_year_shape WHERE indicator_id=:i",
                              i=proj)}
    assert series == {"projected"}  # projections are visible in the shape view, and labelled


@live
def test_v_indicator_year_shape_multi_dimension_slices_and_exclusions(conn):
    ind = new_indicator(conn)
    cur, old = new_file(conn, retrieved_at=T_NEW), new_file(conn, retrieved_at=T_OLD)
    cit = {k: new_member(conn, "citizenship", r, f"{k}{n()}") for k, r in
           (("em", "leaf"), ("non", "leaf"), ("tot", "aggregate"))}
    gen = {k: new_member(conn, "gender", r, f"{k}{n()}") for k, r in
           (("m", "leaf"), ("f", "leaf"), ("tot", "aggregate"))}
    values = {("em", "m"): 1, ("em", "f"): 2, ("em", "tot"): 3, ("non", "m"): 10, ("non", "f"): 20,
              ("non", "tot"): 31,  # mismatch: leaves 30
              ("tot", "m"): 11, ("tot", "f"): 22, ("tot", "tot"): 33}
    for (c, g), v in values.items():
        role = "aggregate" if "tot" in (c, g) else "leaf"
        obs(conn, ind, cur, year=2025, value=v, row_role=role,
            citizenship_member_id=cit[c], gender_member_id=gen[g])
    # excluded from every slice: a flagged duplicate and a superseded vintage
    obs(conn, ind, cur, year=2025, value=999, quality_flag="duplicate_key_conflict",
        citizenship_member_id=cit["em"], gender_member_id=gen["m"])
    obs(conn, ind, old, year=2025, value=888, citizenship_member_id=cit["em"], gender_member_id=gen["m"])

    rows = q(conn, """SELECT dimension_type, fixed_members, cell_state, mismatch_class, leaf_sum, aggregate_value
                      FROM official.v_indicator_year_shape WHERE indicator_id = :i""", i=ind)
    got = {(r[0], tuple(sorted(r[1].items()))): r[2:] for r in rows}
    assert got == {
        ("gender", (("citizenship", cit["em"]),)): ("reconciles", None, 3, 3),
        ("gender", (("citizenship", cit["non"]),)): ("mismatch", "RC-RESIDUAL-BELOW", 30, 31),
        ("citizenship", (("gender", gen["m"]),)): ("reconciles", None, 11, 11),
        ("citizenship", (("gender", gen["f"]),)): ("reconciles", None, 22, 22),
        # slices whose fixed members include an aggregate are kept in the screening and marked not testable
        ("gender", (("citizenship", cit["tot"]),)): ("not_testable", None, 33, 33),
        ("citizenship", (("gender", gen["tot"]),)): ("not_testable", None, 34, 33),
    }
    reasons = {r[0] for r in q(conn, "SELECT not_testable_reason FROM official.v_indicator_year_shape "
                                     "WHERE indicator_id = :i AND cell_state = 'not_testable'", i=ind)}
    assert reasons == {"aggregate_in_fixed_dimension"}


@live
def test_v_derived_total_additive_excludes_mismatch_projected_and_non_additive(conn):
    mem = gender_members(conn)
    f = new_file(conn)
    additive = new_indicator(conn, measure_kind="count")
    put(conn, additive, f, 2020, {"m": 3, "f": 4, "total": 7}, mem)    # reconciles  -> derived
    put(conn, additive, f, 2021, {"m": 3, "f": 4}, mem)                # no_aggregate-> derived
    put(conn, additive, f, 2022, {"total": 7}, mem)                    # aggregate_only: nothing to derive
    put(conn, additive, f, 2023, {"m": 0, "f": 0, "total": 9}, mem)    # mismatch: excluded
    put(conn, additive, f, 2025, {"m": 3, "f": 4, "total": 5}, mem)    # mismatch: excluded
    # a NULL cell value (marker) makes the sum unsafe
    obs(conn, additive, f, year=2026, value=None, value_marker_raw="-", gender_member_id=mem["m"])
    obs(conn, additive, f, year=2026, value=4, gender_member_id=mem["f"])
    rate = new_indicator(conn, measure_kind="rate")
    unclassified = new_indicator(conn, measure_kind="unclassified")
    projected = new_indicator(conn, measure_kind="count", series_kind="projected")
    for other in (rate, unclassified, projected):
        put(conn, other, f, 2021, {"m": 3, "f": 4}, mem)

    got = q(conn, """SELECT indicator_id, period_year, derived_total, cell_state, value_origin
                     FROM official.v_derived_total_additive WHERE indicator_id = ANY(:ids) ORDER BY 1, 2""",
            ids=[additive, rate, unclassified, projected])
    assert got == [(additive, 2020, 7, "reconciles", "derived"), (additive, 2021, 7, "no_aggregate", "derived")]
    assert isinstance(got[0][2], Decimal)


# --- v_facility_usable -------------------------------------------------------
def new_status(conn, raw, operating):
    if operating is None:
        return add(conn, m.LicenseStatusMap, raw_value=f"{raw}{n()}", review_state="unreviewed")
    return add(conn, m.LicenseStatusMap, raw_value=f"{raw}{n()}", review_state="confirmed", status_group="g",
               is_operating=operating, reviewed_by="reviewer", reviewed_on=date(2026, 11, 1))


def new_facility(conn, f, **o):
    i = n()
    return add(conn, m.Facility, **{
        "source_layer": "hospitals", "source_object_id": i, "ch_fid": f"DOH_I{i}", "identity_status": "identified",
        "geo_quality": "ok", "longitude": 54.4, "latitude": 24.4, "source_file_id": f, "transform_version": "t", **o})


@live
def test_v_facility_usable_requires_identity_coordinates_and_reviewed_operating_licence(conn):
    f = new_file(conn)
    active, closed, unreviewed = new_status(conn, "Active", True), new_status(conn, "Closed", False), \
        new_status(conn, "Mystery", None)
    ok = new_facility(conn, f, license_status_raw=active)
    repaired = new_facility(conn, f, license_status_raw=active, geo_quality="swapped_repaired")
    assert q(conn, "SELECT count(*) FROM official.v_facility_usable WHERE facility_id = ANY(:i)", i=[ok, repaired])[
        0][0] == 2
    excluded = [
        new_facility(conn, f, license_status_raw=closed),                                   # reviewed: not operating
        new_facility(conn, f, license_status_raw=unreviewed),                               # never inferred
        new_facility(conn, f),                                                              # no licence status
        new_facility(conn, f, license_status_raw=active, longitude=None, latitude=None,
                     geo_quality="missing_placeholder"),                                    # no usable coordinates
        new_facility(conn, f, license_status_raw=active, longitude=None, latitude=None,
                     geo_quality="out_of_bounds"),                                          # bad source coordinates
        new_facility(conn, f, license_status_raw=active, identity_status="unidentified"),   # no identity
    ]
    got = {r[0] for r in q(conn, "SELECT facility_id FROM official.v_facility_usable "
                                 "WHERE facility_id = ANY(:i)", i=[ok, repaired, *excluded])}
    assert got == {ok, repaired}


@live
def test_v_facility_usable_is_empty_until_a_mapping_is_confirmed(conn):
    f = new_file(conn)
    raw = new_status(conn, "Active", None)  # proposed/unreviewed only
    fac = new_facility(conn, f, license_status_raw=raw)
    assert q(conn, "SELECT count(*) FROM official.v_facility_usable WHERE facility_id = :i", i=fac)[0][0] == 0


# --- source -> source_file integrity (deferred constraint trigger) ------------
@live
@pytest.mark.parametrize("state", ["dataset_obtained", "document_obtained"])
def test_obtained_source_without_file_is_rejected_at_the_check_point(conn, state):
    new_source(conn, state)
    # the insert itself succeeded (deferred); the check fires when constraints are made immediate / at COMMIT
    with pytest.raises(IntegrityError) as ei:
        with conn.begin_nested():
            conn.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    assert ei.value.orig.diag.constraint_name == SOURCE_CONSTRAINT
    assert ei.value.orig.sqlstate == "23514"


@live
@pytest.mark.parametrize("state", ["researched", "blocked", "excluded"])
def test_non_obtained_source_needs_no_file(conn, state):
    new_source(conn, state)
    check_deferred(conn)


@live
def test_source_then_file_in_one_transaction_is_accepted(conn):
    sid = new_source(conn, "dataset_obtained")  # parent first, file second: allowed until the check point
    new_file(conn, sid)
    check_deferred(conn)
    doc = new_source(conn, "document_obtained")
    new_file(conn, doc, file_role="publication_workbook")
    check_deferred(conn)


@live
def test_promoting_a_source_to_obtained_needs_a_file(conn):
    sid = new_source(conn, "blocked")
    conn.execute(text("UPDATE official.source SET acquisition_state = 'dataset_obtained' WHERE source_id = :s"), {"s": sid})
    with pytest.raises(IntegrityError) as ei:
        with conn.begin_nested():
            conn.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    assert ei.value.orig.diag.constraint_name == SOURCE_CONSTRAINT
    new_file(conn, sid)
    check_deferred(conn)


@live
def test_removing_or_moving_the_last_file_of_an_obtained_source_is_rejected(conn):
    sid = new_source(conn, "dataset_obtained")
    f1, f2 = new_file(conn, sid), new_file(conn, sid)
    other = new_source(conn, "dataset_obtained")
    new_file(conn, other)
    check_deferred(conn)

    conn.execute(text("DELETE FROM official.source_file WHERE source_file_id = :f"), {"f": f1})
    check_deferred(conn)  # one file remains: fine

    conn.execute(text("DELETE FROM official.source_file WHERE source_file_id = :f"), {"f": f2})
    with pytest.raises(IntegrityError) as ei:
        with conn.begin_nested():
            conn.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    assert ei.value.orig.diag.constraint_name == SOURCE_CONSTRAINT

    # moving the only file to another source also leaves the first one empty
    conn.execute(text("UPDATE official.source SET acquisition_state = 'blocked' WHERE source_id = :s"), {"s": sid})
    check_deferred(conn)  # blocked sources may be empty again
    mover = new_file(conn, other)
    conn.execute(text("UPDATE official.source_file SET source_id = :n WHERE source_file_id = :f"),
                 {"n": sid, "f": mover})
    check_deferred(conn)  # `other` still has its own file


@live
def test_the_check_runs_at_commit_for_real(engine):
    sid = f"SRC-COMMIT-{uuid.uuid4().hex[:8]}"
    with engine.connect() as c:
        c.execute(insert(m.Source).values(source_id=sid, name="n", publisher="p",
                                          acquisition_state="dataset_obtained", manifest_version="2.0.0"))
        with pytest.raises(IntegrityError) as ei:
            c.commit()
        assert ei.value.orig.diag.constraint_name == SOURCE_CONSTRAINT
    with engine.begin() as c:  # source and file together commit cleanly
        c.execute(insert(m.Source).values(source_id=sid, name="n", publisher="p",
                                          acquisition_state="dataset_obtained", manifest_version="2.0.0"))
        c.execute(insert(m.SourceFile).values(source_id=sid, relative_path=f"raw/{sid}.json", sha256="c" * 64,
                                              byte_size=1, file_role="other", contains_data=False,
                                              loader_version="t"))
    with engine.begin() as c:  # cleanup of the committed rows (file first, then state, then source)
        c.execute(text("UPDATE official.source SET acquisition_state = 'excluded' WHERE source_id = :s"), {"s": sid})
        c.execute(text("DELETE FROM official.source_file WHERE source_id = :s"), {"s": sid})
        c.execute(text("DELETE FROM official.source WHERE source_id = :s"), {"s": sid})


# --- dimension_type integrity (row trigger) ---------------------------------
@live
def test_every_observation_member_column_accepts_only_its_own_dimension_type(conn):
    ind, f = new_indicator(conn), new_file(conn)
    members = {d: new_member(conn, d) for d in DIMENSIONS}
    for dim, col in DIMENSIONS.items():
        obs(conn, ind, f, year=2000 + len(col), **{col: members[dim]})  # right type: accepted
        wrong = members["sector" if dim != "sector" else "region"]
        rejected(conn, TYPE_CONSTRAINT, lambda: obs(conn, ind, f, year=1999, **{col: wrong}))


@live
def test_member_type_is_checked_on_update_and_null_means_not_applicable(conn):
    ind, f = new_indicator(conn), new_file(conn)
    gender, region = new_member(conn, "gender"), new_member(conn, "region")
    o = obs(conn, ind, f)  # all ten NULL: fine
    conn.execute(text("UPDATE official.observation SET gender_member_id = :g WHERE observation_id = :o"),
                 {"g": gender, "o": o})
    rejected(conn, TYPE_CONSTRAINT, lambda: conn.execute(
        text("UPDATE official.observation SET gender_member_id = :r WHERE observation_id = :o"),
        {"r": region, "o": o}))
    # a three-dimension row with one wrong member is rejected as a whole
    rejected(conn, TYPE_CONSTRAINT, lambda: obs(
        conn, ind, f, year=2001, gender_member_id=gender, region_member_id=new_member(conn, "region"),
        age_group_member_id=gender))


@live
def test_referenced_member_cannot_change_dimension_type_but_unreferenced_can(conn):
    ind, f = new_indicator(conn), new_file(conn)
    used, spare = new_member(conn, "gender"), new_member(conn, "gender")
    obs(conn, ind, f, gender_member_id=used)
    rejected(conn, TYPE_CONSTRAINT, lambda: conn.execute(
        text("UPDATE official.dimension_member SET dimension_type = 'sector' WHERE member_id = :m"), {"m": used}))
    conn.execute(text("UPDATE official.dimension_member SET dimension_type = 'sector' WHERE member_id = :m"),
                 {"m": spare})  # nothing points at it
    conn.execute(text("UPDATE official.dimension_member SET canonical_key = 'k2' WHERE member_id = :m"),
                 {"m": used})  # other columns stay editable


# --- existing constraints and loader-owned rules -----------------------------
@live
def test_existing_table_constraints_still_fire_with_the_new_triggers_installed(conn):
    f = new_file(conn)
    ind = new_indicator(conn)
    rejected(conn, "ck_observation_value_xor_marker", lambda: obs(conn, ind, f, value=None))
    rejected(conn, "ck_observation_row_role", lambda: obs(conn, ind, f, row_role="bogus"))
    rejected(conn, "ck_source_acquisition_state", lambda: new_source(conn, "nonsense"))
    rejected(conn, "ck_facility_geo_quality", lambda: new_facility(conn, f, geo_quality="bogus"))
    rejected(conn, "ck_facility_coordinates_both_or_neither", lambda: new_facility(conn, f, latitude=None))
    obs(conn, ind, f, year=2010)
    rejected(conn, "uq_observation_row_identity", lambda: obs(conn, ind, f, year=2010), sqlstate="23505")
    rejected(conn, "fk_observation_gender_member_id_dimension_member",
             lambda: obs(conn, ind, f, gender_member_id=-5), sqlstate="23503")
    # bed capacity storage is unchanged: "0" -> 0, "" / null -> NULL, both stay NULL-able integers
    zero, blank = new_facility(conn, f, inpatient_bed_capacity=0), new_facility(conn, f, inpatient_bed_capacity=None)
    assert q(conn, "SELECT inpatient_bed_capacity FROM official.facility WHERE facility_id IN (:a,:b) "
                   "ORDER BY facility_id", a=zero, b=blank) == [(0,), (None,)]


@live
def test_rules_the_loader_owns_are_deliberately_not_database_constraints(conn):
    """Pins the boundary: these are loader assertions (design ERD §8 items 4-5, mapping §6), so the database
    accepts them and the loader tests must catch them."""
    f_a, f_b = new_file(conn), new_file(conn)
    ind = new_indicator(conn)
    # ERD §8.4: a detail file of a *different* indicator is accepted by PostgreSQL (loader asserts the pairing)
    obs(conn, ind, f_a)
    obs(conn, new_indicator(conn), f_a)
    # §3.3 / CD-7: a reconciliation mismatch never blocks a load
    mem = gender_members(conn)
    put(conn, ind, f_b, 2020, {"m": 1, "f": 1, "total": 99}, mem)
    # the two standards that must load as `blocked` are a loader/manifest rule, not a schema rule
    new_source(conn, "researched", source_id="SRC-02-IFHAS")
    check_deferred(conn)


# --- migration 0003: upgrade, downgrade, data preservation -------------------
OFFICIAL_TABLES = ["source", "source_file", "region", "indicator", "indicator_dimension", "dimension_member",
                   "observation", "facility", "license_status_map"]


def structure(eng):
    """Tables, columns, constraints and indexes of `official` (views and functions excluded)."""
    with eng.connect() as c:
        cols = c.execute(text("""SELECT table_name, column_name, data_type, is_nullable, column_default,
                                        generation_expression, identity_generation
                                 FROM information_schema.columns
                                 WHERE table_schema = 'official'
                                   AND table_name IN (SELECT tablename FROM pg_tables WHERE schemaname = 'official')
                                 ORDER BY table_name, ordinal_position""")).all()
        cons = c.execute(text("""SELECT r.relname, c.conname, pg_get_constraintdef(c.oid)
                                 FROM pg_constraint c JOIN pg_class r ON r.oid = c.conrelid
                                 JOIN pg_namespace n ON n.oid = r.relnamespace
                                 WHERE n.nspname = 'official' AND c.contype <> 't'  -- constraint triggers excluded
                                 ORDER BY 1, 2""")).all()
        idx = c.execute(text("SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'official' "
                             "ORDER BY 1")).all()
    return cols, cons, idx


def row_digest(eng):
    out = {}
    with eng.connect() as c:
        for t in OFFICIAL_TABLES:
            out[t] = c.execute(text(f"SELECT count(*), md5(coalesce(string_agg(x::text, '|' ORDER BY x::text), '')) "
                                    f"FROM official.{t} x")).one()
    return out


def catalogue(eng):
    with eng.connect() as c:
        views = {r[0] for r in c.execute(text("SELECT viewname FROM pg_views WHERE schemaname = 'official'"))}
        funcs = {r[0] for r in c.execute(text("""SELECT proname FROM pg_proc p JOIN pg_namespace n
                                                 ON n.oid = p.pronamespace WHERE n.nspname = 'official'"""))}
        trigs = {r[0] for r in c.execute(text("""SELECT tgname FROM pg_trigger t JOIN pg_class r ON r.oid = t.tgrelid
                 JOIN pg_namespace n ON n.oid = r.relnamespace WHERE n.nspname = 'official' AND NOT tgisinternal"""))}
        version = c.execute(text("SELECT version_num FROM public.alembic_version")).scalar()
    return views, funcs, trigs, version


def seed(eng):
    """Representative rows covering every official table that a view or trigger touches."""
    with eng.begin() as c:
        src = new_source(c, "dataset_obtained")
        f = new_file(c, src)
        new_source(c, "blocked")
        ind = new_indicator(c)
        gm = new_member(c, "gender", "leaf")
        obs(c, ind, f, gender_member_id=gm)
        status = new_status(c, "Active", True)
        new_facility(c, f, license_status_raw=status, inpatient_bed_capacity=0)
        new_facility(c, f, inpatient_bed_capacity=None)


@live
def test_upgrade_and_downgrade_preserve_tables_and_data():
    with scratch_database() as url:
        cfg = alembic_config()
        command.upgrade(cfg, "0002")
        eng = create_engine(url, connect_args={"connect_timeout": 60})
        try:
            seed(eng)
            struct2, data2 = structure(eng), row_digest(eng)
            assert catalogue(eng) == (set(), set(), set(), "0002")

            command.upgrade(cfg, "0003")
            assert catalogue(eng) == (VIEWS, FUNCTIONS, TRIGGERS, "0003")
            assert structure(eng) == struct2, "0003 must not change any table, column, constraint or index"
            assert row_digest(eng) == data2, "0003 must not change any row"
            with eng.connect() as c:  # the views run on the preserved data
                assert c.execute(text("SELECT count(*) FROM official.v_observation_leaf")).scalar() == 1
                assert c.execute(text("SELECT count(*) FROM official.v_facility_usable")).scalar() == 1

            command.downgrade(cfg, "0002")
            assert catalogue(eng) == (set(), set(), set(), "0002")
            assert structure(eng) == struct2 and row_digest(eng) == data2

            command.upgrade(cfg, "0004")  # 0004 replaces two views only: same catalogue, tables and rows
            assert catalogue(eng) == (VIEWS, FUNCTIONS, TRIGGERS, "0004")
            assert structure(eng) == struct2, "0004 must not change any table, column, constraint or index"
            assert row_digest(eng) == data2
            with eng.connect() as c:
                assert "not_testable_reason" in {r[0] for r in c.execute(text(
                    "SELECT column_name FROM information_schema.columns WHERE table_schema = 'official' "
                    "AND table_name = 'v_indicator_year_shape'"))}
                assert "vintage selector" in c.execute(text(
                    "SELECT obj_description('official.v_observation_current'::regclass)")).scalar().lower()

            command.upgrade(cfg, "head")  # 0005 replaces the same two views again
            assert catalogue(eng) == (VIEWS, FUNCTIONS, TRIGGERS, "0005")
            assert structure(eng) == struct2, "0005 must not change any table, column, constraint or index"
            assert row_digest(eng) == data2
            with eng.connect() as c:
                assert {"precision_tolerance", "reconciled_within_precision"} <= {r[0] for r in c.execute(text(
                    "SELECT column_name FROM information_schema.columns WHERE table_schema = 'official' "
                    "AND table_name = 'v_indicator_year_shape'"))}
            command.downgrade(cfg, "0004")  # 0004's own definition comes back
            assert catalogue(eng) == (VIEWS, FUNCTIONS, TRIGGERS, "0004")
            with eng.connect() as c:
                assert "precision_tolerance" not in {r[0] for r in c.execute(text(
                    "SELECT column_name FROM information_schema.columns WHERE table_schema = 'official' "
                    "AND table_name = 'v_indicator_year_shape'"))}

            command.downgrade(cfg, "0003")  # 0003's own definitions come back
            assert catalogue(eng) == (VIEWS, FUNCTIONS, TRIGGERS, "0003")
            with eng.connect() as c:
                assert "not_testable_reason" not in {r[0] for r in c.execute(text(
                    "SELECT column_name FROM information_schema.columns WHERE table_schema = 'official' "
                    "AND table_name = 'v_indicator_year_shape'"))}
            command.upgrade(cfg, "head")
            assert row_digest(eng) == data2

            command.check(cfg)  # no model/database drift (views and triggers are outside autogenerate)

            command.downgrade(cfg, "base")  # full round trip, then back to head on an empty database
            command.upgrade(cfg, "head")
            assert catalogue(eng)[3] == "0005"
        finally:
            eng.dispose()


@live
def test_upgrade_refuses_data_that_already_violates_the_new_invariants():
    with scratch_database() as url:
        cfg = alembic_config()
        command.upgrade(cfg, "0002")
        eng = create_engine(url, connect_args={"connect_timeout": 60})
        try:
            with eng.begin() as c:
                orphan = new_source(c, "document_obtained")  # accepted at 0002: no trigger yet
            with pytest.raises(IntegrityError, match="obtained source"):
                command.upgrade(cfg, "0003")
            assert catalogue(eng) == (set(), set(), set(), "0002")  # transactional DDL: nothing half-applied
            with eng.begin() as c:
                new_file(c, orphan, file_role="publication_workbook")
                ind, f = new_indicator(c), new_file(c)
                wrong = new_member(c, "region")
                obs(c, ind, f, gender_member_id=wrong)  # a region member in the gender column
            with pytest.raises(IntegrityError, match="wrong dimension_type"):
                command.upgrade(cfg, "0003")
            assert catalogue(eng)[3] == "0002"
            with eng.begin() as c:
                c.execute(text("DELETE FROM official.observation"))
            command.upgrade(cfg, "0003")
            assert catalogue(eng) == (VIEWS, FUNCTIONS, TRIGGERS, "0003")
        finally:
            eng.dispose()


def test_migration_0005_follows_0004_and_is_the_head():
    from alembic.script import ScriptDirectory
    script = ScriptDirectory(str(BACKEND / "migrations"))
    assert script.get_heads() == ["0005"]
    assert script.get_revision("0005").down_revision == "0004"
    assert script.get_revision("0004").down_revision == "0003"
    assert script.get_revision("0003").down_revision == "0002"
    assert [r.revision for r in script.walk_revisions()] == ["0005", "0004", "0003", "0002", "0001"]  # linear


# --- reconciliation precision tolerance (0005) -------------------------------
def precision(conn, ind):
    rows = q(conn, """SELECT period_year, cell_state, mismatch_class, difference, precision_tolerance,
                             reconciled_within_precision
                      FROM official.v_indicator_year_shape WHERE indicator_id = :i ORDER BY period_year""", i=ind)
    return {r[0]: r[1:] for r in rows}


@live
def test_precision_tolerance_boundary_is_half_unit_of_15th_significant_digit_summed_over_members(conn):
    """Values near 100 (3 integer digits) are known to 5E-13 each; three members -> 1.5E-12 in total."""
    ind, f, mem = new_indicator(conn), new_file(conn), gender_members(conn)
    put(conn, ind, f, 2001, {"m": Decimal("100"), "f": Decimal("200"), "total": Decimal("300")}, mem)  # exact
    put(conn, ind, f, 2002, {"m": Decimal("100"), "f": Decimal("200.0000000000015"), "total": Decimal("300")}, mem)
    put(conn, ind, f, 2003, {"m": Decimal("100"), "f": Decimal("200.0000000000016"), "total": Decimal("300")}, mem)
    put(conn, ind, f, 2004, {"m": Decimal("100"), "f": Decimal("199.9999999999985"), "total": Decimal("300")}, mem)
    put(conn, ind, f, 2005, {"m": Decimal("100"), "f": Decimal("199.9999999999984"), "total": Decimal("300")}, mem)
    got = precision(conn, ind)
    assert got[2001] == ("reconciles", None, 0, Decimal("0.0000000000015"), False)
    # exactly on the bound: within (inclusive), in either direction; the exact difference is still reported
    assert got[2002] == ("reconciles", None, Decimal("0.0000000000015"), Decimal("0.0000000000015"), True)
    assert got[2004] == ("reconciles", None, Decimal("-0.0000000000015"), Decimal("0.0000000000015"), True)
    # one digit beyond the bound: a mismatch, classified as before (leaves above / below, no residual member)
    assert got[2003][:3] == ("mismatch", "RC-LEAVES-ABOVE", Decimal("0.0000000000016"))
    assert got[2005][:3] == ("mismatch", "RC-RESIDUAL-BELOW", Decimal("-0.0000000000016"))
    assert got[2003][4] is False and got[2005][4] is False  # reconciled_within_precision only where it applies


@live
def test_precision_tolerance_scales_with_magnitude_and_is_not_a_global_constant(conn):
    ind, f, mem = new_indicator(conn), new_file(conn), gender_members(conn)
    # near 1E7 every member is known to 5E-8: a 9E-9 gap is representation noise (the indicator 2622 case)
    put(conn, ind, f, 2001, {"m": Decimal("5000000"), "f": Decimal("5000000.000000009"),
                             "total": Decimal("10000000")}, mem)
    # near 1 every member is known to 5E-15: the same 9E-9 gap is a real discrepancy
    put(conn, ind, f, 2002, {"m": Decimal("1"), "f": Decimal("1.000000009"), "total": Decimal("2")}, mem)
    got = precision(conn, ind)
    assert got[2001][0] == "reconciles" and got[2001][4] is True
    assert got[2002][0] == "mismatch" and got[2002][1] == "RC-LEAVES-ABOVE"


@live
def test_precision_tolerance_never_absorbs_a_unit_difference(conn):
    ind, f, mem = new_indicator(conn), new_file(conn), gender_members(conn)
    put(conn, ind, f, 2001, {"m": 13165217, "f": 4990910, "total": 18156128}, mem)  # integers, 1 apart
    put(conn, ind, f, 2002, {"m": 99999999999999, "f": 1, "total": 99999999999999}, mem)  # largest 14-digit count
    got = precision(conn, ind)
    assert got[2001][:3] == ("mismatch", "RC-RESIDUAL-BELOW", -1)
    assert got[2002][0] == "mismatch"


@live
def test_precision_tolerance_does_not_change_the_projection_or_residual_rules(conn):
    proj = new_indicator(conn, series_kind="projected")
    f, mem = new_file(conn), gender_members(conn)
    put(conn, proj, f, 2030, {"m": 1000, "f": 2000, "total": 3500}, mem)    # still RC-PROJ-ROUNDING
    put(conn, proj, f, 2027, {"m": 1000, "f": 2000, "total": 3500}, mem)    # still unresolved: no step for 2027
    got = precision(conn, proj)
    assert got[2030][:2] == ("mismatch", "RC-PROJ-ROUNDING") and got[2027][:2] == ("mismatch", None)
    ind = new_indicator(conn)
    put(conn, ind, f, 2020, {"m": 3, "f": 4, "total": 10}, mem)             # below, no residual: RC-RESIDUAL-BELOW
    put(conn, ind, f, 2021, {"m": 3, "f": 4, "ns": 1, "total": 10}, mem)    # below, residual present: unresolved
    got = precision(conn, ind)
    assert got[2020][:2] == ("mismatch", "RC-RESIDUAL-BELOW")
    assert got[2021][:2] == ("mismatch", None)


@live
def test_indicator_2622_real_values_reconcile_within_precision_and_stay_unmodified(conn):
    """The two real SCAD cases: 2016 differs by 9E-9 and 2017 by 1E-9 (Decimal, exactly as published)."""
    ind, f, mem = new_indicator(conn), new_file(conn), gender_members(conn)
    cases = {2016: ("13165217.3892964", "4990910.66883999", "881792.809562619", "19037920.867699"),
             2017: ("12632279.0089575", "4553761.68922617", "748353.853446131", "17934394.5516298")}
    for year, (a, b, c, tot) in cases.items():
        # three leaves need a third leaf member
        third = new_member(conn, "gender", "leaf", f"Third{n()}")
        for key, v in (("m", a), ("f", b)):
            obs(conn, ind, f, year=year, value=Decimal(v), gender_member_id=mem[key])
        obs(conn, ind, f, year=year, value=Decimal(c), gender_member_id=third)
        obs(conn, ind, f, year=year, value=Decimal(tot), row_role="aggregate", gender_member_id=mem["total"])
    got = precision(conn, ind)
    assert got[2016][0] == "reconciles" and got[2016][2] == Decimal("9E-9") and got[2016][4] is True
    assert got[2017][0] == "reconciles" and got[2017][2] == Decimal("1E-9") and got[2017][4] is True
    assert got[2016][3] > Decimal("9E-9") and got[2017][3] > Decimal("1E-9")
    stored = {v for (v,) in q(conn, "SELECT value FROM official.observation WHERE indicator_id = :i", i=ind)}
    assert Decimal("13165217.3892964") in stored and Decimal("19037920.867699") in stored  # nothing rewritten
