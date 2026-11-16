"""Official derived views and deferred integrity controls (design §3.2, §3.3, §3.4; ERD §8).

Revision ID: 0003
Revises: 0002

Adds, to the nine `official` tables created in 0002 (no table or column is changed):

Views (design §3.3 / §3.4)
  v_observation_current       latest source_file per indicator (vintage selector; no series_kind filter)
  v_observation_leaf          default observed-data read path (leaf, clean, observed, current vintage)
  v_indicator_year_shape      per (indicator, year, dimension slice): shape + reconciliation class
  v_derived_total_additive    totals derived from leaves (additive, observed, never `mismatch`)
  v_facility_usable           identified + usable coordinates + reviewed-operating licence

Integrity (design §3.2 `source` Checks; ERD §8 item 1)
  * deferred constraint triggers: a `dataset_obtained` / `document_obtained` source must have >= 1
    source_file (checked at COMMIT, from both sides: the source and its last file)
  * row trigger: each observation.*_member_id must reference a dimension_member of the matching
    dimension_type, plus a guard that a referenced member's dimension_type cannot be changed. This is
    the in-database form of the design's "optional composite FK"; it needs no extra observation columns.

No data is read or changed except one pre-flight check: if rows already violate the two new invariants the
upgrade stops with a clear message instead of adopting an invariant the data does not satisfy.
"""
from alembic import op


revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None

# (dimension_type, observation column) in design order.
DIMENSIONS = [
    ('region', 'region_member_id'),
    ('citizenship', 'citizenship_member_id'),
    ('gender', 'gender_member_id'),
    ('age_group', 'age_group_member_id'),
    ('cause_of_death', 'cause_of_death_member_id'),
    ('disease_type', 'disease_type_member_id'),
    ('measure_item', 'measure_item_member_id'),
    ('insurance_type', 'insurance_type_member_id'),
    ('sector', 'sector_member_id'),
    ('bed_type', 'bed_type_member_id'),
]


def _values(prefix: str) -> str:
    """(dimension_type, member_id) VALUES rows for the ten wide member columns."""
    return ",\n            ".join(f"('{d}', {prefix}{c})" for d, c in DIMENSIONS)


def _pairs(prefix: str) -> str:
    return ", ".join(f"'{d}', {prefix}{c}" for d, c in DIMENSIONS)


def _any_member_equals(var: str) -> str:
    return "\n           OR ".join(f"{c} = {var}" for _, c in DIMENSIONS)


PREFLIGHT = """
DO $$
DECLARE n bigint;
BEGIN
    SELECT count(*) INTO n FROM official.source s
    WHERE s.acquisition_state IN ('dataset_obtained', 'document_obtained')
      AND NOT EXISTS (SELECT 1 FROM official.source_file f WHERE f.source_id = s.source_id);
    IF n > 0 THEN
        RAISE EXCEPTION '0003: %% obtained source(s) have no source_file; fix or register files before upgrading', n
            USING ERRCODE = 'check_violation';
    END IF;

    SELECT count(*) INTO n FROM official.observation o
    CROSS JOIN LATERAL (VALUES
            %(values_o)s
        ) v(dimension_type, member_id)
    JOIN official.dimension_member m ON m.member_id = v.member_id
    WHERE m.dimension_type <> v.dimension_type;
    IF n > 0 THEN
        RAISE EXCEPTION '0003: %% observation member reference(s) point at a member of the wrong dimension_type', n
            USING ERRCODE = 'check_violation';
    END IF;
END $$;
""" % {"values_o": _values("o.")}


FN_SOURCE_FILE = """
CREATE FUNCTION official.enforce_obtained_source_has_source_file() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    sid text;
BEGIN
    -- On `source` the row itself is checked; on `source_file` the source the file belonged to.
    IF TG_TABLE_NAME = 'source' THEN
        sid := NEW.source_id;
    ELSE
        sid := OLD.source_id;
    END IF;
    IF EXISTS (SELECT 1 FROM official.source s
               WHERE s.source_id = sid
                 AND s.acquisition_state IN ('dataset_obtained', 'document_obtained'))
       AND NOT EXISTS (SELECT 1 FROM official.source_file f WHERE f.source_id = sid) THEN
        RAISE EXCEPTION 'source % is obtained but has no source_file', sid
            USING ERRCODE = 'check_violation', CONSTRAINT = 'source_obtained_requires_source_file',
                  SCHEMA = 'official', TABLE = 'source';
    END IF;
    RETURN NULL;
END $$;
"""

TRIGGERS_SOURCE_FILE = """
CREATE CONSTRAINT TRIGGER trg_source_obtained_requires_source_file
    AFTER INSERT OR UPDATE ON official.source
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION official.enforce_obtained_source_has_source_file();

CREATE CONSTRAINT TRIGGER trg_source_file_keeps_obtained_source_covered
    AFTER DELETE OR UPDATE OF source_id ON official.source_file
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION official.enforce_obtained_source_has_source_file();
"""

FN_MEMBER_TYPE = """
CREATE FUNCTION official.enforce_observation_member_dimension_type() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    bad record;
BEGIN
    SELECT v.dimension_type AS expected, m.dimension_type AS actual, v.member_id
      INTO bad
      FROM (VALUES
            %(values_new)s
           ) v(dimension_type, member_id)
      JOIN official.dimension_member m ON m.member_id = v.member_id
     WHERE m.dimension_type <> v.dimension_type
     LIMIT 1;
    IF FOUND THEN
        RAISE EXCEPTION 'observation %%_member_id references member %% of dimension_type %%',
            bad.expected, bad.member_id, bad.actual
            USING ERRCODE = 'check_violation', CONSTRAINT = 'observation_member_dimension_type',
                  SCHEMA = 'official', TABLE = 'observation';
    END IF;
    RETURN NULL;
END $$;

CREATE FUNCTION official.forbid_retyping_referenced_dimension_member() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM official.observation
               WHERE %(any_old)s) THEN
        RAISE EXCEPTION 'dimension_member %% is referenced by observations; its dimension_type cannot change',
            OLD.member_id
            USING ERRCODE = 'check_violation', CONSTRAINT = 'observation_member_dimension_type',
                  SCHEMA = 'official', TABLE = 'dimension_member';
    END IF;
    RETURN NEW;
END $$;
""" % {"values_new": _values("NEW."), "any_old": _any_member_equals("OLD.member_id")}

TRIGGERS_MEMBER_TYPE = """
CREATE TRIGGER trg_observation_member_dimension_type
    AFTER INSERT OR UPDATE ON official.observation
    FOR EACH ROW EXECUTE FUNCTION official.enforce_observation_member_dimension_type();

CREATE TRIGGER trg_dimension_member_type_not_retyped
    BEFORE UPDATE OF dimension_type ON official.dimension_member
    FOR EACH ROW WHEN (OLD.dimension_type IS DISTINCT FROM NEW.dimension_type)
    EXECUTE FUNCTION official.forbid_retyping_referenced_dimension_member();
"""

# Latest vintage per indicator: ordered by retrieved_at (NULL = unknown = oldest), then source_file_id so the
# choice is deterministic. The loader refuses a second detail file while either has retrieved_at NULL
# (mapping §6.x), so today the order is never ambiguous.
V_OBSERVATION_CURRENT = """
CREATE VIEW official.v_observation_current AS
WITH vintage AS (
    SELECT DISTINCT ON (o.indicator_id) o.indicator_id, o.source_file_id
    FROM (SELECT DISTINCT indicator_id, source_file_id FROM official.observation) o
    JOIN official.source_file f ON f.source_file_id = o.source_file_id
    ORDER BY o.indicator_id, f.retrieved_at DESC NULLS LAST, o.source_file_id DESC
)
SELECT o.*, i.series_kind
FROM official.observation o
JOIN vintage v ON v.indicator_id = o.indicator_id AND v.source_file_id = o.source_file_id
JOIN official.indicator i ON i.indicator_id = o.indicator_id;
"""

V_OBSERVATION_LEAF = """
CREATE VIEW official.v_observation_leaf AS
SELECT *
FROM official.v_observation_current
WHERE row_role = 'leaf'
  AND quality_flag IS NULL
  AND series_kind = 'observed';
"""

# One row per (indicator, vintage, year, varied dimension, fixed other members). A row takes part in a slice for
# dimension D only if none of its *other* members is an aggregate, so the slice holds true leaves plus (at
# most) the aggregate of D. Clean rows only (quality_flag IS NULL) of the current vintage.
# The `step` tolerance (5 up to 2029, 1000 from 2030) is inferred from the data, not publisher-stated.
V_INDICATOR_YEAR_SHAPE = """
CREATE VIEW official.v_indicator_year_shape AS
WITH member_rows AS (
    SELECT o.observation_id, o.indicator_id, o.source_file_id, o.period_year, o.series_kind, o.value,
           u.dimension_type, dm.member_role,
           jsonb_strip_nulls(jsonb_build_object(%(pairs)s)) - u.dimension_type AS fixed_members,
           count(*) FILTER (WHERE dm.member_role = 'aggregate') OVER (PARTITION BY o.observation_id) AS row_aggregates
    FROM official.v_observation_current o
    CROSS JOIN LATERAL (VALUES
            %(values_o)s
        ) u(dimension_type, member_id)
    JOIN official.dimension_member dm ON dm.member_id = u.member_id
    WHERE o.quality_flag IS NULL
),
slices AS (
    SELECT indicator_id, source_file_id, period_year, series_kind, dimension_type, fixed_members,
           count(*) FILTER (WHERE member_role = 'aggregate') AS n_aggregate_members,
           count(*) FILTER (WHERE member_role <> 'aggregate') AS n_leaf_members,
           count(*) FILTER (WHERE value IS NULL) AS n_null_values,
           count(*) FILTER (WHERE member_role IN ('not_stated', 'missing_unknown', 'abroad')) AS n_residual_members,
           sum(value) FILTER (WHERE member_role = 'aggregate') AS aggregate_value,
           sum(value) FILTER (WHERE member_role <> 'aggregate') AS leaf_sum,
           coalesce(bool_and(value = 0) FILTER (WHERE member_role <> 'aggregate'), false) AS all_leaves_zero
    FROM member_rows
    WHERE row_aggregates - (member_role = 'aggregate')::int = 0
    GROUP BY indicator_id, source_file_id, period_year, series_kind, dimension_type, fixed_members
),
classified AS (
    SELECT s.*,
           CASE WHEN n_aggregate_members >= 2 THEN 'mismatch'
                WHEN n_aggregate_members = 0 THEN 'no_aggregate'
                WHEN n_leaf_members = 0 THEN 'aggregate_only'
                WHEN leaf_sum = aggregate_value THEN 'reconciles'
                ELSE 'mismatch' END AS cell_state,
           CASE WHEN period_year >= 2030 THEN 1000 ELSE 5 END AS step
    FROM slices s
)
SELECT indicator_id, source_file_id, period_year, series_kind, dimension_type, fixed_members,
       n_aggregate_members > 0 AS has_aggregate,
       n_aggregate_members, n_leaf_members, n_null_values,
       aggregate_value, leaf_sum,
       CASE WHEN n_aggregate_members = 1 AND n_leaf_members > 0 THEN leaf_sum - aggregate_value END AS difference,
       cell_state,
       CASE WHEN cell_state <> 'mismatch' THEN NULL
            WHEN n_aggregate_members >= 2 THEN 'RC-HIERARCHY'
            WHEN all_leaves_zero AND aggregate_value > 0 THEN 'RC-ZERO-LEAVES'
            WHEN series_kind = 'projected' AND abs(leaf_sum - aggregate_value) <= n_leaf_members * step / 2.0
                THEN 'RC-PROJ-ROUNDING'
            WHEN series_kind = 'projected' THEN 'RC-UNEXPLAINED'
            WHEN leaf_sum < aggregate_value AND n_residual_members = 0 THEN 'RC-RESIDUAL-BELOW'
            WHEN leaf_sum > aggregate_value THEN 'RC-LEAVES-ABOVE'
            ELSE 'RC-UNEXPLAINED' END AS mismatch_class
FROM classified;
""" % {"pairs": _pairs("o."), "values_o": _values("o.")}

V_DERIVED_TOTAL_ADDITIVE = """
CREATE VIEW official.v_derived_total_additive AS
SELECT s.indicator_id, s.source_file_id, s.period_year, s.dimension_type, s.fixed_members,
       s.leaf_sum AS derived_total, s.n_leaf_members, s.cell_state,
       'derived'::text AS value_origin
FROM official.v_indicator_year_shape s
JOIN official.indicator i ON i.indicator_id = s.indicator_id
WHERE i.is_additive
  AND s.series_kind = 'observed'
  AND s.cell_state IN ('reconciles', 'no_aggregate')
  AND s.n_leaf_members > 0
  AND s.n_null_values = 0;
"""

V_FACILITY_USABLE = """
CREATE VIEW official.v_facility_usable AS
SELECT f.*
FROM official.facility f
JOIN official.license_status_map l ON l.raw_value = f.license_status_raw
WHERE f.identity_status = 'identified'
  AND f.longitude IS NOT NULL AND f.latitude IS NOT NULL
  AND f.geo_quality IN ('ok', 'swapped_repaired')
  AND l.is_operating IS TRUE;
"""

VIEWS = ['v_facility_usable', 'v_derived_total_additive', 'v_indicator_year_shape',
         'v_observation_leaf', 'v_observation_current']  # drop order (dependents first)


def upgrade() -> None:
    op.execute(PREFLIGHT)
    op.execute(FN_SOURCE_FILE)
    op.execute(TRIGGERS_SOURCE_FILE)
    op.execute(FN_MEMBER_TYPE)
    op.execute(TRIGGERS_MEMBER_TYPE)
    for ddl in (V_OBSERVATION_CURRENT, V_OBSERVATION_LEAF, V_INDICATOR_YEAR_SHAPE,
                V_DERIVED_TOTAL_ADDITIVE, V_FACILITY_USABLE):
        op.execute(ddl)


def downgrade() -> None:
    for view in VIEWS:
        op.execute(f"DROP VIEW official.{view}")
    op.execute("DROP TRIGGER trg_dimension_member_type_not_retyped ON official.dimension_member")
    op.execute("DROP TRIGGER trg_observation_member_dimension_type ON official.observation")
    op.execute("DROP FUNCTION official.forbid_retyping_referenced_dimension_member()")
    op.execute("DROP FUNCTION official.enforce_observation_member_dimension_type()")
    op.execute("DROP TRIGGER trg_source_file_keeps_obtained_source_covered ON official.source_file")
    op.execute("DROP TRIGGER trg_source_obtained_requires_source_file ON official.source")
    op.execute("DROP FUNCTION official.enforce_obtained_source_has_source_file()")
