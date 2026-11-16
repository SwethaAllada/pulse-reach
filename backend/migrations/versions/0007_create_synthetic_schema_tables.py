"""create synthetic schema tables, views, and append-only triggers

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-16

Creates the 18 tables of the `synthetic` schema (`docs/phase-3-database-design.md` §5),
the 4 synthetic views (`v_consent_current`, `v_history_availability_current`,
`v_eligibility_current`, `v_care_gap_effective_priority`), and append-only triggers.
"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy.schema import AddConstraint, CreateIndex, CreateTable, DropTable

import app.models.synthetic  # noqa: F401
from app.models.base import Base

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "synthetic"

# Ordered in dependency sequence so all tables except the circular Appointment <-> CareGap
# FK can be created cleanly; the circular FK `fk_appointment_care_gap_id_care_gap` is added
# right after `care_gap` is created.
TABLE_ORDER = (
    "generation_run",
    "evaluation_run",
    "facility_service_profile",
    "patient",
    "guardian",
    "consent",
    "history_availability",
    "eligibility_evaluation",
    "evaluation_reason",
    "appointment",
    "ifhas_screening",
    "well_child_visit",
    "component_result",
    "assessment",
    "referral",
    "care_gap",
    "care_gap_review",
    "outreach_event",
)

APPEND_ONLY_TABLES = (
    "evaluation_run",
    "eligibility_evaluation",
    "evaluation_reason",
    "consent",
    "history_availability",
    "care_gap_review",
)


def upgrade() -> None:
    bind = op.get_bind()
    synth_tables = {
        t.name: t for t in Base.metadata.tables.values() if t.schema == SCHEMA
    }

    deferred_fk = None
    for fk in synth_tables["appointment"].foreign_key_constraints:
        if fk.name == "fk_appointment_care_gap_id_care_gap":
            deferred_fk = fk
            break

    for name in TABLE_ORDER:
        tbl = synth_tables[name]
        if name == "appointment" and deferred_fk is not None:
            tbl.constraints.remove(deferred_fk)
            try:
                bind.execute(CreateTable(tbl))
            finally:
                tbl.constraints.add(deferred_fk)
        else:
            bind.execute(CreateTable(tbl))
        for idx in tbl.indexes:
            bind.execute(CreateIndex(idx))

    if deferred_fk is not None:
        bind.execute(AddConstraint(deferred_fk))

    # Synthetic views (docs/phase-3-database-design.md §5.2, §5.3, §5.5)
    op.execute(
        """
        CREATE VIEW synthetic.v_consent_current AS
        SELECT DISTINCT ON (
            run_id,
            patient_id,
            consent_type,
            COALESCE(scope_pathway, ''),
            COALESCE(scope_rule_id, '')
        )
            c.*
        FROM synthetic.consent c
        ORDER BY
            c.run_id,
            c.patient_id,
            c.consent_type,
            COALESCE(c.scope_pathway, ''),
            COALESCE(c.scope_rule_id, ''),
            c.recorded_at DESC,
            c.consent_id DESC;
        """
    )

    op.execute(
        """
        CREATE VIEW synthetic.v_history_availability_current AS
        SELECT DISTINCT ON (run_id, patient_id, pathway)
            h.*
        FROM synthetic.history_availability h
        ORDER BY h.run_id, h.patient_id, h.pathway, h.as_of_date DESC, h.history_id DESC;
        """
    )

    op.execute(
        """
        CREATE VIEW synthetic.v_eligibility_current AS
        SELECT DISTINCT ON (run_id, patient_id, rule_id)
            e.*
        FROM synthetic.eligibility_evaluation e
        ORDER BY e.run_id, e.patient_id, e.rule_id, e.evaluated_at DESC, e.evaluation_id DESC;
        """
    )

    op.execute(
        """
        CREATE VIEW synthetic.v_care_gap_effective_priority AS
        SELECT
            g.*,
            rev.review_id AS latest_review_id,
            rev.reviewer AS latest_reviewer,
            rev.action AS latest_review_action,
            rev.new_priority AS human_override_priority,
            rev.reason AS latest_review_reason,
            rev.reviewed_at AS latest_reviewed_at,
            COALESCE(rev.new_priority, g.priority_score) AS effective_priority
        FROM synthetic.care_gap g
        LEFT JOIN LATERAL (
            SELECT r.*
            FROM synthetic.care_gap_review r
            WHERE r.run_id = g.run_id AND r.care_gap_id = g.care_gap_id
            ORDER BY r.reviewed_at DESC, r.review_id DESC
            LIMIT 1
        ) rev ON TRUE;
        """
    )

    # Append-only trigger function and triggers
    op.execute(
        """
        CREATE FUNCTION synthetic.reject_append_only_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' AND current_setting('pulsereach.allow_synthetic_reset', true) = 'on' THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION 'synthetic.% is append-only; % is not permitted', TG_TABLE_NAME, TG_OP
                USING ERRCODE = 'integrity_constraint_violation';
        END $$;
        """
    )

    for tbl_name in APPEND_ONLY_TABLES:
        op.execute(
            f"""
            CREATE TRIGGER trg_{tbl_name}_append_only
            BEFORE UPDATE OR DELETE ON synthetic.{tbl_name}
            FOR EACH ROW EXECUTE FUNCTION synthetic.reject_append_only_mutation();
            """
        )


def downgrade() -> None:
    for tbl_name in APPEND_ONLY_TABLES:
        op.execute(
            f"DROP TRIGGER IF EXISTS trg_{tbl_name}_append_only ON synthetic.{tbl_name};"
        )
    op.execute("DROP FUNCTION IF EXISTS synthetic.reject_append_only_mutation();")

    op.execute("DROP VIEW IF EXISTS synthetic.v_care_gap_effective_priority;")
    op.execute("DROP VIEW IF EXISTS synthetic.v_eligibility_current;")
    op.execute("DROP VIEW IF EXISTS synthetic.v_history_availability_current;")
    op.execute("DROP VIEW IF EXISTS synthetic.v_consent_current;")

    op.execute(
        "ALTER TABLE synthetic.appointment DROP CONSTRAINT IF EXISTS fk_appointment_care_gap_id_care_gap;"
    )

    for name in reversed(TABLE_ORDER):
        op.drop_table(name, schema=SCHEMA)
