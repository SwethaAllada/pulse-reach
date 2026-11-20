"""Evaluation-time reason text/snapshot and durable AI audit (F-12, AI persistence).

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-20

- `synthetic.eligibility_evaluation.reason_detail` / `input_snapshot` and
  `synthetic.evaluation_reason.reason_detail`: the engine's reason text and the de-identified
  inputs, recorded when the evaluation runs. Rows written before this revision keep NULL (the
  API labels their snapshot `reconstructed_at_read`); nothing is backfilled from current data.
- `synthetic.ai_audit_record`: append-only audit of AI generations and human outreach reviews
  (references, prompt/provider/model metadata, outcome, SHA-256 fingerprints; never message
  text). A partial unique index allows one terminal review (`approved`/`rejected`) per draft.
- `uq_care_gap_follow_up_event_run_patient_follow_up` so a review can reference the simulated
  follow-up event of the same run and patient.

Downgrade drops recorded audit and evaluation data; it refuses to run while such data exists
unless explicitly allowed (`alembic -x allow_data_loss=true downgrade ...`).

Frozen static DDL: does not import live ORM metadata.
"""

from __future__ import annotations

from alembic import context, op
from sqlalchemy import text

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

_UPGRADE = (
    """
    ALTER TABLE synthetic.eligibility_evaluation
        ADD COLUMN reason_detail TEXT,
        ADD COLUMN input_snapshot JSONB
    """,
    "ALTER TABLE synthetic.evaluation_reason ADD COLUMN reason_detail TEXT",
    """
    ALTER TABLE synthetic.care_gap_follow_up_event
        ADD CONSTRAINT uq_care_gap_follow_up_event_run_patient_follow_up
            UNIQUE (run_id, patient_id, follow_up_id)
    """,
    """
    CREATE TABLE synthetic.ai_audit_record (
        audit_id TEXT NOT NULL,
        run_id TEXT NOT NULL,
        is_synthetic BOOLEAN NOT NULL DEFAULT true,
        recorded_at TIMESTAMP WITH TIME ZONE NOT NULL,
        request_id TEXT,
        feature TEXT NOT NULL,
        patient_id TEXT,
        rule_id TEXT,
        care_gap_id TEXT,
        subject JSONB NOT NULL DEFAULT '{}'::jsonb,
        prompt_version TEXT NOT NULL,
        provider TEXT,
        model TEXT,
        generation_mode TEXT NOT NULL,
        fallback_reason TEXT,
        violations JSONB NOT NULL DEFAULT '[]'::jsonb,
        input_sha256 TEXT,
        output_sha256 TEXT,
        latency_ms DOUBLE PRECISION,
        extra JSONB NOT NULL DEFAULT '{}'::jsonb,
        draft_audit_id TEXT,
        draft_feature TEXT GENERATED ALWAYS AS (
            CASE WHEN draft_audit_id IS NOT NULL THEN 'outreach_draft' END) STORED,
        review_decision TEXT,
        reviewed_by TEXT,
        follow_up_id TEXT,
        simulated_outreach_status TEXT,
        CONSTRAINT pk_ai_audit_record PRIMARY KEY (audit_id),
        CONSTRAINT uq_ai_audit_record_run_audit_feature UNIQUE (run_id, audit_id, feature),
        CONSTRAINT fk_ai_audit_record_run_id_generation_run FOREIGN KEY (run_id)
            REFERENCES synthetic.generation_run (run_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
        CONSTRAINT fk_ai_audit_record_patient_id_patient FOREIGN KEY (run_id, patient_id)
            REFERENCES synthetic.patient (run_id, patient_id)
            ON DELETE RESTRICT ON UPDATE RESTRICT,
        CONSTRAINT fk_ai_audit_record_draft_audit_id_ai_audit_record
            FOREIGN KEY (run_id, draft_audit_id, draft_feature)
            REFERENCES synthetic.ai_audit_record (run_id, audit_id, feature)
            ON DELETE RESTRICT ON UPDATE RESTRICT,
        CONSTRAINT fk_ai_audit_record_follow_up_id_care_gap_follow_up_event
            FOREIGN KEY (run_id, patient_id, follow_up_id)
            REFERENCES synthetic.care_gap_follow_up_event (run_id, patient_id, follow_up_id)
            ON DELETE RESTRICT ON UPDATE RESTRICT,
        CONSTRAINT ck_ai_audit_record_is_synthetic CHECK (is_synthetic),
        CONSTRAINT ck_ai_audit_record_audit_id_format CHECK (audit_id ~ '^[0-9a-f]{32}$'),
        CONSTRAINT ck_ai_audit_record_feature CHECK (
            feature IN ('explanation', 'outreach_draft', 'outreach_review', 'population_insight')),
        CONSTRAINT ck_ai_audit_record_generation_mode CHECK (
            generation_mode IN ('llm_grounded', 'deterministic_fallback', 'not_generated',
                                'human_approved', 'human_rejected', 'human_blocked',
                                'human_invalid')),
        CONSTRAINT ck_ai_audit_record_input_sha256_format
            CHECK (input_sha256 IS NULL OR input_sha256 ~ '^[0-9a-f]{64}$'),
        CONSTRAINT ck_ai_audit_record_output_sha256_format
            CHECK (output_sha256 IS NULL OR output_sha256 ~ '^[0-9a-f]{64}$'),
        CONSTRAINT ck_ai_audit_record_review_draft_link
            CHECK ((feature = 'outreach_review') = (draft_audit_id IS NOT NULL)),
        CONSTRAINT ck_ai_audit_record_review_decision CHECK (
            (feature = 'outreach_review') = (review_decision IS NOT NULL)
            AND (review_decision IS NULL OR (
                review_decision IN ('approved', 'rejected', 'blocked', 'invalid')
                AND generation_mode = 'human_' || review_decision))),
        CONSTRAINT ck_ai_audit_record_review_actor CHECK (
            feature <> 'outreach_review' OR length(btrim(coalesce(reviewed_by, ''))) > 0),
        CONSTRAINT ck_ai_audit_record_follow_up_only_on_review
            CHECK (follow_up_id IS NULL OR feature = 'outreach_review'),
        CONSTRAINT ck_ai_audit_record_simulated_outreach_status CHECK (
            simulated_outreach_status IS NULL
            OR simulated_outreach_status IN ('simulated_not_sent', 'suppressed')),
        CONSTRAINT ck_ai_audit_record_approved_records_simulated_follow_up CHECK (
            review_decision IS DISTINCT FROM 'approved'
            OR (follow_up_id IS NOT NULL AND simulated_outreach_status = 'simulated_not_sent'))
    )
    """,
    "CREATE UNIQUE INDEX uq_ai_audit_record_terminal_review ON synthetic.ai_audit_record "
    "(draft_audit_id) WHERE review_decision IN ('approved', 'rejected')",
    "CREATE UNIQUE INDEX uq_ai_audit_record_follow_up_id ON synthetic.ai_audit_record "
    "(follow_up_id) WHERE follow_up_id IS NOT NULL",
    "CREATE INDEX ix_ai_audit_record_feature_recorded ON synthetic.ai_audit_record "
    "(feature, recorded_at)",
    "CREATE INDEX ix_ai_audit_record_recorded ON synthetic.ai_audit_record (recorded_at)",
    "CREATE INDEX ix_ai_audit_record_patient ON synthetic.ai_audit_record (patient_id, recorded_at)",
    """
    CREATE TRIGGER trg_ai_audit_record_append_only
        BEFORE UPDATE OR DELETE ON synthetic.ai_audit_record
        FOR EACH ROW EXECUTE FUNCTION synthetic.reject_append_only_mutation()
    """,
)

_DOWNGRADE = (
    "DROP TABLE IF EXISTS synthetic.ai_audit_record",
    "ALTER TABLE synthetic.care_gap_follow_up_event "
    "DROP CONSTRAINT IF EXISTS uq_care_gap_follow_up_event_run_patient_follow_up",
    "ALTER TABLE synthetic.evaluation_reason DROP COLUMN IF EXISTS reason_detail",
    "ALTER TABLE synthetic.eligibility_evaluation "
    "DROP COLUMN IF EXISTS input_snapshot, DROP COLUMN IF EXISTS reason_detail",
)

# Data that downgrade would destroy, and how to count it.
_DATA_AT_RISK = {
    "AI audit records": "SELECT count(*) FROM synthetic.ai_audit_record",
    "evaluations with a recorded reason/snapshot": (
        "SELECT count(*) FROM synthetic.eligibility_evaluation "
        "WHERE reason_detail IS NOT NULL OR input_snapshot IS NOT NULL"
    ),
}


def _refuse_destructive_downgrade(revision_id: str, data_at_risk: dict[str, str]) -> None:
    """Abort a downgrade that would drop recorded data unless `-x allow_data_loss=true`."""
    if context.is_offline_mode():
        return
    if context.get_x_argument(as_dictionary=True).get("allow_data_loss", "").lower() == "true":
        return
    bind = op.get_bind()
    found = {
        label: n for label, sql in data_at_risk.items() if (n := bind.execute(text(sql)).scalar_one())
    }
    if found:
        summary = ", ".join(f"{n} {label}" for label, n in found.items())
        raise RuntimeError(
            f"Refusing to downgrade {revision_id}: it would permanently delete {summary}. "
            "Back up the database first, then rerun with `-x allow_data_loss=true` if the loss "
            "is intended."
        )


def upgrade() -> None:
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    _refuse_destructive_downgrade(revision, _DATA_AT_RISK)
    for stmt in _DOWNGRADE:
        op.execute(stmt)
