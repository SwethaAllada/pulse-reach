"""Workflow status history and follow-up event integrity (BE-08 … BE-15).

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-19

- `synthetic.workflow_status_event`: append-only history of every appointment and referral
  create/status change (prior and new status, dates, actor), so PATCH no longer erases history.
- `synthetic.care_gap_follow_up_event`:
  - 0008 CHECK constraints renamed to the project naming convention (they were double-prefixed
    and hashed);
  - `contact_consent_id` gets a composite FK to a *granting contact* consent of the same
    patient and run (as `outreach_event` has), so missing or non-granting consent can never be
    recorded as authorising outreach;
  - `appointment_id` / `referral_id` link appointment/referral events to the workflow row;
  - CHECKs on the outcome vocabulary (no "sent"/"delivered": outreach is simulated only) and
    on completion events requiring documented evidence.

New CHECK/FK constraints on the existing table are added `NOT VALID` so rows written before
this revision are kept (the table is append-only); they are enforced for every new row.

Frozen static DDL: does not import live ORM metadata.
"""

from __future__ import annotations

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

_FUP = "synthetic.care_gap_follow_up_event"

_UPGRADE = (
    # -- care_gap_follow_up_event: normalise 0008 CHECK names ----------------------------------
    f"""
    DO $$
    DECLARE c record;
    BEGIN
        FOR c IN SELECT conname FROM pg_constraint
                 WHERE conrelid = '{_FUP}'::regclass AND contype = 'c'
        LOOP
            EXECUTE format('ALTER TABLE {_FUP} DROP CONSTRAINT %I', c.conname);
        END LOOP;
    END $$;
    """,
    f"""
    ALTER TABLE {_FUP}
        ADD CONSTRAINT ck_care_gap_follow_up_event_is_synthetic CHECK (is_synthetic),
        ADD CONSTRAINT ck_care_gap_follow_up_event_pk_prefix
            CHECK (follow_up_id ~ '^SYNTH-FUP-[0-9]{{6,}}$'),
        ADD CONSTRAINT ck_care_gap_follow_up_event_event_type CHECK (event_type IN (
            'outreach_attempted', 'outreach_suppressed', 'appointment_scheduled',
            'appointment_updated', 'referral_created', 'referral_updated',
            'completion_documented', 'note_recorded')),
        ADD CONSTRAINT ck_care_gap_follow_up_event_outreach_requires_consent
            CHECK (event_type <> 'outreach_attempted' OR contact_consent_id IS NOT NULL),
        ADD CONSTRAINT ck_care_gap_follow_up_event_suppressed_requires_reason
            CHECK (event_type <> 'outreach_suppressed' OR suppression_reason IS NOT NULL)
    """,
    # -- care_gap_follow_up_event: new columns -------------------------------------------------
    f"""
    ALTER TABLE {_FUP}
        ADD COLUMN appointment_id TEXT,
        ADD COLUMN referral_id TEXT,
        ADD COLUMN contact_consent_marker BOOLEAN
            GENERATED ALWAYS AS (CASE WHEN contact_consent_id IS NOT NULL THEN TRUE END) STORED
    """,
    f"""
    ALTER TABLE {_FUP}
        ADD CONSTRAINT ck_care_gap_follow_up_event_outcome_status CHECK (
            outcome_status IS NULL OR outcome_status IN (
                'noted', 'completed', 'suppressed', 'simulated_not_sent', 'status_recorded'))
            NOT VALID,
        ADD CONSTRAINT ck_care_gap_follow_up_event_completion_requires_evidence CHECK (
            event_type <> 'completion_documented'
            OR (documented_evidence AND evidence_reference IS NOT NULL
                AND outcome_status = 'completed'))
            NOT VALID,
        ADD CONSTRAINT ck_care_gap_follow_up_event_appointment_link CHECK (
            (event_type IN ('appointment_scheduled', 'appointment_updated'))
            = (appointment_id IS NOT NULL)),
        ADD CONSTRAINT ck_care_gap_follow_up_event_referral_link CHECK (
            (event_type IN ('referral_created', 'referral_updated')) = (referral_id IS NOT NULL)),
        ADD CONSTRAINT fk_care_gap_follow_up_event_contact_consent_id_consent
            FOREIGN KEY (run_id, patient_id, contact_consent_id, contact_consent_marker)
            REFERENCES synthetic.consent (run_id, patient_id, consent_id, grants_contact)
            ON DELETE RESTRICT ON UPDATE RESTRICT NOT VALID,
        ADD CONSTRAINT fk_care_gap_follow_up_event_appointment_id_appointment
            FOREIGN KEY (run_id, patient_id, appointment_id)
            REFERENCES synthetic.appointment (run_id, patient_id, appointment_id)
            ON DELETE RESTRICT ON UPDATE RESTRICT,
        ADD CONSTRAINT fk_care_gap_follow_up_event_referral_id_referral
            FOREIGN KEY (run_id, patient_id, referral_id)
            REFERENCES synthetic.referral (run_id, patient_id, referral_id)
            ON DELETE RESTRICT ON UPDATE RESTRICT
    """,
    # -- workflow_status_event -----------------------------------------------------------------
    """
    CREATE TABLE synthetic.workflow_status_event (
        status_event_id TEXT NOT NULL,
        run_id TEXT NOT NULL,
        patient_id TEXT NOT NULL,
        is_synthetic BOOLEAN NOT NULL DEFAULT true,
        entity_type TEXT NOT NULL,
        appointment_id TEXT,
        referral_id TEXT,
        care_gap_id TEXT,
        from_status TEXT,
        to_status TEXT NOT NULL,
        scheduled_datetime TIMESTAMP WITH TIME ZONE,
        initiated_date DATE,
        completed_date DATE,
        recorded_by TEXT NOT NULL,
        recorded_at TIMESTAMP WITH TIME ZONE NOT NULL,
        note TEXT,
        CONSTRAINT pk_workflow_status_event PRIMARY KEY (status_event_id),
        CONSTRAINT fk_workflow_status_event_appointment_id_appointment
            FOREIGN KEY (run_id, patient_id, appointment_id)
            REFERENCES synthetic.appointment (run_id, patient_id, appointment_id)
            ON DELETE RESTRICT ON UPDATE RESTRICT,
        CONSTRAINT fk_workflow_status_event_referral_id_referral
            FOREIGN KEY (run_id, patient_id, referral_id)
            REFERENCES synthetic.referral (run_id, patient_id, referral_id)
            ON DELETE RESTRICT ON UPDATE RESTRICT,
        CONSTRAINT fk_workflow_status_event_care_gap_id_care_gap
            FOREIGN KEY (run_id, patient_id, care_gap_id)
            REFERENCES synthetic.care_gap (run_id, patient_id, care_gap_id)
            ON DELETE RESTRICT ON UPDATE RESTRICT,
        CONSTRAINT ck_workflow_status_event_is_synthetic CHECK (is_synthetic),
        CONSTRAINT ck_workflow_status_event_pk_prefix
            CHECK (status_event_id ~ '^SYNTH-WSE-[0-9]{6,}$'),
        CONSTRAINT ck_workflow_status_event_entity_link CHECK (
            (entity_type = 'appointment' AND appointment_id IS NOT NULL AND referral_id IS NULL)
            OR (entity_type = 'referral' AND referral_id IS NOT NULL AND appointment_id IS NULL)),
        CONSTRAINT ck_workflow_status_event_status_vocabulary CHECK (
            (entity_type = 'appointment'
             AND to_status IN ('scheduled', 'attended', 'no_show', 'cancelled_by_patient',
                               'cancelled_by_facility', 'rescheduled')
             AND (from_status IS NULL OR from_status IN ('scheduled', 'rescheduled')))
            OR (entity_type = 'referral'
             AND to_status IN ('pending', 'initiated', 'completed', 'declined', 'cancelled')
             AND (from_status IS NULL OR from_status IN ('pending', 'initiated')))),
        CONSTRAINT ck_workflow_status_event_creation_status CHECK (
            from_status IS NOT NULL OR to_status IN ('scheduled', 'pending', 'initiated')),
        CONSTRAINT ck_workflow_status_event_recorded_by_nonempty
            CHECK (length(btrim(recorded_by)) > 0)
    )
    """,
    "CREATE INDEX ix_workflow_status_event_appointment ON synthetic.workflow_status_event "
    "(appointment_id, recorded_at)",
    "CREATE INDEX ix_workflow_status_event_referral ON synthetic.workflow_status_event "
    "(referral_id, recorded_at)",
    "CREATE INDEX ix_workflow_status_event_patient ON synthetic.workflow_status_event "
    "(patient_id, recorded_at)",
    """
    CREATE TRIGGER trg_workflow_status_event_append_only
        BEFORE UPDATE OR DELETE ON synthetic.workflow_status_event
        FOR EACH ROW EXECUTE FUNCTION synthetic.reject_append_only_mutation()
    """,
)

_DOWNGRADE = (
    "DROP TABLE IF EXISTS synthetic.workflow_status_event",
    f"""
    ALTER TABLE {_FUP}
        DROP CONSTRAINT IF EXISTS fk_care_gap_follow_up_event_referral_id_referral,
        DROP CONSTRAINT IF EXISTS fk_care_gap_follow_up_event_appointment_id_appointment,
        DROP CONSTRAINT IF EXISTS fk_care_gap_follow_up_event_contact_consent_id_consent,
        DROP CONSTRAINT IF EXISTS ck_care_gap_follow_up_event_referral_link,
        DROP CONSTRAINT IF EXISTS ck_care_gap_follow_up_event_appointment_link,
        DROP CONSTRAINT IF EXISTS ck_care_gap_follow_up_event_completion_requires_evidence,
        DROP CONSTRAINT IF EXISTS ck_care_gap_follow_up_event_outcome_status,
        DROP COLUMN IF EXISTS contact_consent_marker,
        DROP COLUMN IF EXISTS referral_id,
        DROP COLUMN IF EXISTS appointment_id
    """,
)


def upgrade() -> None:
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in _DOWNGRADE:
        op.execute(stmt)
