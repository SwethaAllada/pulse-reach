"""Geospatial population-intelligence tables (`population` schema) — migration 0012 (BE-33).

Own `MetaData` (like `app/models/identity.py`): PostgreSQL in `DATA_SOURCE=db`, an in-process
SQLite database with the schema name translated away in `DATA_SOURCE=memory`
(`app.services.population.store`). No foreign keys into `synthetic`, `official` or `identity`:
reseeding and memory mode must keep working; `organization_key` is the owning organization id
(`*` = the unrestricted legacy scope).

Only aggregates are stored: no patient ids, names, addresses or coordinates.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    Double,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    SmallInteger,
    String,
    Text,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.db.session import NAMING_CONVENTION
from app.models.identity import _JSON, UTCDateTime, _in

POPULATION_SCHEMA = "population"

AREA_LEVELS = ("country", "state", "district", "city", "local_area")
AREA_SOURCES = ("iso_3166", "official_region", "sdi_facility_city_label", "synthetic_patient_label")
AREA_VERIFICATION = ("verified_reference", "published_label", "synthetic_label")
RUN_STATUSES = ("running", "succeeded", "failed")
RUN_TRIGGERS = ("manual", "scheduled", "on_demand", "stale_data", "config_change")
ALERT_CATEGORIES = (
    "case_increase",
    "disease_burden",
    "prevalence",
    "preventive_coverage_low",
    "follow_up_completion_decline",
    "facility_coverage_insufficient",
)
ALERT_SEVERITIES = ("CRITICAL", "HIGH", "MODERATE", "WATCH")
ALERT_STATUSES = ("NEW", "ACKNOWLEDGED", "INVESTIGATING", "RESOLVED", "DISMISSED")
ACTIVE_ALERT_STATUSES = ("NEW", "ACKNOWLEDGED", "INVESTIGATING")
ALERT_EVENT_TYPES = ("created", "updated", "status_changed", "condition_cleared", "condition_recurred")

population_metadata = MetaData(naming_convention=NAMING_CONVENTION)


class PopulationBase(DeclarativeBase):
    metadata = population_metadata


class GeoArea(PopulationBase):
    """One geographic area of the hierarchy, derived from existing reference/patient labels."""

    __tablename__ = "geo_area"

    area_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    level: Mapped[str] = mapped_column(String(16), nullable=False)
    parent_area_id: Mapped[str | None] = mapped_column(
        ForeignKey(f"{POPULATION_SCHEMA}.geo_area.area_id", ondelete="RESTRICT")
    )
    name_en: Mapped[str] = mapped_column(Text, nullable=False)
    name_ar: Mapped[str | None] = mapped_column(Text)
    region_id: Mapped[int | None] = mapped_column(SmallInteger)
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    source_label: Mapped[str | None] = mapped_column(Text)
    verification_status: Mapped[str] = mapped_column(String(24), nullable=False)
    # Only populated from a reliable source; never estimated (none is available today).
    reference_latitude: Mapped[float | None] = mapped_column(Double)
    reference_longitude: Mapped[float | None] = mapped_column(Double)
    boundary_ref: Mapped[str | None] = mapped_column(Text)
    boundary_source: Mapped[str | None] = mapped_column(Text)
    first_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)

    __table_args__ = (
        CheckConstraint(_in("level", AREA_LEVELS), name="level"),
        CheckConstraint(_in("source", AREA_SOURCES), name="source"),
        CheckConstraint(_in("verification_status", AREA_VERIFICATION), name="verification_status"),
        CheckConstraint("(level = 'country') = (parent_area_id IS NULL)", name="parent_unless_country"),
        CheckConstraint(
            "(reference_latitude IS NULL) = (reference_longitude IS NULL)", name="reference_point_pair"
        ),
        CheckConstraint("(boundary_ref IS NULL) = (boundary_source IS NULL)", name="boundary_pair"),
        Index("ix_geo_area_level", "level"),
        Index("ix_geo_area_parent", "parent_area_id"),
        {"schema": POPULATION_SCHEMA},
    )


class AggregationRun(PopulationBase):
    """One aggregation of one organization; `snapshot` holds the persisted aggregate result."""

    __tablename__ = "aggregation_run"

    run_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_key: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    trigger: Mapped[str] = mapped_column(String(16), nullable=False)
    requested_by: Mapped[str | None] = mapped_column(String(36))
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    engine_version: Mapped[str] = mapped_column(String(16), nullable=False)
    data_version: Mapped[str | None] = mapped_column(String(64))
    config_version: Mapped[int | None] = mapped_column(Integer)
    source_run_id: Mapped[str | None] = mapped_column(Text)
    as_of: Mapped[date | None] = mapped_column(Date)
    complete_through: Mapped[date | None] = mapped_column(Date)
    latest_data_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    snapshot: Mapped[dict[str, Any] | None] = mapped_column(_JSON)
    summary: Mapped[dict[str, Any]] = mapped_column(_JSON, nullable=False, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(64))

    __table_args__ = (
        CheckConstraint(_in("status", RUN_STATUSES), name="status"),
        CheckConstraint(_in("trigger", RUN_TRIGGERS), name="trigger"),
        CheckConstraint("(status = 'running') = (finished_at IS NULL)", name="finished_unless_running"),
        CheckConstraint("status <> 'succeeded' OR snapshot IS NOT NULL", name="succeeded_has_snapshot"),
        # At most one running aggregation per organization (concurrent refresh guard).
        Index(
            "uq_aggregation_run_one_running",
            "organization_key",
            unique=True,
            postgresql_where=text("status = 'running'"),
            sqlite_where=text("status = 'running'"),
        ),
        Index("ix_aggregation_run_org_status_finished", "organization_key", "status", "finished_at"),
        {"schema": POPULATION_SCHEMA},
    )


class ThresholdConfig(PopulationBase):
    """Organization-specific hotspot/alert thresholds (defaults live in code)."""

    __tablename__ = "threshold_config"

    organization_key: Mapped[str] = mapped_column(String(40), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    thresholds: Mapped[dict[str, Any]] = mapped_column(_JSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    updated_by: Mapped[str | None] = mapped_column(String(36))

    __table_args__ = (
        CheckConstraint("version >= 1", name="version_positive"),
        {"schema": POPULATION_SCHEMA},
    )


class PopulationAlert(PopulationBase):
    __tablename__ = "population_alert"

    alert_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_key: Mapped[str] = mapped_column(String(40), nullable=False)
    dedup_key: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    area_id: Mapped[str] = mapped_column(String(96), nullable=False)
    condition_code: Mapped[str | None] = mapped_column(String(40))
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    metrics: Mapped[dict[str, Any]] = mapped_column(_JSON, nullable=False)
    thresholds: Mapped[dict[str, Any]] = mapped_column(_JSON, nullable=False)
    period_key: Mapped[str | None] = mapped_column(String(8))
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    first_detected_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    last_detected_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    data_freshness_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    condition_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    last_run_id: Mapped[str | None] = mapped_column(String(36))
    acknowledged_by: Mapped[str | None] = mapped_column(String(36))
    acknowledged_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    investigating_by: Mapped[str | None] = mapped_column(String(36))
    investigating_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    closed_by: Mapped[str | None] = mapped_column(String(36))
    closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)

    __table_args__ = (
        CheckConstraint(_in("category", ALERT_CATEGORIES), name="category"),
        CheckConstraint(_in("severity", ALERT_SEVERITIES), name="severity"),
        CheckConstraint(_in("status", ALERT_STATUSES), name="status"),
        CheckConstraint("occurrence_count >= 1", name="occurrence_count_positive"),
        CheckConstraint(
            "(status IN ('RESOLVED', 'DISMISSED')) = (closed_at IS NOT NULL)", name="closed_consistency"
        ),
        # One active alert per underlying condition (repeated runs update it instead).
        Index(
            "uq_population_alert_active_dedup",
            "organization_key",
            "dedup_key",
            unique=True,
            postgresql_where=text("status IN ('NEW', 'ACKNOWLEDGED', 'INVESTIGATING')"),
            sqlite_where=text("status IN ('NEW', 'ACKNOWLEDGED', 'INVESTIGATING')"),
        ),
        Index("ix_population_alert_org_status_severity", "organization_key", "status", "severity"),
        Index("ix_population_alert_org_area", "organization_key", "area_id"),
        Index("ix_population_alert_org_dedup", "organization_key", "dedup_key", "created_at"),
        Index("ix_population_alert_org_detected", "organization_key", "last_detected_at"),
        {"schema": POPULATION_SCHEMA},
    )


class PopulationAlertEvent(PopulationBase):
    """Append-only alert history (UPDATE/DELETE/TRUNCATE rejected in PostgreSQL)."""

    __tablename__ = "population_alert_event"

    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    alert_id: Mapped[str] = mapped_column(
        ForeignKey(f"{POPULATION_SCHEMA}.population_alert.alert_id", ondelete="RESTRICT"),
        nullable=False,
    )
    organization_key: Mapped[str] = mapped_column(String(40), nullable=False)
    event_type: Mapped[str] = mapped_column(String(24), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(16))
    to_status: Mapped[str | None] = mapped_column(String(16))
    severity: Mapped[str | None] = mapped_column(String(16))
    actor_user_id: Mapped[str | None] = mapped_column(String(36))  # NULL = aggregation engine
    actor_role: Mapped[str | None] = mapped_column(String(40))
    run_id: Mapped[str | None] = mapped_column(String(36))
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)  # staff-entered status note; never audited
    details: Mapped[dict[str, Any]] = mapped_column(_JSON, nullable=False, default=dict)

    __table_args__ = (
        CheckConstraint(_in("event_type", ALERT_EVENT_TYPES), name="event_type"),
        CheckConstraint(
            "event_type <> 'status_changed' OR (to_status IS NOT NULL AND actor_user_id IS NOT NULL)",
            name="status_change_has_actor",
        ),
        Index("ix_population_alert_event_alert", "alert_id", "occurred_at"),
        {"schema": POPULATION_SCHEMA},
    )
