"""Lock the reconciliation behaviour of the official views (Phase 4, Step 3, Part A).

Revision ID: 0004
Revises: 0003

Migration 0003 is not edited; this revision replaces two of its views (no table, column, constraint, index or
row is touched). Decisions applied to `v_indicator_year_shape` (and, because it depends on it, re-created
unchanged, `v_derived_total_additive`):

1. `RC-HIERARCHY` is never inferred. Two or more aggregate members in one slice are not proof of a nesting;
   without a verified parent/child relationship the slice is `not_testable` and is excluded from derived totals.
2. `RC-UNEXPLAINED` is not a fall-through. It is assigned only where a tolerance is defined and exceeded
   (projected series). Leaves below the aggregate with a residual member (`Missing/Unknown`, `Not stated`,
   `Abroad`) already among the leaves stay a `mismatch` with `mismatch_class` NULL = unresolved: the residual is
   already inside the leaf sum, so it demonstrably does not explain the shortfall.
3. Classification precedence is explicit and deterministic (see the CASE below). The projection tolerance is
   defined only for 2024 (step 5) and for 2030 onwards (step 1,000); 2025-2029 have none and are not
   extrapolated (a projected mismatch there is unresolved, never `RC-PROJ-ROUNDING`).
4. Slices whose fixed (non-varied) dimensions contain an aggregate member are kept and marked
   `not_testable` (reason `aggregate_in_fixed_dimension`) instead of being dropped from the screening.
5. Vintage selection (`v_observation_current`, unchanged) is documented accurately in its view comment.
   `series_kind` is kept.

A slice with a NULL value is also `not_testable` (a sum over a missing cell proves nothing).
"""
import importlib.util
from pathlib import Path

from alembic import op

revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def _m3():
    """The 0003 module (its file name starts with a digit, so it cannot be imported normally)."""
    path = Path(__file__).with_name('0003_official_views_and_integrity.py')
    spec = importlib.util.spec_from_file_location('official_migration_0003', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# Precedence of the classification, first match wins:
#   cell_state:    not_testable (fixed aggregate -> 2+ aggregate members -> NULL value)
#                  -> no_aggregate -> aggregate_only -> reconciles -> mismatch
#   mismatch_class (mismatch only): RC-ZERO-LEAVES
#                  -> projected: RC-PROJ-ROUNDING (within tolerance) | RC-UNEXPLAINED (tolerance exceeded) |
#                     NULL (no tolerance defined for the year)
#                  -> leaves below: RC-RESIDUAL-BELOW (no residual member among the leaves) | NULL (residual
#                     already among the leaves: unresolved)
#                  -> leaves above: RC-LEAVES-ABOVE
V_INDICATOR_YEAR_SHAPE = """
CREATE VIEW official.v_indicator_year_shape AS
WITH member_rows AS (
    SELECT o.observation_id, o.indicator_id, o.source_file_id, o.period_year, o.series_kind, o.value,
           u.dimension_type, dm.member_role,
           jsonb_strip_nulls(jsonb_build_object(%(pairs)s)) - u.dimension_type AS fixed_members,
           count(*) FILTER (WHERE dm.member_role = 'aggregate') OVER (PARTITION BY o.observation_id)
               - (dm.member_role = 'aggregate')::int > 0 AS fixed_has_aggregate
    FROM official.v_observation_current o
    CROSS JOIN LATERAL (VALUES
            %(values_o)s
        ) u(dimension_type, member_id)
    JOIN official.dimension_member dm ON dm.member_id = u.member_id
    WHERE o.quality_flag IS NULL
),
slices AS (
    SELECT indicator_id, source_file_id, period_year, series_kind, dimension_type, fixed_members,
           bool_or(fixed_has_aggregate) AS fixed_has_aggregate,
           count(*) FILTER (WHERE member_role = 'aggregate') AS n_aggregate_members,
           count(*) FILTER (WHERE member_role <> 'aggregate') AS n_leaf_members,
           count(*) FILTER (WHERE value IS NULL) AS n_null_values,
           count(*) FILTER (WHERE member_role IN ('not_stated', 'missing_unknown', 'abroad')) AS n_residual_members,
           sum(value) FILTER (WHERE member_role = 'aggregate') AS aggregate_value,
           sum(value) FILTER (WHERE member_role <> 'aggregate') AS leaf_sum,
           coalesce(bool_and(value = 0) FILTER (WHERE member_role <> 'aggregate'), false) AS all_leaves_zero
    FROM member_rows
    GROUP BY indicator_id, source_file_id, period_year, series_kind, dimension_type, fixed_members
),
classified AS (
    SELECT s.*,
           CASE WHEN fixed_has_aggregate THEN 'aggregate_in_fixed_dimension'
                WHEN n_aggregate_members >= 2 THEN 'multiple_aggregate_members_unverified_hierarchy'
                WHEN n_null_values > 0 THEN 'null_value'
           END AS not_testable_reason,
           CASE WHEN fixed_has_aggregate OR n_aggregate_members >= 2 OR n_null_values > 0 THEN 'not_testable'
                WHEN n_aggregate_members = 0 THEN 'no_aggregate'
                WHEN n_leaf_members = 0 THEN 'aggregate_only'
                WHEN leaf_sum = aggregate_value THEN 'reconciles'
                ELSE 'mismatch' END AS cell_state,
           -- Tolerance only where it was observed: 2024 and 2030+. Never extrapolated to 2025-2029.
           CASE WHEN period_year = 2024 THEN 5 WHEN period_year >= 2030 THEN 1000 END AS step
    FROM slices s
)
SELECT indicator_id, source_file_id, period_year, series_kind, dimension_type, fixed_members,
       n_aggregate_members > 0 AS has_aggregate,
       n_aggregate_members, n_leaf_members, n_null_values,
       aggregate_value, leaf_sum,
       CASE WHEN cell_state IN ('reconciles', 'mismatch') THEN leaf_sum - aggregate_value END AS difference,
       cell_state,
       CASE WHEN cell_state <> 'mismatch' THEN NULL
            WHEN all_leaves_zero AND aggregate_value > 0 THEN 'RC-ZERO-LEAVES'
            WHEN series_kind = 'projected' AND step IS NOT NULL
                 AND abs(leaf_sum - aggregate_value) <= n_leaf_members * step / 2.0 THEN 'RC-PROJ-ROUNDING'
            WHEN series_kind = 'projected' AND step IS NOT NULL THEN 'RC-UNEXPLAINED'
            WHEN series_kind = 'projected' THEN NULL
            WHEN leaf_sum < aggregate_value AND n_residual_members = 0 THEN 'RC-RESIDUAL-BELOW'
            WHEN leaf_sum < aggregate_value THEN NULL
            WHEN leaf_sum > aggregate_value THEN 'RC-LEAVES-ABOVE'
       END AS mismatch_class,
       not_testable_reason
FROM classified;
"""

COMMENT_CURRENT = (
    "Vintage selector, not a statement about which file is newer in the world. Per indicator it keeps the rows of "
    "the one source_file that has observations and sorts first by retrieved_at DESC (NULL = not recorded, treated "
    "as oldest), then source_file_id DESC. While retrieved_at is NULL on the competing files the choice therefore "
    "falls to source_file_id, i.e. registration order, which is neither retrieval nor publication time; the "
    "loader refuses a second detail file for an indicator in that situation, so today each indicator has exactly "
    "one. Selection is per indicator, not per period, and does not test a file for completeness. series_kind is "
    "exposed and NOT filtered."
)
COMMENT_SHAPE = (
    "One row per (indicator, vintage, year, varied dimension, fixed members). cell_state: not_testable | "
    "no_aggregate | aggregate_only | reconciles | mismatch. not_testable (excluded from derived totals) = an "
    "aggregate among the fixed members, two or more aggregate members (hierarchy unverified, RC-HIERARCHY is "
    "never inferred) or a NULL value. mismatch_class NULL on a mismatch = unresolved. Projection tolerance "
    "exists for 2024 (5) and 2030+ (1000) only. A report, never a correction."
)


def upgrade() -> None:
    m3 = _m3()
    op.execute("DROP VIEW official.v_derived_total_additive")
    op.execute("DROP VIEW official.v_indicator_year_shape")
    op.execute(V_INDICATOR_YEAR_SHAPE % {"pairs": m3._pairs("o."), "values_o": m3._values("o.")})
    op.execute(m3.V_DERIVED_TOTAL_ADDITIVE)  # unchanged: reconciles / no_aggregate, additive, observed only
    op.execute("COMMENT ON VIEW official.v_observation_current IS '%s'" % COMMENT_CURRENT.replace("'", "''"))
    op.execute("COMMENT ON VIEW official.v_indicator_year_shape IS '%s'" % COMMENT_SHAPE.replace("'", "''"))


def downgrade() -> None:
    m3 = _m3()
    op.execute("COMMENT ON VIEW official.v_observation_current IS NULL")
    op.execute("DROP VIEW official.v_derived_total_additive")
    op.execute("DROP VIEW official.v_indicator_year_shape")
    op.execute(m3.V_INDICATOR_YEAR_SHAPE)
    op.execute(m3.V_DERIVED_TOTAL_ADDITIVE)
