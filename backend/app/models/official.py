"""SQLAlchemy models for the nine `official` tables.

Canonical design: docs/phase-3-database-design.md §3 (revision 2.5).
Every foreign key is RESTRICT/RESTRICT (design §2.2: no CASCADE anywhere).
Rows are loaded by the loaders, never by migrations; nothing here loads data.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    Double,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import CHAR
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

SCHEMA = "official"

# Vocabularies repeated in more than one place.
DIMENSION_TYPES = (
    "region", "citizenship", "gender", "age_group", "cause_of_death",
    "disease_type", "measure_item", "insurance_type", "sector", "bed_type",
)
# observation member columns, one per dimension type (design §3.3).
MEMBER_COLUMNS = tuple(f"{d}_member_id" for d in DIMENSION_TYPES)


def _in(column: str, *values: str) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _fk(target: str, **kw) -> ForeignKey:
    return ForeignKey(f"{SCHEMA}.{target}", ondelete="RESTRICT", onupdate="RESTRICT", **kw)


class Source(Base):
    """One row per manifest source (24)."""

    __tablename__ = "source"
    __table_args__ = (
        CheckConstraint(
            _in("acquisition_state", "researched", "document_obtained", "dataset_obtained", "blocked", "excluded"),
            name="acquisition_state",
        ),
        CheckConstraint(
            "validation_state IS NULL OR " + _in("validation_state", "none", "structural", "clinical"),
            name="validation_state",
        ),
        {"schema": SCHEMA},
    )

    source_id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    publisher: Mapped[str] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    licence_text: Mapped[str | None] = mapped_column(Text)  # NULL = not recorded
    attribution_statement: Mapped[str | None] = mapped_column(Text)  # NULL = not recorded
    acquisition_state: Mapped[str] = mapped_column(Text)
    validation_state: Mapped[str | None] = mapped_column(Text)  # NULL = not a dataset
    fit_for_use: Mapped[bool | None] = mapped_column(Boolean)  # NULL = not assessed
    contains_data: Mapped[bool | None] = mapped_column(Boolean)
    acquisition_reason: Mapped[str | None] = mapped_column(Text)
    manifest_version: Mapped[str] = mapped_column(Text)


class SourceFile(Base):
    """One row per acquired file (215); anchor for every checksum and vintage."""

    __tablename__ = "source_file"
    __table_args__ = (
        UniqueConstraint("relative_path"),
        CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="sha256_hex"),
        CheckConstraint(
            _in(
                "file_role", "indicator_detail", "indicator_metadata", "publication_workbook",
                "facility_geojson", "catalogue", "other",
            ),
            name="file_role",
        ),
        # sha256 is deliberately NOT unique: identical bytes may appear twice.
        Index("ix_source_file_source_id_file_role", "source_id", "file_role"),
        Index("ix_source_file_sha256", "sha256"),
        {"schema": SCHEMA},
    )

    source_file_id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    source_id: Mapped[str] = mapped_column(Text, _fk("source.source_id"))
    relative_path: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(CHAR(64))
    byte_size: Mapped[int] = mapped_column(BigInteger)
    file_role: Mapped[str] = mapped_column(Text)
    # Tool-recorded RETRIEVAL time only. NULL = not recorded. Never defaulted (CD-9, D-P1 open).
    retrieved_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    source_effective_note: Mapped[str | None] = mapped_column(Text)  # free text, not a date
    contains_data: Mapped[bool] = mapped_column(Boolean)
    fit_for_use: Mapped[bool | None] = mapped_column(Boolean)
    loader_version: Mapped[str] = mapped_column(Text)
    registered_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )  # processing/load time (ours), never a source time


class Region(Base):
    """The three Abu Dhabi regions. Seeded by the loader, not by a migration."""

    __tablename__ = "region"
    __table_args__ = (
        UniqueConstraint("region_code"),
        CheckConstraint(_in("region_code", "AD", "AIN", "DHF"), name="region_code"),
        {"schema": SCHEMA},
    )

    region_id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=False)
    region_code: Mapped[str] = mapped_column(Text)
    name_en: Mapped[str] = mapped_column(Text)
    name_ar: Mapped[str | None] = mapped_column(Text)  # from source labels only
    scad_label: Mapped[str] = mapped_column(Text)
    sdi_label: Mapped[str] = mapped_column(Text)


class Indicator(Base):
    """The 86 SCAD indicators."""

    __tablename__ = "indicator"
    __table_args__ = (
        UniqueConstraint("slug"),
        CheckConstraint(
            _in("measure_kind", "count", "rate", "percentage", "ratio", "density", "unclassified"),
            name="measure_kind",
        ),
        CheckConstraint(_in("series_kind", "observed", "projected"), name="series_kind"),
        CheckConstraint(_in("periodicity", "annual"), name="periodicity"),
        CheckConstraint(
            _in("region_basis", "residence", "facility_location", "unspecified"),
            name="region_basis",
        ),
        Index("ix_indicator_measure_kind", "measure_kind"),
        Index("ix_indicator_metadata_source_file_id", "metadata_source_file_id"),
        {"schema": SCHEMA},
    )

    indicator_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)  # SCAD-owned
    slug: Mapped[str] = mapped_column(Text)
    title_en: Mapped[str] = mapped_column(Text)
    definition_en: Mapped[str | None] = mapped_column(Text)
    unit_raw: Mapped[str] = mapped_column(Text)  # verbatim, never assumed
    measure_kind: Mapped[str] = mapped_column(Text)
    # Additive across leaf members at one period only; anything but 'count' is non-additive.
    is_additive: Mapped[bool] = mapped_column(Boolean, Computed("measure_kind = 'count'", persisted=True))
    series_kind: Mapped[str] = mapped_column(Text)  # 'projected': 4866, 4868, 4869, 4870
    periodicity: Mapped[str] = mapped_column(Text)
    region_basis: Mapped[str] = mapped_column(Text)
    metadata_source_file_id: Mapped[int | None] = mapped_column(BigInteger, _fk("source_file.source_file_id"))
    statistical_population: Mapped[str | None] = mapped_column(Text)
    geographic_coverage: Mapped[str | None] = mapped_column(Text)
    calculation_method: Mapped[str | None] = mapped_column(Text)
    data_sources_text: Mapped[str | None] = mapped_column(Text)
    last_update_raw: Mapped[str | None] = mapped_column(Text)  # verbatim; '20400101' is not a date


class IndicatorDimension(Base):
    """Which dimension types each indicator uses (0-3)."""

    __tablename__ = "indicator_dimension"
    __table_args__ = (
        UniqueConstraint("indicator_id", "ordinal", name="uq_indicator_dimension_indicator_id_ordinal"),
        CheckConstraint(_in("dimension_type", *DIMENSION_TYPES), name="dimension_type"),
        CheckConstraint("ordinal BETWEEN 1 AND 3", name="ordinal_range"),
        {"schema": SCHEMA},
    )

    indicator_id: Mapped[int] = mapped_column(Integer, _fk("indicator.indicator_id"), primary_key=True)
    dimension_type: Mapped[str] = mapped_column(Text, primary_key=True)
    source_column: Mapped[str] = mapped_column(Text)
    ordinal: Mapped[int] = mapped_column(SmallInteger)


class DimensionMember(Base):
    """Every distinct label of every dimension, with its role."""

    __tablename__ = "dimension_member"
    __table_args__ = (
        UniqueConstraint(
            "dimension_type", "raw_label_en", "raw_label_ar",
            name="uq_dimension_member_label", postgresql_nulls_not_distinct=True,
        ),
        CheckConstraint(_in("dimension_type", *DIMENSION_TYPES), name="dimension_type"),
        CheckConstraint(
            _in(
                "member_role", "leaf", "aggregate", "not_stated", "missing_unknown",
                "abroad", "other", "unlabelled",
            ),
            name="member_role",
        ),
        CheckConstraint("region_id IS NULL OR dimension_type = 'region'", name="region_id_region_only"),
        CheckConstraint("age_min_months <= age_max_months", name="age_months_order"),
        CheckConstraint(_in("correction_state", "none", "pending", "applied"), name="correction_state"),
        CheckConstraint(
            "(correction_state = 'applied') = (label_corrected_en IS NOT NULL)",
            name="label_corrected_iff_applied",
        ),
        CheckConstraint(
            "correction_state <> 'applied' OR correction_basis IS NOT NULL",
            name="correction_basis_when_applied",
        ),
        Index("ix_dimension_member_dimension_type_member_role", "dimension_type", "member_role"),
        Index("ix_dimension_member_region_id", "region_id"),
        {"schema": SCHEMA},
    )

    member_id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    dimension_type: Mapped[str] = mapped_column(Text)
    raw_label_en: Mapped[str] = mapped_column(Text)  # verbatim, incl. corrupted age labels
    raw_label_ar: Mapped[str | None] = mapped_column(Text)
    canonical_key: Mapped[str] = mapped_column(Text)
    member_role: Mapped[str] = mapped_column(Text)  # only 'aggregate' is excluded from sums
    region_id: Mapped[int | None] = mapped_column(SmallInteger, _fk("region.region_id"))
    scheme_code: Mapped[str | None] = mapped_column(Text)
    age_min_months: Mapped[int | None] = mapped_column(Integer)
    age_max_months: Mapped[int | None] = mapped_column(Integer)  # NULL = open-ended
    correction_state: Mapped[str] = mapped_column(Text, server_default="none")
    label_corrected_en: Mapped[str | None] = mapped_column(Text)
    correction_basis: Mapped[str | None] = mapped_column(Text)


def _member_fk() -> Mapped[int | None]:
    return mapped_column(BigInteger, _fk("dimension_member.member_id"))  # NULL = dimension not applicable


class Observation(Base):
    """One row per published SCAD data point (API set)."""

    __tablename__ = "observation"
    __table_args__ = (
        CheckConstraint("period_year BETWEEN 1900 AND 2100", name="period_year_range"),
        CheckConstraint("period_type = 'year'", name="period_type"),
        CheckConstraint("(value IS NULL) = (value_marker_raw IS NOT NULL)", name="value_xor_marker"),
        CheckConstraint(_in("row_role", "leaf", "aggregate"), name="row_role"),
        CheckConstraint(
            "quality_flag IS NULL OR " + _in("quality_flag", "duplicate_key_conflict"),
            name="quality_flag",
        ),
        # Row identity: duplicate-key rows (indicator 3422) carry quality_flag and fall outside it.
        Index(
            "uq_observation_row_identity",
            "indicator_id", "source_file_id", "period_year", *MEMBER_COLUMNS,
            unique=True,
            postgresql_nulls_not_distinct=True,
            postgresql_where=text("quality_flag IS NULL"),
        ),
        Index("ix_observation_indicator_id_period_year", "indicator_id", "period_year"),
        Index("ix_observation_source_file_id", "source_file_id"),
        *(Index(f"ix_observation_{c}", c) for c in MEMBER_COLUMNS),
        {"schema": SCHEMA},
    )

    observation_id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    indicator_id: Mapped[int] = mapped_column(Integer, _fk("indicator.indicator_id"))
    source_file_id: Mapped[int] = mapped_column(BigInteger, _fk("source_file.source_file_id"))
    period_year: Mapped[int] = mapped_column(SmallInteger)
    period_type: Mapped[str] = mapped_column(Text)
    obs_date_raw: Mapped[str] = mapped_column(Text)  # OBS_DT verbatim
    region_member_id: Mapped[int | None] = _member_fk()
    citizenship_member_id: Mapped[int | None] = _member_fk()
    gender_member_id: Mapped[int | None] = _member_fk()
    age_group_member_id: Mapped[int | None] = _member_fk()
    cause_of_death_member_id: Mapped[int | None] = _member_fk()
    disease_type_member_id: Mapped[int | None] = _member_fk()
    measure_item_member_id: Mapped[int | None] = _member_fk()
    insurance_type_member_id: Mapped[int | None] = _member_fk()
    sector_member_id: Mapped[int | None] = _member_fk()
    bed_type_member_id: Mapped[int | None] = _member_fk()
    value: Mapped[Decimal | None] = mapped_column(Numeric)
    value_marker_raw: Mapped[str | None] = mapped_column(Text)  # meaning unassigned (D3)
    row_role: Mapped[str] = mapped_column(Text)  # 'leaf' | 'aggregate'
    source_row_ordinal: Mapped[int] = mapped_column(Integer)
    quality_flag: Mapped[str | None] = mapped_column(Text)  # NULL = clean
    loader_version: Mapped[str] = mapped_column(Text)


class LicenseStatusMap(Base):
    """Raw licence status -> grouping / operating flag, only after human review."""

    __tablename__ = "license_status_map"
    __table_args__ = (
        CheckConstraint(_in("review_state", "unreviewed", "proposed", "confirmed"), name="review_state"),
        CheckConstraint(
            "review_state = 'confirmed' OR is_operating IS NULL", name="operating_only_when_confirmed"
        ),
        CheckConstraint(
            "review_state <> 'confirmed' OR (reviewed_by IS NOT NULL AND reviewed_on IS NOT NULL "
            "AND is_operating IS NOT NULL)",
            name="confirmed_requires_review",
        ),
        {"schema": SCHEMA},
    )

    raw_value: Mapped[str] = mapped_column(Text, primary_key=True)  # verbatim, incl. typo variants
    status_group: Mapped[str | None] = mapped_column(Text)
    is_operating: Mapped[bool | None] = mapped_column(Boolean)  # NULL until confirmed
    review_state: Mapped[str] = mapped_column(Text)
    reviewed_by: Mapped[str | None] = mapped_column(Text)
    reviewed_on: Mapped[dt.date | None] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(Text)


class Facility(Base):
    """SDI health-facility register as published, one row per licence-level feature."""

    __tablename__ = "facility"
    __table_args__ = (
        UniqueConstraint("source_layer", "source_object_id", name="uq_facility_source_layer_source_object_id"),
        UniqueConstraint("ch_fid"),
        UniqueConstraint("license_no"),  # NULLs distinct: the 434 unidentified rows
        CheckConstraint(
            _in(
                "source_layer", "hospitals", "health_centres", "clinics", "pharmacy",
                "rehabilitation_center", "provision_health_service", "diagnostic_centers",
                "mobile_health_unit", "dialysis_centre",
            ),
            name="source_layer",
        ),
        CheckConstraint("license_no <> ''", name="license_no_not_blank"),
        CheckConstraint(_in("identity_status", "identified", "unidentified"), name="identity_status"),
        CheckConstraint(
            "identity_status = 'identified' OR (license_no IS NULL AND facility_name_en IS NULL)",
            name="unidentified_has_no_identity",
        ),
        CheckConstraint("inpatient_bed_capacity >= 0", name="inpatient_bed_capacity_non_negative"),
        CheckConstraint(
            _in("geo_quality", "ok", "swapped_repaired", "missing_placeholder", "out_of_bounds"),
            name="geo_quality",
        ),
        CheckConstraint(
            "geo_quality IN ('ok', 'swapped_repaired') OR (longitude IS NULL AND latitude IS NULL)",
            name="usable_coordinates_need_good_geo_quality",
        ),
        CheckConstraint("longitude IS NULL OR longitude BETWEEN 51.0 AND 56.5", name="longitude_range"),
        CheckConstraint("latitude IS NULL OR latitude BETWEEN 22.0 AND 25.5", name="latitude_range"),
        CheckConstraint("(longitude IS NULL) = (latitude IS NULL)", name="coordinates_both_or_neither"),
        Index("ix_facility_source_layer", "source_layer"),
        Index("ix_facility_region_id", "region_id"),
        Index("ix_facility_license_status_raw", "license_status_raw"),
        Index("ix_facility_source_file_id", "source_file_id"),
        Index("ix_facility_latitude_longitude", "latitude", "longitude", postgresql_where=text("latitude IS NOT NULL")),
        {"schema": SCHEMA},
    )

    facility_id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    source_layer: Mapped[str] = mapped_column(Text)
    source_object_id: Mapped[int] = mapped_column(Integer)  # OBJECTID; unique only within a layer
    ch_fid: Mapped[str] = mapped_column(Text)  # raw publisher key; never parsed into a date
    license_no: Mapped[str | None] = mapped_column(Text)  # NULL, never ''
    identity_status: Mapped[str] = mapped_column(Text)
    facility_name_en: Mapped[str | None] = mapped_column(Text)
    facility_name_ar: Mapped[str | None] = mapped_column(Text)
    type: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(Text)
    subtype: Mapped[str | None] = mapped_column(Text)
    region_id: Mapped[int | None] = mapped_column(SmallInteger, _fk("region.region_id"))
    city: Mapped[str | None] = mapped_column(Text)
    license_status_raw: Mapped[str | None] = mapped_column(Text, _fk("license_status_map.raw_value"))
    is_public_raw: Mapped[str | None] = mapped_column(Text)  # verbatim (stray 'N')
    is_public: Mapped[bool | None] = mapped_column(Boolean)  # derived
    has_insurance: Mapped[bool | None] = mapped_column(Boolean)
    # Licensed capacity (not operational beds). Typed projection of the source STRING (CD-8):
    # "0" -> 0 (source-stated zero); "<n>" -> n; "" -> NULL (not recorded, never 0); null -> NULL.
    inpatient_bed_capacity: Mapped[int | None] = mapped_column(Integer)
    beds_raw: Mapped[str | None] = mapped_column(Text)
    specialities_raw: Mapped[str | None] = mapped_column(Text)
    professionals_raw: Mapped[str | None] = mapped_column(Text)
    emergency_department: Mapped[bool | None] = mapped_column(Boolean)
    pediatric_emergency_department: Mapped[bool | None] = mapped_column(Boolean)
    maternity_emergency_care: Mapped[bool | None] = mapped_column(Boolean)
    home_care_services: Mapped[bool | None] = mapped_column(Boolean)
    source_longitude: Mapped[float | None] = mapped_column(Double)  # as published, incl. (0,0)
    source_latitude: Mapped[float | None] = mapped_column(Double)
    longitude: Mapped[float | None] = mapped_column(Double)  # usable; NULL unless geo_quality ok/swapped_repaired
    latitude: Mapped[float | None] = mapped_column(Double)
    geo_quality: Mapped[str] = mapped_column(Text)  # 'ok' = inside the bounding rectangle only
    source_file_id: Mapped[int] = mapped_column(BigInteger, _fk("source_file.source_file_id"))
    source_effective_date: Mapped[dt.date | None] = mapped_column(Date)  # NULL unless publisher states one
    transform_version: Mapped[str] = mapped_column(Text)
