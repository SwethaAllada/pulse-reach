"""Reconciliation precision tolerance (Phase 4, Step 3.1).

Migration 0004 is not edited; this revision replaces `v_indicator_year_shape` (and, because it depends on it,
re-creates `v_derived_total_additive` unchanged). No table, column, constraint, index or row is touched.

Why: indicator 2622 (Outpatients by Facility Region) in 2016 and 2017 failed exact reconciliation by 9E-9 and
1E-9. The source stores those values as binary doubles printed to 15 significant digits (e.g. 13165217.3892964,
4990910.66883999, 881792.809562619 against a total of 19037920.867699). The loader keeps them exactly as
published (Decimal, never rounded), so the sum of rounded leaves differs from the separately rounded total by
representation error, not by a missing or surplus category.

PRECISION. Every value in the held SCAD detail files carries at most 15 significant digits. A value is therefore
known to within half a unit of its 15th significant digit: 0.5 * 10^(floor(log10|v|) - 14). For a slice the
worst-case error of (leaf_sum - aggregate) is the sum of that bound over every member in it (leaves and
aggregate), and the slice is `reconciles` when |leaf_sum - aggregate| does not exceed it. Properties:
  * not a global constant: it scales with the magnitude of the values (about 1E-7 near 1E7, 5E-13 near 100);
  * it cannot absorb a real discrepancy: for any count below 1E14 the bound is far below 1, so a difference of
    one unit is still a `mismatch`;
  * it does not change a stored value or the reported `difference` (still exact); the slices it rescues are
    flagged `reconciled_within_precision`;
  * it is separate from, and does not touch, the projection step tolerance (2024 / 2030+), which only
    classifies a mismatch that remains.
"""
import importlib.util
from pathlib import Path

from alembic import op

revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def _load(name, filename):
    """A sibling migration module (file names start with a digit, so they cannot be imported normally)."""
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# Classification precedence is unchanged from 0004 (cell_state: not_testable -> no_aggregate -> aggregate_only ->
# reconciles (exact or within precision) -> mismatch; mismatch_class as in 0004). RC-RESIDUAL-BELOW is kept for
# leaves below the aggregate with no residual member; leaves below WITH a residual member stay unresolved (NULL).
V_INDICATOR_YEAR_SHAPE = """
CREATE VIEW official.v_indicator_year_shape AS
WITH member_rows AS (
    SELECT o.observation_id, o.indicator_id, o.source_file_id, o.period_year, o.series_kind, o.value,
           u.dimension_type, dm.member_role,
           -- Half a unit in the 15th significant digit of this value (see PRECISION below); NULL for 0 / NULL.
           CASE WHEN o.value <> 0 THEN 0.5 * power(10::numeric, floor(log(abs(o.value)))::int - 14) END AS half_unit,
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
           coalesce(sum(half_unit), 0) AS precision_tolerance,
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
                WHEN abs(leaf_sum - aggregate_value) <= precision_tolerance THEN 'reconciles'
                ELSE 'mismatch' END AS cell_state,
           -- Tolerance only where it was observed: 2024 and 2030+. Never extrapolated to 2025-2029.
           CASE WHEN period_year = 2024 THEN 5 WHEN period_year >= 2030 THEN 1000 END AS step
    FROM slices s
)
SELECT indicator_id, source_file_id, period_year, series_kind, dimension_type, fixed_members,
       n_aggregate_members > 0 AS has_aggregate,
       n_aggregate_members, n_leaf_members, n_null_values,
       aggregate_value, leaf_sum, precision_tolerance,
       cell_state = 'reconciles' AND leaf_sum <> aggregate_value AS reconciled_within_precision,
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

COMMENT_SHAPE = (
    "One row per (indicator, vintage, year, varied dimension, fixed members). cell_state: not_testable | "
    "no_aggregate | aggregate_only | reconciles | mismatch. not_testable (excluded from derived totals) = an "
    "aggregate among the fixed members, two or more aggregate members (hierarchy unverified, RC-HIERARCHY is "
    "never inferred) or a NULL value. reconciles = leaf_sum equals the aggregate, or differs by no more than "
    "precision_tolerance (half a unit of the 15th significant digit of every member, summed; "
    "reconciled_within_precision marks those); difference is always the exact difference. mismatch_class NULL "
    "on a mismatch = unresolved. Projection tolerance exists for 2024 (5) and 2030+ (1000) only. A report, "
    "never a correction."
)


def upgrade() -> None:
    m3 = _load('official_migration_0003', '0003_official_views_and_integrity.py')
    op.execute("DROP VIEW official.v_derived_total_additive")
    op.execute("DROP VIEW official.v_indicator_year_shape")
    op.execute(V_INDICATOR_YEAR_SHAPE % {"pairs": m3._pairs("o."), "values_o": m3._values("o.")})
    op.execute(m3.V_DERIVED_TOTAL_ADDITIVE)  # unchanged
    op.execute("COMMENT ON VIEW official.v_indicator_year_shape IS '%s'" % COMMENT_SHAPE.replace("'", "''"))


def downgrade() -> None:
    m3 = _load('official_migration_0003', '0003_official_views_and_integrity.py')
    m4 = _load('official_migration_0004', '0004_lock_reconciliation_rules.py')
    op.execute("DROP VIEW official.v_derived_total_additive")
    op.execute("DROP VIEW official.v_indicator_year_shape")
    op.execute(m4.V_INDICATOR_YEAR_SHAPE % {"pairs": m3._pairs("o."), "values_o": m3._values("o.")})
    op.execute(m3.V_DERIVED_TOTAL_ADDITIVE)
    op.execute("COMMENT ON VIEW official.v_indicator_year_shape IS '%s'" % m4.COMMENT_SHAPE.replace("'", "''"))
