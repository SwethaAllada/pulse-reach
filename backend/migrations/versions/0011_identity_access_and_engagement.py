"""Identity, access control, audit and patient engagement (schemas `identity`, `engagement`).

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-20

Additive only: two new schemas; nothing in `official`, `clinical` or `synthetic` is altered, so
existing rules, evaluations, facility data and synthetic records are preserved and reseeding keeps
working (new tables reference synthetic patients by `patient_id` text, without foreign keys).

- identity: organization, user_account, membership, auth_session, auth_token, one_time_token,
  patient_organization, patient_assignment, patient_invitation, patient_link, audit_event
- engagement: follow_up_task, follow_up_task_event, patient_request
- `identity.audit_event` and `engagement.follow_up_task_event` are append-only (UPDATE, DELETE and
  TRUNCATE rejected) unless `pulsereach.allow_identity_reset = 'on'` is set in the transaction.

Downgrade drops accounts, links, tasks and audit history; it refuses while such data exists unless
explicitly allowed (`alembic -x allow_data_loss=true downgrade 0010`).

Frozen static DDL: does not import live ORM metadata (`app/models/identity.py` mirrors it).
"""

from __future__ import annotations

from alembic import context, op
from sqlalchemy import text

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

_ROLES = "('SYSTEM_ADMIN', 'POPULATION_HEALTH_MANAGER', 'CARE_COORDINATOR', 'CLINICIAN', 'PATIENT')"
_TS = "TIMESTAMP WITH TIME ZONE"

_UPGRADE = (
    "CREATE SCHEMA IF NOT EXISTS identity",
    "CREATE SCHEMA IF NOT EXISTS engagement",
    f"""
    CREATE TABLE identity.organization (
        organization_id VARCHAR(36) NOT NULL,
        name TEXT NOT NULL,
        slug VARCHAR(64) NOT NULL,
        is_active BOOLEAN NOT NULL DEFAULT true,
        created_at {_TS} NOT NULL,
        created_by VARCHAR(36),
        CONSTRAINT pk_organization PRIMARY KEY (organization_id),
        CONSTRAINT uq_organization_slug UNIQUE (slug),
        CONSTRAINT ck_organization_name_nonempty CHECK (length(trim(name)) > 0)
    )
    """,
    f"""
    CREATE TABLE identity.user_account (
        user_id VARCHAR(36) NOT NULL,
        email VARCHAR(320) NOT NULL,
        password_hash TEXT,
        full_name TEXT NOT NULL,
        preferred_language VARCHAR(8) NOT NULL DEFAULT 'en',
        is_active BOOLEAN NOT NULL DEFAULT true,
        failed_login_count INTEGER NOT NULL DEFAULT 0,
        locked_until {_TS},
        password_changed_at {_TS},
        last_login_at {_TS},
        created_at {_TS} NOT NULL,
        updated_at {_TS} NOT NULL,
        CONSTRAINT pk_user_account PRIMARY KEY (user_id),
        CONSTRAINT uq_user_account_email UNIQUE (email),
        CONSTRAINT ck_user_account_email_lowercase CHECK (email = lower(email)),
        CONSTRAINT ck_user_account_preferred_language CHECK (preferred_language IN ('en', 'ar')),
        CONSTRAINT ck_user_account_failed_login_count_nonnegative CHECK (failed_login_count >= 0)
    )
    """,
    f"""
    CREATE TABLE identity.membership (
        membership_id VARCHAR(36) NOT NULL,
        user_id VARCHAR(36) NOT NULL,
        organization_id VARCHAR(36) NOT NULL,
        role VARCHAR(40) NOT NULL,
        patient_access VARCHAR(16) NOT NULL DEFAULT 'assigned',
        is_active BOOLEAN NOT NULL DEFAULT true,
        created_at {_TS} NOT NULL,
        created_by VARCHAR(36),
        updated_at {_TS} NOT NULL,
        CONSTRAINT pk_membership PRIMARY KEY (membership_id),
        CONSTRAINT uq_membership_user_organization UNIQUE (user_id, organization_id),
        CONSTRAINT fk_membership_user_id_user_account FOREIGN KEY (user_id)
            REFERENCES identity.user_account (user_id) ON DELETE RESTRICT,
        CONSTRAINT fk_membership_organization_id_organization FOREIGN KEY (organization_id)
            REFERENCES identity.organization (organization_id) ON DELETE RESTRICT,
        CONSTRAINT ck_membership_role CHECK (role IN {_ROLES}),
        CONSTRAINT ck_membership_patient_access CHECK (patient_access IN ('assigned', 'organization'))
    )
    """,
    "CREATE INDEX ix_membership_organization_role ON identity.membership (organization_id, role)",
    f"""
    CREATE TABLE identity.auth_session (
        session_id VARCHAR(36) NOT NULL,
        user_id VARCHAR(36) NOT NULL,
        organization_id VARCHAR(36),
        created_at {_TS} NOT NULL,
        expires_at {_TS} NOT NULL,
        revoked_at {_TS},
        revoke_reason VARCHAR(64),
        CONSTRAINT pk_auth_session PRIMARY KEY (session_id),
        CONSTRAINT fk_auth_session_user_id_user_account FOREIGN KEY (user_id)
            REFERENCES identity.user_account (user_id) ON DELETE RESTRICT,
        CONSTRAINT fk_auth_session_organization_id_organization FOREIGN KEY (organization_id)
            REFERENCES identity.organization (organization_id) ON DELETE RESTRICT
    )
    """,
    "CREATE INDEX ix_auth_session_user ON identity.auth_session (user_id)",
    f"""
    CREATE TABLE identity.auth_token (
        token_hash VARCHAR(64) NOT NULL,
        session_id VARCHAR(36) NOT NULL,
        kind VARCHAR(8) NOT NULL,
        issued_at {_TS} NOT NULL,
        expires_at {_TS} NOT NULL,
        used_at {_TS},
        revoked_at {_TS},
        CONSTRAINT pk_auth_token PRIMARY KEY (token_hash),
        CONSTRAINT fk_auth_token_session_id_auth_session FOREIGN KEY (session_id)
            REFERENCES identity.auth_session (session_id) ON DELETE RESTRICT,
        CONSTRAINT ck_auth_token_kind CHECK (kind IN ('access', 'refresh')),
        CONSTRAINT ck_auth_token_only_refresh_used CHECK (used_at IS NULL OR kind = 'refresh')
    )
    """,
    "CREATE INDEX ix_auth_token_session ON identity.auth_token (session_id)",
    f"""
    CREATE TABLE identity.one_time_token (
        token_hash VARCHAR(64) NOT NULL,
        user_id VARCHAR(36) NOT NULL,
        purpose VARCHAR(16) NOT NULL,
        created_at {_TS} NOT NULL,
        created_by VARCHAR(36),
        expires_at {_TS} NOT NULL,
        used_at {_TS},
        CONSTRAINT pk_one_time_token PRIMARY KEY (token_hash),
        CONSTRAINT fk_one_time_token_user_id_user_account FOREIGN KEY (user_id)
            REFERENCES identity.user_account (user_id) ON DELETE RESTRICT,
        CONSTRAINT ck_one_time_token_purpose CHECK (purpose IN ('password_reset', 'activation'))
    )
    """,
    "CREATE INDEX ix_one_time_token_user ON identity.one_time_token (user_id)",
    f"""
    CREATE TABLE identity.patient_organization (
        patient_id VARCHAR(64) NOT NULL,
        organization_id VARCHAR(36) NOT NULL,
        created_at {_TS} NOT NULL,
        created_by VARCHAR(36),
        CONSTRAINT pk_patient_organization PRIMARY KEY (patient_id),
        CONSTRAINT fk_patient_organization_organization_id_organization FOREIGN KEY (organization_id)
            REFERENCES identity.organization (organization_id) ON DELETE RESTRICT
    )
    """,
    "CREATE INDEX ix_patient_organization_org ON identity.patient_organization (organization_id)",
    f"""
    CREATE TABLE identity.patient_assignment (
        assignment_id VARCHAR(36) NOT NULL,
        organization_id VARCHAR(36) NOT NULL,
        staff_user_id VARCHAR(36) NOT NULL,
        patient_id VARCHAR(64) NOT NULL,
        is_active BOOLEAN NOT NULL DEFAULT true,
        created_at {_TS} NOT NULL,
        created_by VARCHAR(36),
        ended_at {_TS},
        ended_by VARCHAR(36),
        CONSTRAINT pk_patient_assignment PRIMARY KEY (assignment_id),
        CONSTRAINT fk_patient_assignment_organization_id_organization FOREIGN KEY (organization_id)
            REFERENCES identity.organization (organization_id) ON DELETE RESTRICT,
        CONSTRAINT fk_patient_assignment_staff_user_id_user_account FOREIGN KEY (staff_user_id)
            REFERENCES identity.user_account (user_id) ON DELETE RESTRICT,
        CONSTRAINT ck_patient_assignment_active_matches_ended CHECK (is_active = (ended_at IS NULL))
    )
    """,
    "CREATE UNIQUE INDEX uq_patient_assignment_active ON identity.patient_assignment "
    "(staff_user_id, patient_id) WHERE is_active",
    "CREATE INDEX ix_patient_assignment_org_staff ON identity.patient_assignment (organization_id, staff_user_id)",
    "CREATE INDEX ix_patient_assignment_patient ON identity.patient_assignment (patient_id)",
    f"""
    CREATE TABLE identity.patient_invitation (
        invitation_id VARCHAR(36) NOT NULL,
        organization_id VARCHAR(36) NOT NULL,
        patient_id VARCHAR(64) NOT NULL,
        code_hash VARCHAR(64) NOT NULL,
        created_at {_TS} NOT NULL,
        created_by VARCHAR(36) NOT NULL,
        expires_at {_TS} NOT NULL,
        failed_attempts INTEGER NOT NULL DEFAULT 0,
        used_at {_TS},
        used_by VARCHAR(36),
        revoked_at {_TS},
        CONSTRAINT pk_patient_invitation PRIMARY KEY (invitation_id),
        CONSTRAINT uq_patient_invitation_code_hash UNIQUE (code_hash),
        CONSTRAINT fk_patient_invitation_organization_id_organization FOREIGN KEY (organization_id)
            REFERENCES identity.organization (organization_id) ON DELETE RESTRICT
    )
    """,
    "CREATE INDEX ix_patient_invitation_patient ON identity.patient_invitation (patient_id)",
    f"""
    CREATE TABLE identity.patient_link (
        link_id VARCHAR(36) NOT NULL,
        user_id VARCHAR(36) NOT NULL,
        patient_id VARCHAR(64) NOT NULL,
        organization_id VARCHAR(36) NOT NULL,
        status VARCHAR(16) NOT NULL,
        verification_method VARCHAR(64) NOT NULL,
        invitation_id VARCHAR(36),
        verified_at {_TS} NOT NULL,
        revoked_at {_TS},
        revoked_by VARCHAR(36),
        CONSTRAINT pk_patient_link PRIMARY KEY (link_id),
        CONSTRAINT fk_patient_link_user_id_user_account FOREIGN KEY (user_id)
            REFERENCES identity.user_account (user_id) ON DELETE RESTRICT,
        CONSTRAINT fk_patient_link_organization_id_organization FOREIGN KEY (organization_id)
            REFERENCES identity.organization (organization_id) ON DELETE RESTRICT,
        CONSTRAINT fk_patient_link_invitation_id_patient_invitation FOREIGN KEY (invitation_id)
            REFERENCES identity.patient_invitation (invitation_id) ON DELETE RESTRICT,
        CONSTRAINT ck_patient_link_status CHECK (status IN ('active', 'revoked')),
        CONSTRAINT ck_patient_link_revoked_consistency CHECK ((status = 'revoked') = (revoked_at IS NOT NULL))
    )
    """,
    "CREATE UNIQUE INDEX uq_patient_link_active_patient ON identity.patient_link (patient_id) "
    "WHERE status = 'active'",
    "CREATE UNIQUE INDEX uq_patient_link_active_user ON identity.patient_link (user_id) WHERE status = 'active'",
    "CREATE INDEX ix_patient_link_org ON identity.patient_link (organization_id)",
    f"""
    CREATE TABLE identity.audit_event (
        event_id VARCHAR(36) NOT NULL,
        occurred_at {_TS} NOT NULL,
        request_id VARCHAR(64),
        actor_user_id VARCHAR(36),
        actor_role VARCHAR(40),
        organization_id VARCHAR(36),
        permission VARCHAR(64),
        action VARCHAR(64) NOT NULL,
        resource_type VARCHAR(40) NOT NULL,
        resource_id VARCHAR(128),
        patient_id VARCHAR(64),
        outcome VARCHAR(16) NOT NULL,
        status_code INTEGER,
        details JSONB NOT NULL DEFAULT '{{}}'::jsonb,
        CONSTRAINT pk_audit_event PRIMARY KEY (event_id),
        CONSTRAINT ck_audit_event_outcome CHECK (outcome IN ('success', 'denied', 'failed'))
    )
    """,
    "CREATE INDEX ix_audit_event_org_occurred ON identity.audit_event (organization_id, occurred_at)",
    "CREATE INDEX ix_audit_event_actor ON identity.audit_event (actor_user_id, occurred_at)",
    "CREATE INDEX ix_audit_event_patient ON identity.audit_event (patient_id, occurred_at)",
    f"""
    CREATE TABLE engagement.follow_up_task (
        task_id VARCHAR(36) NOT NULL,
        organization_id VARCHAR(36) NOT NULL,
        patient_id VARCHAR(64) NOT NULL,
        care_gap_id VARCHAR(64),
        rule_id VARCHAR(128),
        assigned_to_user_id VARCHAR(36),
        created_by_user_id VARCHAR(36) NOT NULL,
        status VARCHAR(24) NOT NULL,
        due_date DATE,
        language VARCHAR(8) NOT NULL,
        message_key VARCHAR(64) NOT NULL,
        patient_visible BOOLEAN NOT NULL DEFAULT true,
        staff_note TEXT,
        patient_reported_completion BOOLEAN NOT NULL DEFAULT false,
        completion_follow_up_id VARCHAR(64),
        escalated_at {_TS},
        created_at {_TS} NOT NULL,
        updated_at {_TS} NOT NULL,
        completed_at {_TS},
        CONSTRAINT pk_follow_up_task PRIMARY KEY (task_id),
        CONSTRAINT fk_follow_up_task_organization_id_organization FOREIGN KEY (organization_id)
            REFERENCES identity.organization (organization_id) ON DELETE RESTRICT,
        CONSTRAINT fk_follow_up_task_assigned_to_user_id_user_account FOREIGN KEY (assigned_to_user_id)
            REFERENCES identity.user_account (user_id) ON DELETE RESTRICT,
        CONSTRAINT ck_follow_up_task_status CHECK (status IN ('open', 'awaiting_patient',
            'patient_responded', 'in_progress', 'completed', 'cancelled')),
        CONSTRAINT ck_follow_up_task_language CHECK (language IN ('en', 'ar')),
        CONSTRAINT ck_follow_up_task_completed_at CHECK ((status = 'completed') = (completed_at IS NOT NULL))
    )
    """,
    "CREATE INDEX ix_follow_up_task_org_status ON engagement.follow_up_task (organization_id, status)",
    "CREATE INDEX ix_follow_up_task_patient ON engagement.follow_up_task (patient_id)",
    "CREATE INDEX ix_follow_up_task_assignee ON engagement.follow_up_task (assigned_to_user_id, status)",
    f"""
    CREATE TABLE engagement.follow_up_task_event (
        event_id VARCHAR(36) NOT NULL,
        task_id VARCHAR(36) NOT NULL,
        organization_id VARCHAR(36) NOT NULL,
        patient_id VARCHAR(64) NOT NULL,
        actor_user_id VARCHAR(36) NOT NULL,
        actor_role VARCHAR(40) NOT NULL,
        event_type VARCHAR(32) NOT NULL,
        visibility VARCHAR(16) NOT NULL,
        from_status VARCHAR(24),
        to_status VARCHAR(24),
        response_code VARCHAR(32),
        message TEXT,
        created_at {_TS} NOT NULL,
        CONSTRAINT pk_follow_up_task_event PRIMARY KEY (event_id),
        CONSTRAINT fk_follow_up_task_event_task_id_follow_up_task FOREIGN KEY (task_id)
            REFERENCES engagement.follow_up_task (task_id) ON DELETE RESTRICT,
        CONSTRAINT ck_follow_up_task_event_visibility CHECK (visibility IN ('patient', 'internal')),
        CONSTRAINT ck_follow_up_task_event_event_type CHECK (event_type IN ('created', 'assigned',
            'status_changed', 'due_date_changed', 'staff_note', 'staff_message', 'patient_response',
            'assistance_requested', 'appointment_requested', 'escalated', 'completed'))
    )
    """,
    "CREATE INDEX ix_follow_up_task_event_task ON engagement.follow_up_task_event (task_id, created_at)",
    f"""
    CREATE TABLE engagement.patient_request (
        request_id VARCHAR(36) NOT NULL,
        organization_id VARCHAR(36) NOT NULL,
        patient_id VARCHAR(64) NOT NULL,
        submitted_by_user_id VARCHAR(36) NOT NULL,
        request_type VARCHAR(24) NOT NULL,
        status VARCHAR(16) NOT NULL,
        task_id VARCHAR(36),
        care_gap_id VARCHAR(64),
        appointment_id VARCHAR(64),
        change_action VARCHAR(16),
        preferred_dates JSONB NOT NULL DEFAULT '[]'::jsonb,
        preferred_time_of_day VARCHAR(16),
        message TEXT,
        language VARCHAR(8) NOT NULL,
        staff_response TEXT,
        internal_note TEXT,
        handled_by_user_id VARCHAR(36),
        created_at {_TS} NOT NULL,
        updated_at {_TS} NOT NULL,
        CONSTRAINT pk_patient_request PRIMARY KEY (request_id),
        CONSTRAINT fk_patient_request_organization_id_organization FOREIGN KEY (organization_id)
            REFERENCES identity.organization (organization_id) ON DELETE RESTRICT,
        CONSTRAINT fk_patient_request_task_id_follow_up_task FOREIGN KEY (task_id)
            REFERENCES engagement.follow_up_task (task_id) ON DELETE RESTRICT,
        CONSTRAINT ck_patient_request_request_type CHECK (request_type IN ('appointment', 'assistance',
            'appointment_change')),
        CONSTRAINT ck_patient_request_status CHECK (status IN ('submitted', 'acknowledged', 'scheduled',
            'declined', 'closed', 'cancelled')),
        CONSTRAINT ck_patient_request_language CHECK (language IN ('en', 'ar')),
        CONSTRAINT ck_patient_request_change_requires_appointment CHECK (request_type <> 'appointment_change'
            OR (appointment_id IS NOT NULL AND change_action IS NOT NULL)),
        CONSTRAINT ck_patient_request_change_action CHECK (change_action IS NULL OR (
            request_type = 'appointment_change' AND change_action IN ('cancel', 'reschedule'))),
        CONSTRAINT ck_patient_request_preferred_time_of_day CHECK (preferred_time_of_day IS NULL
            OR preferred_time_of_day IN ('morning', 'afternoon', 'evening'))
    )
    """,
    "CREATE INDEX ix_patient_request_org_status ON engagement.patient_request (organization_id, status)",
    "CREATE INDEX ix_patient_request_patient ON engagement.patient_request (patient_id, created_at)",
    """
    CREATE FUNCTION identity.reject_audit_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF current_setting('pulsereach.allow_identity_reset', true) = 'on' THEN
            RETURN COALESCE(OLD, NEW);
        END IF;
        RAISE EXCEPTION '% on %.% is not allowed: append-only audit history',
            TG_OP, TG_TABLE_SCHEMA, TG_TABLE_NAME USING ERRCODE = 'restrict_violation';
    END;
    $$
    """,
    """
    CREATE TRIGGER trg_audit_event_append_only BEFORE UPDATE OR DELETE ON identity.audit_event
        FOR EACH ROW EXECUTE FUNCTION identity.reject_audit_mutation()
    """,
    """
    CREATE TRIGGER trg_audit_event_no_truncate BEFORE TRUNCATE ON identity.audit_event
        FOR EACH STATEMENT EXECUTE FUNCTION identity.reject_audit_mutation()
    """,
    """
    CREATE TRIGGER trg_follow_up_task_event_append_only BEFORE UPDATE OR DELETE
        ON engagement.follow_up_task_event FOR EACH ROW EXECUTE FUNCTION identity.reject_audit_mutation()
    """,
    """
    CREATE TRIGGER trg_follow_up_task_event_no_truncate BEFORE TRUNCATE ON engagement.follow_up_task_event
        FOR EACH STATEMENT EXECUTE FUNCTION identity.reject_audit_mutation()
    """,
)

_DOWNGRADE = (
    "DROP SCHEMA IF EXISTS engagement CASCADE",
    "DROP SCHEMA IF EXISTS identity CASCADE",
)

_DATA_AT_RISK = {
    "user accounts": "SELECT count(*) FROM identity.user_account",
    "audit events": "SELECT count(*) FROM identity.audit_event",
    "follow-up tasks": "SELECT count(*) FROM engagement.follow_up_task",
    "patient requests": "SELECT count(*) FROM engagement.patient_request",
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
