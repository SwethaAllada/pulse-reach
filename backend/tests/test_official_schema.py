"""Tests for the nine `official` tables (design §3, revision 2.5).

Static tests inspect the SQLAlchemy metadata and need no database. Live tests run the
real migration against the PostgreSQL named by TEST_DATABASE_URL (a disposable database:
the module upgrades it to head) and roll every test's writes back.
"""
import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from pydantic import SecretStr
from sqlalchemy import create_engine, inspect, insert, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.schema import CheckConstraint, ForeignKeyConstraint, UniqueConstraint

from app.db import session
from app.models import Base
from app.models import official as m

BACKEND = Path(__file__).resolve().parents[1]
TABLES = {
    "source", "source_file", "region", "indicator", "indicator_dimension",
    "dimension_member", "observation", "facility", "license_status_map",
}

# Columns exactly as listed in the canonical design (§3.2-§3.4), written independently of the models.
# value = nullable?
EXPECTED = {
    "source": {
        "source_id": False, "name": False, "publisher": False, "url": True, "licence_text": True,
        "attribution_statement": True, "acquisition_state": False, "validation_state": True,
        "fit_for_use": True, "contains_data": True, "acquisition_reason": True, "manifest_version": False,
    },
    "source_file": {
        "source_file_id": False, "source_id": False, "relative_path": False, "sha256": False,
        "byte_size": False, "file_role": False, "retrieved_at": True, "source_effective_note": True,
        "contains_data": False, "fit_for_use": True, "loader_version": False, "registered_at": False,
    },
    "region": {
        "region_id": False, "region_code": False, "name_en": False, "name_ar": True,
        "scad_label": False, "sdi_label": False,
    },
    "indicator": {
        "indicator_id": False, "slug": False, "title_en": False, "definition_en": True, "unit_raw": False,
        "measure_kind": False, "is_additive": False, "series_kind": False, "periodicity": False,
        "region_basis": False, "metadata_source_file_id": True, "statistical_population": True,
        "geographic_coverage": True, "calculation_method": True, "data_sources_text": True,
        "last_update_raw": True,
    },
    "indicator_dimension": {
        "indicator_id": False, "dimension_type": False, "source_column": False, "ordinal": False,
    },
    "dimension_member": {
        "member_id": False, "dimension_type": False, "raw_label_en": False, "raw_label_ar": True,
        "canonical_key": False, "member_role": False, "region_id": True, "scheme_code": True,
        "age_min_months": True, "age_max_months": True, "correction_state": False,
        "label_corrected_en": True, "correction_basis": True,
    },
    "observation": {
        "observation_id": False, "indicator_id": False, "source_file_id": False, "period_year": False,
        "period_type": False, "obs_date_raw": False,
        **{c: True for c in m.MEMBER_COLUMNS},
        "value": True, "value_marker_raw": True, "row_role": False, "source_row_ordinal": False,
        "quality_flag": True, "loader_version": False,
    },
    "facility": {
        "facility_id": False, "source_layer": False, "source_object_id": False, "ch_fid": False,
        "license_no": True, "identity_status": False, "facility_name_en": True, "facility_name_ar": True,
        "type": True, "category": True, "subtype": True, "region_id": True, "city": True,
        "license_status_raw": True, "is_public_raw": True, "is_public": True, "has_insurance": True,
        "inpatient_bed_capacity": True, "beds_raw": True, "specialities_raw": True,
        "professionals_raw": True, "emergency_department": True, "pediatric_emergency_department": True,
        "maternity_emergency_care": True, "home_care_services": True, "source_longitude": True,
        "source_latitude": True, "longitude": True, "latitude": True, "geo_quality": False,
        "source_file_id": False, "source_effective_date": True, "transform_version": False,
    },
    "license_status_map": {
        "raw_value": False, "status_group": True, "is_operating": True, "review_state": False,
        "reviewed_by": True, "reviewed_on": True, "note": True,
    },
}

# (child table, child column, parent table, parent column)
EXPECTED_FKS = {
    ("source_file", "source_id", "source", "source_id"),
    ("indicator", "metadata_source_file_id", "source_file", "source_file_id"),
    ("indicator_dimension", "indicator_id", "indicator", "indicator_id"),
    ("dimension_member", "region_id", "region", "region_id"),
    ("observation", "indicator_id", "indicator", "indicator_id"),
    ("observation", "source_file_id", "source_file", "source_file_id"),
    *{("observation", c, "dimension_member", "member_id") for c in m.MEMBER_COLUMNS},
    ("facility", "region_id", "region", "region_id"),
    ("facility", "license_status_raw", "license_status_map", "raw_value"),
    ("facility", "source_file_id", "source_file", "source_file_id"),
}
NOT_NULL_FKS = {
    ("source_file", "source_id"), ("indicator_dimension", "indicator_id"),
    ("observation", "indicator_id"), ("observation", "source_file_id"), ("facility", "source_file_id"),
}

EXPECTED_UNIQUE = {  # constraint name -> columns
    "uq_source_file_relative_path": ["relative_path"],
    "uq_region_region_code": ["region_code"],
    "uq_indicator_slug": ["slug"],
    "uq_indicator_dimension_indicator_id_ordinal": ["indicator_id", "ordinal"],
    "uq_dimension_member_label": ["dimension_type", "raw_label_en", "raw_label_ar"],
    "uq_facility_source_layer_source_object_id": ["source_layer", "source_object_id"],
    "uq_facility_ch_fid": ["ch_fid"],
    "uq_facility_license_no": ["license_no"],
}

EXPECTED_CHECKS = {
    "ck_source_acquisition_state", "ck_source_validation_state",
    "ck_source_file_sha256_hex", "ck_source_file_file_role",
    "ck_region_region_code",
    "ck_indicator_measure_kind", "ck_indicator_series_kind", "ck_indicator_periodicity",
    "ck_indicator_region_basis",
    "ck_indicator_dimension_dimension_type", "ck_indicator_dimension_ordinal_range",
    "ck_dimension_member_dimension_type", "ck_dimension_member_member_role",
    "ck_dimension_member_region_id_region_only", "ck_dimension_member_age_months_order",
    "ck_dimension_member_correction_state", "ck_dimension_member_label_corrected_iff_applied",
    "ck_dimension_member_correction_basis_when_applied",
    "ck_observation_period_year_range", "ck_observation_period_type", "ck_observation_value_xor_marker",
    "ck_observation_row_role", "ck_observation_quality_flag",
    "ck_facility_source_layer", "ck_facility_license_no_not_blank", "ck_facility_identity_status",
    "ck_facility_unidentified_has_no_identity", "ck_facility_inpatient_bed_capacity_non_negative",
    "ck_facility_geo_quality", "ck_facility_usable_coordinates_need_good_geo_quality",
    "ck_facility_longitude_range", "ck_facility_latitude_range", "ck_facility_coordinates_both_or_neither",
    "ck_license_status_map_review_state", "ck_license_status_map_operating_only_when_confirmed",
    "ck_license_status_map_confirmed_requires_review",
}

EXPECTED_INDEXES = {
    "ix_source_file_source_id_file_role", "ix_source_file_sha256", "ix_indicator_measure_kind",
    "ix_indicator_metadata_source_file_id", "ix_dimension_member_dimension_type_member_role",
    "ix_dimension_member_region_id", "ix_observation_indicator_id_period_year",
    "ix_observation_source_file_id", "uq_observation_row_identity",
    *{f"ix_observation_{c}" for c in m.MEMBER_COLUMNS},
    "ix_facility_source_layer", "ix_facility_region_id", "ix_facility_license_status_raw",
    "ix_facility_source_file_id", "ix_facility_latitude_longitude",
}


# --- static (no database) ------------------------------------------------
def official_tables():
    return {t.name: t for t in Base.metadata.tables.values() if t.schema == "official"}


def test_nine_official_tables_and_nothing_else():
    assert set(official_tables()) == TABLES
    schemas = {t.schema for t in Base.metadata.tables.values()}
    assert "official" in schemas
    assert schemas <= {"official", "clinical", "synthetic"}


def test_models_match_design_columns_and_nullability():
    for name, cols in EXPECTED.items():
        table = official_tables()[name]
        assert {c.name: c.nullable for c in table.columns} == cols, name


def test_every_fk_is_restrict_and_exactly_the_designed_set():
    found = set()
    for t in official_tables().values():
        for fk in t.foreign_key_constraints:
            assert fk.ondelete == "RESTRICT" and fk.onupdate == "RESTRICT", fk.name
            (el,) = fk.elements
            found.add((t.name, el.parent.name, el.column.table.name, el.column.name))
    assert found == EXPECTED_FKS


def test_no_foreign_key_between_facility_and_observation_or_outside_official():
    for t in official_tables().values():
        for fk in t.foreign_key_constraints:
            assert fk.referred_table.schema == "official"
    assert not any(
        fk.referred_table.name == "observation" for fk in official_tables()["facility"].foreign_key_constraints
    )


def test_all_constraints_are_named_by_the_shared_convention():
    prefixes = {CheckConstraint: "ck_", UniqueConstraint: "uq_", ForeignKeyConstraint: "fk_"}
    for t in official_tables().values():
        assert t.primary_key.name == f"pk_{t.name}"
        for c in t.constraints:
            for cls, prefix in prefixes.items():
                if isinstance(c, cls):
                    assert c.name and str(c.name).startswith(prefix), (t.name, c)


def test_coordinates_are_double_precision_not_postgis():
    t = official_tables()["facility"]
    for col in ("source_longitude", "source_latitude", "longitude", "latitude"):
        assert t.c[col].type.compile(dialect=postgresql.dialect()) == "DOUBLE PRECISION"
    assert not any("geometry" in str(c.type).lower() or "geography" in str(c.type).lower()
                   for c in t.columns)


def test_measure_and_key_types():
    t = official_tables()
    d = postgresql.dialect()
    assert t["observation"].c.value.type.compile(dialect=d) == "NUMERIC"
    assert t["source_file"].c.sha256.type.compile(dialect=d) == "CHAR(64)"
    assert t["source_file"].c.retrieved_at.type.compile(dialect=d) == "TIMESTAMP WITH TIME ZONE"
    assert t["facility"].c.inpatient_bed_capacity.type.compile(dialect=d) == "INTEGER"
    for name in ("source_file", "dimension_member", "observation", "facility"):
        pk = list(t[name].primary_key.columns)[0]
        assert pk.type.compile(dialect=d) == "BIGINT" and pk.identity is not None and pk.identity.always


def test_migration_chain_is_linear_and_0001_is_untouched():
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(Config(str(BACKEND / "alembic.ini")))
    revs = [r.revision for r in script.walk_revisions()]
    assert revs[-5:] == ["0005", "0004", "0003", "0002", "0001"]
    assert script.get_revision("0005").down_revision == "0004"
    assert script.get_revision("0004").down_revision == "0003"
    assert script.get_revision("0003").down_revision == "0002"
    assert script.get_revision("0002").down_revision == "0001"
    assert script.get_revision("0001").down_revision is None


# --- live PostgreSQL -----------------------------------------------------
live = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set")


@pytest.fixture(scope="module")
def engine():
    url = os.environ["TEST_DATABASE_URL"]
    mp = pytest.MonkeyPatch()
    mp.setattr(session.settings, "database_url", SecretStr(url))
    mp.setattr(session.settings, "db_connect_timeout", 60)
    command.upgrade(Config(str(BACKEND / "alembic.ini")), "head")
    eng = create_engine(url, connect_args={"connect_timeout": 60})
    yield eng
    eng.dispose()
    mp.undo()


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


def add(conn, model, **values):
    return conn.execute(insert(model).values(**values).returning(*model.__table__.primary_key.columns)).one()[0]


def rejected(conn, model, constraint, **values):
    """The insert must fail, and fail on exactly this named constraint (or unique index)."""
    with pytest.raises(IntegrityError) as ei:
        with conn.begin_nested():
            conn.execute(insert(model).values(**values))
    assert ei.value.orig.diag.constraint_name == constraint, ei.value.orig


_n = iter(range(1, 10**6))


def n():
    return next(_n)


def new_source(conn, **o):
    return add(conn, m.Source, **{"source_id": f"SRC-T{n()}", "name": "n", "publisher": "p",
                                  "acquisition_state": "dataset_obtained", "manifest_version": "2.0.0", **o})


def new_file(conn, source_id=None, **o):
    return add(conn, m.SourceFile, **{
        "source_id": source_id or new_source(conn), "relative_path": f"raw/f{n()}.json", "sha256": "a" * 64,
        "byte_size": 1, "file_role": "indicator_detail", "contains_data": True, "loader_version": "t", **o})


def new_region(conn, **o):
    i = n() % 30000
    return add(conn, m.Region, **{"region_id": i, "region_code": "AD", "name_en": "Abu Dhabi",
                                  "scad_label": "Abu Dhabi Region", "sdi_label": "Abu Dhabi", **o})


def new_indicator(conn, **o):
    i = n()
    return add(conn, m.Indicator, **{"indicator_id": i, "slug": f"{i}_slug", "title_en": "t", "unit_raw": "Number",
                                     "measure_kind": "count", "series_kind": "observed", "periodicity": "annual",
                                     "region_basis": "residence", **o})


def new_member(conn, **o):
    return add(conn, m.DimensionMember, **{"dimension_type": "gender", "raw_label_en": f"L{n()}",
                                           "canonical_key": "k", "member_role": "leaf", **o})


def obs_values(conn, indicator_id, file_id, **o):
    return {"indicator_id": indicator_id, "source_file_id": file_id, "period_year": 2025, "period_type": "year",
            "obs_date_raw": "2025-12-31", "value": 1, "row_role": "leaf", "source_row_ordinal": n(),
            "loader_version": "t", **o}


def new_facility(conn, file_id=None, **o):
    i = n()
    return add(conn, m.Facility, **{
        "source_layer": "hospitals", "source_object_id": i, "ch_fid": f"DOH_{i}", "identity_status": "identified",
        "geo_quality": "ok", "source_file_id": file_id or new_file(conn), "transform_version": "t", **o})


@pytest.fixture
def pg(conn):
    return lambda sql, **p: conn.execute(text(sql), p)


@live
def test_schema_placement(engine):
    insp = inspect(engine)
    assert set(insp.get_table_names(schema="official")) == TABLES
    assert insp.get_table_names(schema="public") == ["alembic_version"]
    import app.models.clinical  # noqa: F401
    import app.models.synthetic  # noqa: F401
    from app.models.base import Base

    for other in ("clinical", "synthetic"):  # later schemas hold exactly their own designed tables
        designed = {t.name for t in Base.metadata.tables.values() if t.schema == other}
        assert set(insp.get_table_names(schema=other)) == designed
    with engine.connect() as c:
        outside = c.execute(text("""
            SELECT count(*) FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid
            JOIN pg_namespace tn ON tn.oid = t.relnamespace
            JOIN pg_class r ON r.oid = c.confrelid JOIN pg_namespace rn ON rn.oid = r.relnamespace
            WHERE c.contype = 'f' AND tn.nspname = 'official' AND rn.nspname <> 'official'""")).scalar()
        postgis = c.execute(text("SELECT count(*) FROM pg_extension WHERE extname LIKE 'postgis%'")).scalar()
    assert outside == 0 and postgis == 0


@live
def test_live_columns_nullability_and_types(engine):
    insp = inspect(engine)
    for name, cols in EXPECTED.items():
        got = {c["name"]: c["nullable"] for c in insp.get_columns(name, schema="official")}
        assert got == cols, name
    with engine.connect() as c:
        types = dict(c.execute(text("""SELECT column_name || '.' || table_name, data_type FROM information_schema.columns
                                       WHERE table_schema = 'official'""")).all())
    for col in ("source_longitude", "source_latitude", "longitude", "latitude"):
        assert types[f"{col}.facility"] == "double precision"
    assert types["value.observation"] == "numeric"
    assert types["sha256.source_file"] == "character"
    assert types["retrieved_at.source_file"] == "timestamp with time zone"
    assert types["inpatient_bed_capacity.facility"] == "integer"
    assert types["region_id.region"] == "smallint"


@live
def test_live_identity_and_generated_columns(engine):
    with engine.connect() as c:
        ident = dict(c.execute(text("""SELECT table_name, identity_generation FROM information_schema.columns
            WHERE table_schema='official' AND identity_generation IS NOT NULL""")).all())
        gen = c.execute(text("""SELECT table_name, column_name, generation_expression FROM information_schema.columns
            WHERE table_schema='official' AND is_generated='ALWAYS'""")).all()
    assert ident == {t: "ALWAYS" for t in ("source_file", "dimension_member", "observation", "facility")}
    assert [(t, col) for t, col, _ in gen] == [("indicator", "is_additive")]


@live
def test_live_foreign_keys_exist_and_restrict(engine):
    with engine.connect() as c:
        rows = c.execute(text("""
            SELECT t.relname, a.attname, r.relname, ra.attname, c.confdeltype, c.confupdtype, c.conname
            FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid JOIN pg_namespace tn ON tn.oid = t.relnamespace
            JOIN pg_class r ON r.oid = c.confrelid
            JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]
            JOIN pg_attribute ra ON ra.attrelid = c.confrelid AND ra.attnum = c.confkey[1]
            WHERE c.contype = 'f' AND tn.nspname = 'official'""")).all()
    assert {r[:4] for r in rows} == EXPECTED_FKS
    assert {(r[4], r[5]) for r in rows} == {("r", "r")}
    for t, col, parent, _, _, _, name in rows:
        assert name == f"fk_{t}_{col}_{parent}"
    insp = inspect(engine)
    for t, col in NOT_NULL_FKS:
        assert not {c["name"]: c for c in insp.get_columns(t, schema="official")}[col]["nullable"]


@live
def test_fk_rejects_orphans_and_blocks_parent_delete(conn):
    rejected(conn, m.SourceFile, "fk_source_file_source_id_source", source_id="NOPE", relative_path="x",
             sha256="a" * 64, byte_size=1, file_role="other", contains_data=True, loader_version="t")
    f = new_file(conn)
    ind = new_indicator(conn)
    mem = new_member(conn)
    add(conn, m.Observation, **obs_values(conn, ind, f, gender_member_id=mem))
    rejected(conn, m.Observation, "fk_observation_gender_member_id_dimension_member",
             **obs_values(conn, ind, f, gender_member_id=-1))
    rejected(conn, m.Observation, "fk_observation_indicator_id_indicator", **obs_values(conn, -1, f))
    rejected(conn, m.Facility, "fk_facility_license_status_raw_license_status_map",
             source_layer="clinics", source_object_id=1, ch_fid="Z1", identity_status="identified",
             geo_quality="ok", source_file_id=f, transform_version="t", license_status_raw="Never Seen")
    for model, key, ident in ((m.DimensionMember, "member_id", mem), (m.Indicator, "indicator_id", ind),
                              (m.SourceFile, "source_file_id", f)):
        with pytest.raises(IntegrityError) as ei:  # RESTRICT: no cascade, no silent delete
            with conn.begin_nested():
                conn.execute(model.__table__.delete().where(model.__table__.c[key] == ident))
        assert ei.value.orig.sqlstate == "23503"  # foreign_key_violation; confdeltype is checked separately


@live
def test_nullable_fks_accept_null(conn):
    ind = new_indicator(conn)  # metadata_source_file_id NULL: 15 indicators have no workbook
    f = new_file(conn)
    add(conn, m.Observation, **obs_values(conn, ind, f))  # all ten member columns NULL = not applicable
    new_facility(conn, f, identity_status="unidentified")  # region_id and license_status_raw NULL


@live
def test_live_unique_constraints_and_indexes(engine):
    with engine.connect() as c:
        uq = {r[0]: list(r[1]) for r in c.execute(text("""
            SELECT c.conname, array_agg(a.attname ORDER BY k.ord)
            FROM pg_constraint c JOIN pg_namespace n ON n.oid = c.connamespace
            CROSS JOIN LATERAL unnest(c.conkey) WITH ORDINALITY k(attnum, ord)
            JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.attnum
            WHERE c.contype = 'u' AND n.nspname = 'official' GROUP BY c.conname"""))}
        idx = {r[0]: r[1] for r in c.execute(text(
            "SELECT indexname, indexdef FROM pg_indexes WHERE schemaname='official'"))}
        ck = {r[0] for r in c.execute(text("""SELECT c.conname FROM pg_constraint c JOIN pg_namespace n
            ON n.oid=c.connamespace WHERE c.contype='c' AND n.nspname='official'"""))}
    assert uq == EXPECTED_UNIQUE
    assert EXPECTED_INDEXES <= set(idx)
    assert "NULLS NOT DISTINCT" in idx["uq_dimension_member_label"]
    ident = idx["uq_observation_row_identity"]
    assert "UNIQUE" in ident and "NULLS NOT DISTINCT" in ident and "WHERE (quality_flag IS NULL)" in ident
    assert "WHERE (latitude IS NOT NULL)" in idx["ix_facility_latitude_longitude"]
    assert not any("sha256" in d and "UNIQUE" in d for d in idx.values())  # sha256 is deliberately not unique
    assert ck == EXPECTED_CHECKS


@live
def test_unique_behaviour_provenance_and_facility(conn):
    s = new_source(conn)
    new_file(conn, s, relative_path="raw/same.json")
    rejected(conn, m.SourceFile, "uq_source_file_relative_path", source_id=s, relative_path="raw/same.json",
             sha256="b" * 64, byte_size=1, file_role="other", contains_data=True, loader_version="t")
    new_file(conn, s, sha256="a" * 64)  # identical bytes under another path are allowed
    new_file(conn, s, sha256="a" * 64)
    f = new_file(conn)
    new_facility(conn, f, source_layer="clinics", source_object_id=7, license_no="L1")
    rejected(conn, m.Facility, "uq_facility_source_layer_source_object_id", source_layer="clinics",
             source_object_id=7, ch_fid="OTHER", identity_status="identified", geo_quality="ok",
             source_file_id=f, transform_version="t")
    new_facility(conn, f, source_layer="pharmacy", source_object_id=7)  # OBJECTID unique only within a layer


@live
def test_unique_license_no_and_ch_fid(conn):
    f = new_file(conn)
    new_facility(conn, f, license_no="LIC-1", ch_fid="CH-1")
    base = dict(source_layer="clinics", identity_status="identified", geo_quality="ok", source_file_id=f,
                transform_version="t")
    rejected(conn, m.Facility, "uq_facility_license_no", source_object_id=n(), ch_fid="CH-2", license_no="LIC-1", **base)
    rejected(conn, m.Facility, "uq_facility_ch_fid", source_object_id=n(), ch_fid="CH-1", license_no="LIC-2", **base)
    for _ in range(3):  # NULL licence numbers never collide (the 434 unidentified rows)
        new_facility(conn, f, identity_status="unidentified")


@live
def test_unique_region_indicator_dimension_and_member(conn):
    new_region(conn, region_id=1, region_code="AD")
    rejected(conn, m.Region, "uq_region_region_code", region_id=2, region_code="AD", name_en="x",
             scad_label="x", sdi_label="x")
    ind = new_indicator(conn, slug="dup")
    rejected(conn, m.Indicator, "uq_indicator_slug", indicator_id=n(), slug="dup", title_en="t", unit_raw="u",
             measure_kind="count", series_kind="observed", periodicity="annual", region_basis="residence")
    add(conn, m.IndicatorDimension, indicator_id=ind, dimension_type="gender", source_column="GENDER_EN", ordinal=1)
    rejected(conn, m.IndicatorDimension, "pk_indicator_dimension", indicator_id=ind, dimension_type="gender",
             source_column="GENDER_EN", ordinal=2)
    rejected(conn, m.IndicatorDimension, "uq_indicator_dimension_indicator_id_ordinal", indicator_id=ind,
             dimension_type="region", source_column="REGION_EN", ordinal=1)
    # NULLS NOT DISTINCT: a repeated (type, en, NULL ar) label is a duplicate
    new_member(conn, raw_label_en="Male", raw_label_ar=None)
    rejected(conn, m.DimensionMember, "uq_dimension_member_label", dimension_type="gender", raw_label_en="Male",
             raw_label_ar=None, canonical_key="male", member_role="leaf")
    new_member(conn, raw_label_en="Male", raw_label_ar="ذكر")  # a different Arabic label is a different member
    new_member(conn, dimension_type="citizenship", raw_label_en="Male", raw_label_ar=None)  # other dimension


@live
def test_observation_row_identity_and_partial_unique_index(conn):
    ind, f1, f2 = new_indicator(conn), new_file(conn), new_file(conn)
    reg, cit, gen = (new_member(conn, dimension_type=d) for d in ("region", "citizenship", "gender"))
    cell = dict(region_member_id=reg, citizenship_member_id=cit, gender_member_id=gen)
    add(conn, m.Observation, **obs_values(conn, ind, f1, **cell))
    rejected(conn, m.Observation, "uq_observation_row_identity", **obs_values(conn, ind, f1, **cell))
    add(conn, m.Observation, **obs_values(conn, ind, f2, **cell))  # another vintage of the same cell coexists
    add(conn, m.Observation, **obs_values(conn, ind, f1, period_year=2024, **cell))
    # NULL dimensions compare equal (NULLS NOT DISTINCT): two all-NULL rows for one year are duplicates
    add(conn, m.Observation, **obs_values(conn, ind, f1, period_year=2000))
    rejected(conn, m.Observation, "uq_observation_row_identity", **obs_values(conn, ind, f1, period_year=2000))
    # duplicate-key conflicts (indicator 3422) are loaded flagged and fall outside the index
    for v in (1, 1708):
        add(conn, m.Observation, **obs_values(conn, ind, f1, period_year=1999, value=v,
                                              quality_flag="duplicate_key_conflict", **cell))


@live
def test_check_constraints_provenance_and_vocabularies(conn):
    bad = {"source_id": "S-bad", "name": "n", "publisher": "p", "manifest_version": "1"}
    rejected(conn, m.Source, "ck_source_acquisition_state", acquisition_state="downloaded", **bad)
    rejected(conn, m.Source, "ck_source_validation_state", acquisition_state="blocked", validation_state="maybe", **bad)
    for state in ("researched", "document_obtained", "dataset_obtained", "blocked", "excluded"):
        new_source(conn, acquisition_state=state)
    f = dict(source_id=new_source(conn), byte_size=1, contains_data=True, loader_version="t")
    for sha in ("A" * 64, "a" * 63, "g" * 64, ""):
        rejected(conn, m.SourceFile, "ck_source_file_sha256_hex", relative_path=f"p{n()}", sha256=sha,
                 file_role="other", **f)
    rejected(conn, m.SourceFile, "ck_source_file_file_role", relative_path=f"p{n()}", sha256="a" * 64,
             file_role="zip", **f)
    rejected(conn, m.Region, "ck_region_region_code", region_id=9, region_code="DXB", name_en="x",
             scad_label="x", sdi_label="x")
    row = dict(indicator_id=n(), title_en="t", unit_raw="u", measure_kind="count", series_kind="observed",
               periodicity="annual", region_basis="residence")
    for col, bad_value, name in (("measure_kind", "total", "ck_indicator_measure_kind"),
                                 ("series_kind", "forecast", "ck_indicator_series_kind"),
                                 ("periodicity", "monthly", "ck_indicator_periodicity"),
                                 ("region_basis", "birth", "ck_indicator_region_basis")):
        rejected(conn, m.Indicator, name, **{**row, "slug": f"s{n()}", col: bad_value})
    ind = new_indicator(conn)
    rejected(conn, m.IndicatorDimension, "ck_indicator_dimension_dimension_type", indicator_id=ind,
             dimension_type="nationality", source_column="x", ordinal=1)
    for o in (0, 4):
        rejected(conn, m.IndicatorDimension, "ck_indicator_dimension_ordinal_range", indicator_id=ind,
                 dimension_type="gender", source_column="x", ordinal=o)


@live
def test_check_constraints_dimension_member(conn):
    base = dict(dimension_type="age_group", canonical_key="k", member_role="leaf")
    rejected(conn, m.DimensionMember, "ck_dimension_member_dimension_type", **{**base, "dimension_type": "x"}, raw_label_en="a")
    rejected(conn, m.DimensionMember, "ck_dimension_member_member_role", **{**base, "member_role": "total"}, raw_label_en="b")
    r = new_region(conn)
    rejected(conn, m.DimensionMember, "ck_dimension_member_region_id_region_only", **base, raw_label_en="c", region_id=r)
    new_member(conn, dimension_type="region", raw_label_en="Abu Dhabi Region", region_id=r)
    rejected(conn, m.DimensionMember, "ck_dimension_member_age_months_order", **base, raw_label_en="d",
             age_min_months=12, age_max_months=11)
    new_member(conn, **{**base, "raw_label_en": "80+"}, age_min_months=960, age_max_months=None)  # open-ended
    new_member(conn, **{**base, "raw_label_en": "<1"}, age_min_months=0, age_max_months=11)
    rejected(conn, m.DimensionMember, "ck_dimension_member_correction_state", **base, raw_label_en="e",
             correction_state="done")
    # applied <=> corrected label present; applied needs its basis
    rejected(conn, m.DimensionMember, "ck_dimension_member_label_corrected_iff_applied", **base, raw_label_en="f",
             correction_state="applied", correction_basis="SCAD email")
    rejected(conn, m.DimensionMember, "ck_dimension_member_label_corrected_iff_applied", **base, raw_label_en="g",
             correction_state="pending", label_corrected_en="5-9")
    rejected(conn, m.DimensionMember, "ck_dimension_member_correction_basis_when_applied", **base, raw_label_en="h",
             correction_state="applied", label_corrected_en="5-9")
    new_member(conn, **base, raw_label_en="i", correction_state="applied", label_corrected_en="5-9",
               correction_basis="SCAD confirmation ref")


@live
def test_check_constraints_observation(conn):
    ind, f = new_indicator(conn), new_file(conn)
    for y in (1899, 2101):
        rejected(conn, m.Observation, "ck_observation_period_year_range", **obs_values(conn, ind, f, period_year=y))
    rejected(conn, m.Observation, "ck_observation_period_type", **obs_values(conn, ind, f, period_type="month"))
    rejected(conn, m.Observation, "ck_observation_row_role", **obs_values(conn, ind, f, row_role="total"))
    rejected(conn, m.Observation, "ck_observation_quality_flag", **obs_values(conn, ind, f, quality_flag="bad"))
    # a value and a marker are mutually exclusive, and one of them is required
    rejected(conn, m.Observation, "ck_observation_value_xor_marker", **obs_values(conn, ind, f, value=None))
    rejected(conn, m.Observation, "ck_observation_value_xor_marker", **obs_values(conn, ind, f, value=5, value_marker_raw="-"))
    add(conn, m.Observation, **obs_values(conn, ind, f, period_year=2001, value=None, value_marker_raw="-"))
    add(conn, m.Observation, **obs_values(conn, ind, f, period_year=2002, value=None, value_marker_raw=":"))


@live
def test_check_constraints_facility(conn):
    f = new_file(conn)
    base = dict(source_layer="clinics", identity_status="identified", geo_quality="ok", source_file_id=f,
                transform_version="t")

    def row(**o):
        return {**base, "source_object_id": n(), "ch_fid": f"C{n()}", **o}

    rejected(conn, m.Facility, "ck_facility_source_layer", **row(source_layer="spa"))
    rejected(conn, m.Facility, "ck_facility_identity_status", **row(identity_status="unknown"))
    rejected(conn, m.Facility, "ck_facility_license_no_not_blank", **row(license_no=""))
    rejected(conn, m.Facility, "ck_facility_unidentified_has_no_identity", **row(identity_status="unidentified", license_no="L"))
    rejected(conn, m.Facility, "ck_facility_unidentified_has_no_identity",
             **row(identity_status="unidentified", facility_name_en="N"))
    rejected(conn, m.Facility, "ck_facility_geo_quality", **row(geo_quality="good"))
    rejected(conn, m.Facility, "ck_facility_inpatient_bed_capacity_non_negative", **row(inpatient_bed_capacity=-1))
    for lon in (50.99, 56.51):
        rejected(conn, m.Facility, "ck_facility_longitude_range", **row(longitude=lon, latitude=24.0))
    for lat in (21.99, 25.51):
        rejected(conn, m.Facility, "ck_facility_latitude_range", **row(longitude=54.0, latitude=lat))
    rejected(conn, m.Facility, "ck_facility_coordinates_both_or_neither", **row(longitude=54.0))
    rejected(conn, m.Facility, "ck_facility_coordinates_both_or_neither", **row(latitude=24.0))
    for q in ("missing_placeholder", "out_of_bounds"):  # usable coordinates only for ok / swapped_repaired
        rejected(conn, m.Facility, "ck_facility_usable_coordinates_need_good_geo_quality",
                 **row(geo_quality=q, longitude=54.0, latitude=24.0))
    for lon, lat in ((51.0, 22.0), (56.5, 25.5)):  # bounds are inclusive
        new_facility(conn, f, longitude=lon, latitude=lat)
    new_facility(conn, f, geo_quality="swapped_repaired", longitude=54.4, latitude=24.4)


@live
def test_check_constraints_license_status_map(conn):
    rejected(conn, m.LicenseStatusMap, "ck_license_status_map_review_state", raw_value="x", review_state="approved")
    rejected(conn, m.LicenseStatusMap, "ck_license_status_map_operating_only_when_confirmed", raw_value="Active",
             review_state="proposed", is_operating=True)
    rejected(conn, m.LicenseStatusMap, "ck_license_status_map_operating_only_when_confirmed", raw_value="Active",
             review_state="unreviewed", is_operating=False)
    for missing in ({"reviewed_by": None}, {"reviewed_on": None}, {"is_operating": None}):
        vals = {"reviewed_by": "R", "reviewed_on": "2026-11-15", "is_operating": True, **missing}
        rejected(conn, m.LicenseStatusMap, "ck_license_status_map_confirmed_requires_review", raw_value="Active",
                 review_state="confirmed", **vals)
    add(conn, m.LicenseStatusMap, raw_value="Active", review_state="confirmed", is_operating=True,
        reviewed_by="R", reviewed_on="2026-11-15")
    add(conn, m.LicenseStatusMap, raw_value="Expired", review_state="unreviewed")  # is_operating stays NULL


# --- preservation of source values --------------------------------------
@live
def test_bed_capacity_zero_blank_null_and_positive(conn, pg):
    """Typed projection of the string source field (CD-8): "0" -> 0, "" -> NULL, null -> NULL, "n" -> n."""
    f = new_file(conn)
    cases = {"zero": 0, "blank": None, "null": None, "pos": 111}
    for key, val in cases.items():
        new_facility(conn, f, ch_fid=f"bed-{key}", inpatient_bed_capacity=val, beds_raw=repr(val))
    got = dict(pg("SELECT ch_fid, inpatient_bed_capacity FROM official.facility WHERE ch_fid LIKE 'bed-%'").all())
    assert got == {f"bed-{k}": v for k, v in cases.items()}
    assert got["bed-zero"] == 0 and got["bed-zero"] is not None  # a source-stated zero is not "not recorded"
    assert got["bed-blank"] is None  # never coerced to 0


@live
def test_all_original_licence_status_values_are_preserved(conn, pg):
    raw = ["Active", "About to Expire", "Temporary Closed", "Preliminary - Cancelled by Law",
           "Preliminary -Cancelled by Law", "Cancelled", "Expired"]  # note the typo variant: its own value
    for v in raw:
        add(conn, m.LicenseStatusMap, raw_value=v, review_state="unreviewed")
    f = new_file(conn)
    for v in raw:
        new_facility(conn, f, license_status_raw=v)
    assert {r[0] for r in pg("SELECT raw_value FROM official.license_status_map")} == set(raw)
    used = {r[0] for r in pg("SELECT DISTINCT license_status_raw FROM official.facility WHERE license_status_raw IS NOT NULL")}
    assert used == set(raw) and len(used) == len(raw)
    assert pg("SELECT count(*) FROM official.license_status_map WHERE is_operating IS NOT NULL").scalar() == 0


@live
def test_original_and_corrected_coordinates_are_both_kept(conn):
    f = new_file(conn)
    placeholder = new_facility(conn, f, geo_quality="missing_placeholder", source_longitude=0.0, source_latitude=0.0)
    oob = new_facility(conn, f, geo_quality="out_of_bounds", source_longitude=37.76, source_latitude=26.75)
    swapped = new_facility(conn, f, geo_quality="swapped_repaired", source_longitude=24.4539123456789,
                           source_latitude=54.3773438123456, longitude=54.3773438123456, latitude=24.4539123456789)
    rows = {r.facility_id: r for r in conn.execute(select(m.Facility.__table__).where(
        m.Facility.facility_id.in_([placeholder, oob, swapped])))}
    assert (rows[placeholder].source_longitude, rows[placeholder].longitude) == (0.0, None)  # as published vs unusable
    assert (rows[oob].source_longitude, rows[oob].source_latitude) == (37.76, 26.75)  # out of the usable range
    assert rows[oob].longitude is None and rows[oob].latitude is None
    s = rows[swapped]  # full DOUBLE PRECISION round trip, as-published pair differs from usable pair
    assert (s.source_longitude, s.source_latitude) == (24.4539123456789, 54.3773438123456)
    assert (s.longitude, s.latitude) == (54.3773438123456, 24.4539123456789)


@live
def test_unidentified_rows_keep_nulls_and_raw_text(conn, pg):
    f = new_file(conn)
    u = new_facility(conn, f, source_layer="rehabilitation_center", identity_status="unidentified",
                     ch_fid="DOH_15_10_2026_1#1#1", region_id=None, license_status_raw=None, is_public_raw="N")
    r = pg("SELECT license_no, region_id, license_status_raw, is_public_raw, is_public, source_effective_date, "
           "ch_fid FROM official.facility WHERE facility_id = :i", i=u).one()
    assert tuple(r) == (None, None, None, "N", None, None, "DOH_15_10_2026_1#1#1")  # verbatim, nothing derived


@live
def test_raw_labels_and_numeric_values_preserved(conn, pg):
    ind, f = new_indicator(conn, last_update_raw="20400101", unit_raw="Per 1,000 live births"), new_file(conn)
    m1 = new_member(conn, dimension_type="age_group", raw_label_en="2026-05-09", canonical_key="2026-05-09",
                    correction_state="pending")  # corrupted label kept verbatim, bounds untouched
    m2 = new_member(conn, dimension_type="citizenship", raw_label_en="(unlabelled)", member_role="unlabelled",
                    canonical_key="(unlabelled)")
    add(conn, m.Observation, **obs_values(conn, ind, f, value="6.0240963855", age_group_member_id=m1))
    add(conn, m.Observation, **obs_values(conn, ind, f, period_year=2024, value=0, citizenship_member_id=m2))
    assert pg("SELECT value::text FROM official.observation WHERE period_year = 2025 AND indicator_id = :i", i=ind).scalar() == "6.0240963855"
    assert pg("SELECT value FROM official.observation WHERE period_year = 2024 AND indicator_id = :i", i=ind).scalar() == 0
    lab = pg("SELECT raw_label_en, correction_state, label_corrected_en, age_min_months, age_max_months "
             "FROM official.dimension_member WHERE member_id = :i", i=m1).one()
    assert tuple(lab) == ("2026-05-09", "pending", None, None, None)
    assert pg("SELECT last_update_raw, unit_raw FROM official.indicator WHERE indicator_id = :i", i=ind).one() == (
        "20400101", "Per 1,000 live births")


@live
def test_retrieval_time_is_never_defaulted(conn, pg):
    f = new_file(conn)
    assert pg("SELECT retrieved_at, source_effective_note FROM official.source_file WHERE source_file_id = :i", i=f).one() == (None, None)
    assert pg("SELECT registered_at IS NOT NULL FROM official.source_file WHERE source_file_id = :i", i=f).scalar()
    fac = new_facility(conn, f)
    assert pg("SELECT source_effective_date FROM official.facility WHERE facility_id = :i", i=fac).scalar() is None


# --- aggregate vs leaf, observed vs projected ---------------------------
@live
def test_projected_and_observed_indicators_are_distinguishable(conn, pg):
    for i, kind in ((4866, "projected"), (4868, "projected"), (3916, "observed")):
        new_indicator(conn, indicator_id=10_000_000 + i, slug=f"{i}_s", series_kind=kind)
    f = new_file(conn)
    for i in (4866, 3916):
        add(conn, m.Observation, **obs_values(conn, 10_000_000 + i, f, period_year=2024, value=100))
    rows = pg("SELECT i.indicator_id - 10000000, i.series_kind FROM official.observation o "
              "JOIN official.indicator i USING (indicator_id) WHERE o.indicator_id > 10000000 "
              "AND o.indicator_id < 10005000 ORDER BY 1").all()
    assert [tuple(r) for r in rows] == [(3916, "observed"), (4866, "projected")]
    # the 2024 base-year figure exists in both series; the flag keeps them apart
    observed = pg("SELECT count(*) FROM official.observation o JOIN official.indicator i USING (indicator_id) "
                  "WHERE i.series_kind = 'observed' AND o.period_year = 2024 AND i.indicator_id > 10000000 "
                  "AND i.indicator_id < 10005000").scalar()
    assert observed == 1
    rejected(conn, m.Indicator, "ck_indicator_series_kind", indicator_id=n(), slug="bad", title_en="t",
             unit_raw="u", measure_kind="count", series_kind="estimated", periodicity="annual",
             region_basis="residence")


@live
def test_is_additive_is_derived_from_measure_kind(conn, pg):
    for kind in ("count", "rate", "percentage", "ratio", "density", "unclassified"):
        ident = new_indicator(conn, measure_kind=kind)
        assert pg("SELECT is_additive FROM official.indicator WHERE indicator_id = :i", i=ident).scalar() is (kind == "count")
    with pytest.raises(DBAPIError):  # a generated column cannot be written
        with conn.begin_nested():
            conn.execute(insert(m.Indicator).values(indicator_id=n(), slug="g", title_en="t", unit_raw="u",
                                                    measure_kind="rate", series_kind="observed", periodicity="annual",
                                                    region_basis="residence", is_additive=True))


@live
def test_aggregate_and_leaf_rows_coexist_and_stay_distinguishable(conn, pg):
    ind, f = new_indicator(conn), new_file(conn)
    total = new_member(conn, dimension_type="citizenship", raw_label_en="Total", member_role="aggregate")
    emirati = new_member(conn, dimension_type="citizenship", raw_label_en="Emirati", member_role="leaf")
    not_stated = new_member(conn, dimension_type="citizenship", raw_label_en="Not Stated", member_role="not_stated")
    add(conn, m.Observation, **obs_values(conn, ind, f, value=100, row_role="aggregate", citizenship_member_id=total))
    add(conn, m.Observation, **obs_values(conn, ind, f, value=60, row_role="leaf", citizenship_member_id=emirati))
    add(conn, m.Observation, **obs_values(conn, ind, f, value=40, row_role="leaf", citizenship_member_id=not_stated))
    rows = pg("""SELECT o.row_role, d.member_role, o.value FROM official.observation o
                 JOIN official.dimension_member d ON d.member_id = o.citizenship_member_id
                 WHERE o.indicator_id = :i ORDER BY o.value""", i=ind).all()
    assert [tuple(r) for r in rows] == [("leaf", "not_stated", 40), ("leaf", "leaf", 60), ("aggregate", "aggregate", 100)]
    # `Not Stated` carries a real number and sums with the leaves; only the aggregate is excluded
    assert pg("SELECT sum(value) FROM official.observation WHERE indicator_id = :i AND row_role = 'leaf'", i=ind).scalar() == 100
    assert pg("SELECT count(*) FROM official.observation WHERE indicator_id = :i AND row_role = 'aggregate'", i=ind).scalar() == 1
