"""Add append-only `synthetic.care_gap_follow_up_event` table (T-09).

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "care_gap_follow_up_event",
        sa.Column("follow_up_id", sa.Text(), primary_key=True),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("patient_id", sa.Text(), nullable=False),
        sa.Column("care_gap_id", sa.Text(), nullable=False),
        sa.Column(
            "is_synthetic",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("outcome_status", sa.Text(), nullable=True),
        sa.Column(
            "documented_evidence",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("evidence_reference", sa.Text(), nullable=True),
        sa.Column("contact_consent_id", sa.Text(), nullable=True),
        sa.Column("suppression_reason", sa.Text(), nullable=True),
        sa.Column("recorded_by", sa.Text(), nullable=False),
        sa.Column("recorded_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["run_id", "patient_id", "care_gap_id"],
            [
                "synthetic.care_gap.run_id",
                "synthetic.care_gap.patient_id",
                "synthetic.care_gap.care_gap_id",
            ],
            name="fk_care_gap_follow_up_event_care_gap",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("is_synthetic IS TRUE", name="ck_care_gap_follow_up_event_is_synthetic"),
        sa.CheckConstraint(
            "follow_up_id ~ '^SYNTH-FUP-[0-9]{6,}$'",
            name="ck_care_gap_follow_up_event_id_format",
        ),
        sa.CheckConstraint(
            "event_type IN ('outreach_attempted', 'outreach_suppressed', 'appointment_scheduled', "
            "'appointment_updated', 'referral_created', 'referral_updated', "
            "'completion_documented', 'note_recorded')",
            name="ck_care_gap_follow_up_event_event_type",
        ),
        sa.CheckConstraint(
            "event_type <> 'outreach_attempted' OR contact_consent_id IS NOT NULL",
            name="ck_care_gap_follow_up_event_outreach_requires_consent",
        ),
        sa.CheckConstraint(
            "event_type <> 'outreach_suppressed' OR suppression_reason IS NOT NULL",
            name="ck_care_gap_follow_up_event_suppressed_requires_reason",
        ),
        schema="synthetic",
    )
    op.create_index(
        "ix_care_gap_follow_up_event_gap_recorded",
        "care_gap_follow_up_event",
        ["care_gap_id", "recorded_at"],
        schema="synthetic",
    )
    op.create_index(
        "ix_care_gap_follow_up_event_patient",
        "care_gap_follow_up_event",
        ["patient_id", "recorded_at"],
        schema="synthetic",
    )
    op.execute(
        """
        CREATE TRIGGER trg_care_gap_follow_up_event_append_only
            BEFORE UPDATE OR DELETE ON synthetic.care_gap_follow_up_event
            FOR EACH ROW
            EXECUTE FUNCTION synthetic.reject_append_only_mutation();
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_care_gap_follow_up_event_append_only "
        "ON synthetic.care_gap_follow_up_event;"
    )
    op.drop_index(
        "ix_care_gap_follow_up_event_patient",
        table_name="care_gap_follow_up_event",
        schema="synthetic",
    )
    op.drop_index(
        "ix_care_gap_follow_up_event_gap_recorded",
        table_name="care_gap_follow_up_event",
        schema="synthetic",
    )
    op.drop_table("care_gap_follow_up_event", schema="synthetic")
