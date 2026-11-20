"""Geospatial population intelligence (BE-33): condition records and the `population` schema.

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-20

Additive only; nothing existing is altered.

- `synthetic.condition_record`: synthetic problem-list entries (patient-owned, part of the
  reseedable run like every other synthetic table; FK to `synthetic.patient`).
- `population` schema (aggregates only; no patient identifiers): `geo_area`, `aggregation_run`
  (persisted aggregate snapshots; at most one running aggregation per organization),
  `threshold_config`, `population_alert` (one active alert per underlying condition),
  `population_alert_event` (append-only: UPDATE, DELETE and TRUNCATE rejected unless
  `pulsereach.allow_identity_reset = 'on'`, reusing `identity.reject_audit_mutation()` from 0011).
  No foreign keys into `synthetic`, `official` or `identity`.

Downgrade drops alert history and threshold configuration; it refuses while such data exists
unless explicitly allowed (`alembic -x allow_data_loss=true downgrade 0011`).

Frozen static DDL: does not import live ORM metadata (`app/models/population.py` and
`ConditionRecord` in `app/models/synthetic.py` mirror it).
"""

from __future__ import annotations

from alembic import context, op
from sqlalchemy import text

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

_TS = "TIMESTAMP WITH TIME ZONE"
_ACTIVE = "('NEW', 'ACKNOWLEDGED', 'INVESTIGATING')"

_UPGRADE = (
    """
    CREATE TABLE synthetic.condition_record (
        condition_record_id TEXT NOT NULL,
        run_id TEXT NOT NULL,
        patient_id TEXT NOT NULL,
        is_synthetic BOOLEAN DEFAULT true NOT NULL,
        condition_code TEXT NOT NULL,
        diagnosis_date DATE,
        recorded_at TIMESTAMP WITH TIME ZONE NOT NULL,
        status TEXT NOT NULL,
        resolved_date DATE,
        source_system TEXT NOT NULL,
        scenario_tag TEXT,
        CONSTRAINT pk_condition_record PRIMARY KEY (condition_record_id),
        CONSTRAINT fk_condition_record_patient_id_patient FOREIGN KEY (run_id, patient_id)
            REFERENCES synthetic.patient (run_id, patient_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
        CONSTRAINT ck_condition_record_is_synthetic CHECK (is_synthetic),
        CONSTRAINT ck_condition_record_pk_prefix CHECK (condition_record_id ~ '^SYNTH-CND-[0-9]{6,}$'),
        CONSTRAINT ck_condition_record_condition_code CHECK (condition_code IN
            ('diabetes_type_2', 'hypertension', 'dyslipidaemia', 'asthma')),
        CONSTRAINT ck_condition_record_status CHECK (status IN ('active', 'resolved', 'entered_in_error')),
        CONSTRAINT ck_condition_record_resolved_date_consistency CHECK
            ((status = 'resolved') = (resolved_date IS NOT NULL)),
        CONSTRAINT ck_condition_record_resolved_after_diagnosis CHECK
            (resolved_date IS NULL OR diagnosis_date IS NULL OR resolved_date >= diagnosis_date),
        CONSTRAINT ck_condition_record_diagnosed_before_recorded CHECK
            (diagnosis_date IS NULL OR diagnosis_date <= (recorded_at AT TIME ZONE 'UTC')::date)
    )
    """,
    "CREATE INDEX ix_condition_record_run_condition_diagnosis ON synthetic.condition_record "
    "(run_id, condition_code, diagnosis_date)",
    "CREATE INDEX ix_condition_record_patient ON synthetic.condition_record (patient_id, condition_code)",
    "CREATE INDEX ix_condition_record_recorded_at ON synthetic.condition_record (recorded_at)",
    # Aggregation filters patients by run and groups by geography.
    "CREATE INDEX ix_patient_run_region_district ON synthetic.patient (run_id, region_id, district_label)",
    "CREATE SCHEMA IF NOT EXISTS population",
    f"""
    CREATE TABLE population.geo_area (
        area_id VARCHAR(96) NOT NULL,
        level VARCHAR(16) NOT NULL,
        parent_area_id VARCHAR(96),
        name_en TEXT NOT NULL,
        name_ar TEXT,
        region_id SMALLINT,
        source VARCHAR(40) NOT NULL,
        source_label TEXT,
        verification_status VARCHAR(24) NOT NULL,
        reference_latitude DOUBLE PRECISION,
        reference_longitude DOUBLE PRECISION,
        boundary_ref TEXT,
        boundary_source TEXT,
        first_seen_at {_TS} NOT NULL,
        updated_at {_TS} NOT NULL,
        CONSTRAINT pk_geo_area PRIMARY KEY (area_id),
        CONSTRAINT fk_geo_area_parent_area_id_geo_area FOREIGN KEY (parent_area_id)
            REFERENCES population.geo_area (area_id) ON DELETE RESTRICT,
        CONSTRAINT ck_geo_area_level CHECK (level IN ('country', 'state', 'district', 'city', 'local_area')),
        CONSTRAINT ck_geo_area_source CHECK (source IN ('iso_3166', 'official_region',
            'sdi_facility_city_label', 'synthetic_patient_label')),
        CONSTRAINT ck_geo_area_verification_status CHECK (verification_status IN
            ('verified_reference', 'published_label', 'synthetic_label')),
        CONSTRAINT ck_geo_area_parent_unless_country CHECK ((level = 'country') = (parent_area_id IS NULL)),
        CONSTRAINT ck_geo_area_reference_point_pair CHECK
            ((reference_latitude IS NULL) = (reference_longitude IS NULL)),
        CONSTRAINT ck_geo_area_boundary_pair CHECK ((boundary_ref IS NULL) = (boundary_source IS NULL))
    )
    """,
    "CREATE INDEX ix_geo_area_level ON population.geo_area (level)",
    "CREATE INDEX ix_geo_area_parent ON population.geo_area (parent_area_id)",
    f"""
    CREATE TABLE population.aggregation_run (
        run_id VARCHAR(36) NOT NULL,
        organization_key VARCHAR(40) NOT NULL,
        status VARCHAR(16) NOT NULL,
        trigger VARCHAR(16) NOT NULL,
        requested_by VARCHAR(36),
        started_at {_TS} NOT NULL,
        finished_at {_TS},
        engine_version VARCHAR(16) NOT NULL,
        data_version VARCHAR(64),
        config_version INTEGER,
        source_run_id TEXT,
        as_of DATE,
        complete_through DATE,
        latest_data_at {_TS},
        snapshot JSONB,
        summary JSONB NOT NULL,
        error_code VARCHAR(64),
        CONSTRAINT pk_aggregation_run PRIMARY KEY (run_id),
        CONSTRAINT ck_aggregation_run_status CHECK (status IN ('running', 'succeeded', 'failed')),
        CONSTRAINT ck_aggregation_run_trigger CHECK (trigger IN ('manual', 'scheduled', 'on_demand',
            'stale_data', 'config_change')),
        CONSTRAINT ck_aggregation_run_finished_unless_running CHECK ((status = 'running') = (finished_at IS NULL)),
        CONSTRAINT ck_aggregation_run_succeeded_has_snapshot CHECK (status <> 'succeeded' OR snapshot IS NOT NULL)
    )
    """,
    "CREATE UNIQUE INDEX uq_aggregation_run_one_running ON population.aggregation_run (organization_key) "
    "WHERE status = 'running'",
    "CREATE INDEX ix_aggregation_run_org_status_finished ON population.aggregation_run "
    "(organization_key, status, finished_at)",
    f"""
    CREATE TABLE population.threshold_config (
        organization_key VARCHAR(40) NOT NULL,
        version INTEGER NOT NULL,
        thresholds JSONB NOT NULL,
        updated_at {_TS} NOT NULL,
        updated_by VARCHAR(36),
        CONSTRAINT pk_threshold_config PRIMARY KEY (organization_key),
        CONSTRAINT ck_threshold_config_version_positive CHECK (version >= 1)
    )
    """,
    f"""
    CREATE TABLE population.population_alert (
        alert_id VARCHAR(36) NOT NULL,
        organization_key VARCHAR(40) NOT NULL,
        dedup_key VARCHAR(255) NOT NULL,
        category VARCHAR(40) NOT NULL,
        area_id VARCHAR(96) NOT NULL,
        condition_code VARCHAR(40),
        severity VARCHAR(16) NOT NULL,
        title TEXT NOT NULL,
        explanation TEXT NOT NULL,
        metrics JSONB NOT NULL,
        thresholds JSONB NOT NULL,
        period_key VARCHAR(8),
        period_start DATE,
        period_end DATE,
        first_detected_at {_TS} NOT NULL,
        last_detected_at {_TS} NOT NULL,
        data_freshness_at {_TS},
        status VARCHAR(16) NOT NULL,
        condition_active BOOLEAN NOT NULL DEFAULT true,
        occurrence_count INTEGER NOT NULL DEFAULT 1,
        last_run_id VARCHAR(36),
        acknowledged_by VARCHAR(36),
        acknowledged_at {_TS},
        investigating_by VARCHAR(36),
        investigating_at {_TS},
        closed_by VARCHAR(36),
        closed_at {_TS},
        created_at {_TS} NOT NULL,
        updated_at {_TS} NOT NULL,
        CONSTRAINT pk_population_alert PRIMARY KEY (alert_id),
        CONSTRAINT ck_population_alert_category CHECK (category IN ('case_increase', 'disease_burden',
            'prevalence', 'preventive_coverage_low', 'follow_up_completion_decline',
            'facility_coverage_insufficient')),
        CONSTRAINT ck_population_alert_severity CHECK (severity IN ('CRITICAL', 'HIGH', 'MODERATE', 'WATCH')),
        CONSTRAINT ck_population_alert_status CHECK (status IN ('NEW', 'ACKNOWLEDGED', 'INVESTIGATING',
            'RESOLVED', 'DISMISSED')),
        CONSTRAINT ck_population_alert_occurrence_count_positive CHECK (occurrence_count >= 1),
        CONSTRAINT ck_population_alert_closed_consistency CHECK
            ((status IN ('RESOLVED', 'DISMISSED')) = (closed_at IS NOT NULL))
    )
    """,
    "CREATE UNIQUE INDEX uq_population_alert_active_dedup ON population.population_alert "
    f"(organization_key, dedup_key) WHERE status IN {_ACTIVE}",
    "CREATE INDEX ix_population_alert_org_status_severity ON population.population_alert "
    "(organization_key, status, severity)",
    "CREATE INDEX ix_population_alert_org_area ON population.population_alert (organization_key, area_id)",
    "CREATE INDEX ix_population_alert_org_dedup ON population.population_alert "
    "(organization_key, dedup_key, created_at)",
    "CREATE INDEX ix_population_alert_org_detected ON population.population_alert "
    "(organization_key, last_detected_at)",
    f"""
    CREATE TABLE population.population_alert_event (
        event_id VARCHAR(36) NOT NULL,
        alert_id VARCHAR(36) NOT NULL,
        organization_key VARCHAR(40) NOT NULL,
        event_type VARCHAR(24) NOT NULL,
        from_status VARCHAR(16),
        to_status VARCHAR(16),
        severity VARCHAR(16),
        actor_user_id VARCHAR(36),
        actor_role VARCHAR(40),
        run_id VARCHAR(36),
        occurred_at {_TS} NOT NULL,
        note TEXT,
        details JSONB NOT NULL,
        CONSTRAINT pk_population_alert_event PRIMARY KEY (event_id),
        CONSTRAINT fk_population_alert_event_alert_id_population_alert FOREIGN KEY (alert_id)
            REFERENCES population.population_alert (alert_id) ON DELETE RESTRICT,
        CONSTRAINT ck_population_alert_event_event_type CHECK (event_type IN ('created', 'updated',
            'status_changed', 'condition_cleared', 'condition_recurred')),
        CONSTRAINT ck_population_alert_event_status_change_has_actor CHECK
            (event_type <> 'status_changed' OR (to_status IS NOT NULL AND actor_user_id IS NOT NULL))
    )
    """,
    "CREATE INDEX ix_population_alert_event_alert ON population.population_alert_event (alert_id, occurred_at)",
    """
    CREATE TRIGGER trg_population_alert_event_append_only BEFORE UPDATE OR DELETE
        ON population.population_alert_event FOR EACH ROW EXECUTE FUNCTION identity.reject_audit_mutation()
    """,
    """
    CREATE TRIGGER trg_population_alert_event_no_truncate BEFORE TRUNCATE ON population.population_alert_event
        FOR EACH STATEMENT EXECUTE FUNCTION identity.reject_audit_mutation()
    """,
)

_DOWNGRADE = (
    "DROP SCHEMA IF EXISTS population CASCADE",
    "DROP INDEX IF EXISTS synthetic.ix_patient_run_region_district",
    "DROP TABLE IF EXISTS synthetic.condition_record",
)

_DATA_AT_RISK = {
    "population alerts": "SELECT count(*) FROM population.population_alert",
    "threshold configurations": "SELECT count(*) FROM population.threshold_config",
}


def _refuse_destructive_downgrade() -> None:
    if context.is_offline_mode():
        return
    if context.get_x_argument(as_dictionary=True).get("allow_data_loss", "").lower() == "true":
        return
    bind = op.get_bind()
    found = {label: n for label, sql in _DATA_AT_RISK.items() if (n := bind.execute(text(sql)).scalar_one())}
    if found:
        summary = ", ".join(f"{n} {label}" for label, n in found.items())
        raise RuntimeError(
            f"Refusing to downgrade {revision}: it would permanently delete {summary}. Back up the "
            "database first, then rerun with `-x allow_data_loss=true` if the loss is intended."
        )


def upgrade() -> None:
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    _refuse_destructive_downgrade()
    for stmt in _DOWNGRADE:
        op.execute(stmt)
