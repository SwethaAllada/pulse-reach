"""Identity, access-control, audit (`identity` schema) and patient-engagement (`engagement`
schema) models — migration 0011.

These tables use their own `MetaData` (not the shared official/clinical/synthetic one) so the
Phase 3 three-schema design is unchanged. In `DATA_SOURCE=db` they live in PostgreSQL; in
`DATA_SOURCE=memory` the same models run on an in-process SQLite database with the schema names
translated away (`app.services.identity.store`).

Patient-owned rows reference synthetic patients by `patient_id` text **without** a foreign key:
the synthetic run is deleted and recreated on reseed, and identity data must not block that.
Links are validated when they are created and resolve to "not found" if the record disappears.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from app.db.session import NAMING_CONVENTION

IDENTITY_SCHEMA = "identity"
ENGAGEMENT_SCHEMA = "engagement"
IDENTITY_SCHEMAS = (IDENTITY_SCHEMA, ENGAGEMENT_SCHEMA)

ROLES = (
    "SYSTEM_ADMIN",
    "POPULATION_HEALTH_MANAGER",
    "CARE_COORDINATOR",
    "CLINICIAN",
    "PATIENT",
)
LOCALES = ("en", "ar")
TASK_STATUSES = (
    "open",
    "awaiting_patient",
    "patient_responded",
    "in_progress",
    "completed",
    "cancelled",
)
TASK_TERMINAL_STATUSES = ("completed", "cancelled")
# Operational coordination urgency set by staff (migration 0013). Not a clinical risk score:
# care-gap priority stays with the deterministic evaluation engine.
TASK_PRIORITIES = ("routine", "high", "urgent")
# Staff-documented contact attempts (migration 0013). Documentation only: PulseReach never sends.
CONTACT_CHANNELS = ("phone", "sms", "email", "in_person", "portal")
CONTACT_OUTCOMES = ("reached", "no_answer", "left_message", "wrong_contact_details", "declined")
TASK_EVENT_TYPES = (
    "created",
    "assigned",
    "status_changed",
    "due_date_changed",
    "staff_note",
    "staff_message",
    "patient_response",
    "assistance_requested",
    "appointment_requested",
    "escalated",
    "completed",
    "priority_changed",  # 0013
    "contact_attempt",  # 0013
)
REQUEST_TYPES = ("appointment", "assistance", "appointment_change")
REQUEST_STATUSES = ("submitted", "acknowledged", "scheduled", "declined", "closed", "cancelled")

identity_metadata = MetaData(naming_convention=NAMING_CONVENTION)


class UTCDateTime(TypeDecorator):
    """Timezone-aware UTC datetimes on PostgreSQL and SQLite (which drops the offset)."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("naive datetime")
        return value.astimezone(timezone.utc) if value is not None else None

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value


_JSON = JSON().with_variant(JSONB(), "postgresql")


def _in(col: str, values: tuple[str, ...]) -> str:
    return f"{col} IN ({', '.join(repr(v) for v in values)})"


class IdentityBase(DeclarativeBase):
    metadata = identity_metadata


# --------------------------------------------------------------------------------------------
# identity
# --------------------------------------------------------------------------------------------


class Organization(IdentityBase):
    __tablename__ = "organization"

    organization_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(String(64), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(36))

    __table_args__ = (
        UniqueConstraint("slug", name="uq_organization_slug"),
        CheckConstraint("length(trim(name)) > 0", name="name_nonempty"),
        {"schema": IDENTITY_SCHEMA},
    )


class UserAccount(IdentityBase):
    __tablename__ = "user_account"

    user_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    password_hash: Mapped[str | None] = mapped_column(Text)
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    preferred_language: Mapped[str] = mapped_column(
        String(8), nullable=False, server_default=text("'en'")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    failed_login_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    locked_until: Mapped[datetime | None] = mapped_column(UTCDateTime)
    password_changed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)

    __table_args__ = (
        UniqueConstraint("email", name="uq_user_account_email"),
        CheckConstraint("email = lower(email)", name="email_lowercase"),
        CheckConstraint(_in("preferred_language", LOCALES), name="preferred_language"),
        CheckConstraint("failed_login_count >= 0", name="failed_login_count_nonnegative"),
        {"schema": IDENTITY_SCHEMA},
    )


class Membership(IdentityBase):
    """A user's role inside one organization (one role per user per organization)."""

    __tablename__ = "membership"

    membership_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        ForeignKey(f"{IDENTITY_SCHEMA}.user_account.user_id", ondelete="RESTRICT"), nullable=False
    )
    organization_id: Mapped[str] = mapped_column(
        ForeignKey(f"{IDENTITY_SCHEMA}.organization.organization_id", ondelete="RESTRICT"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(40), nullable=False)
    # 'assigned': only explicitly assigned patients; 'organization': every patient of the org.
    patient_access: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'assigned'")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(36))
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "organization_id", name="uq_membership_user_organization"),
        CheckConstraint(_in("role", ROLES), name="role"),
        CheckConstraint(_in("patient_access", ("assigned", "organization")), name="patient_access"),
        Index("ix_membership_organization_role", "organization_id", "role"),
        {"schema": IDENTITY_SCHEMA},
    )


class AuthSession(IdentityBase):
    """Server-side login session; every access/refresh token belongs to exactly one session."""

    __tablename__ = "auth_session"

    session_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        ForeignKey(f"{IDENTITY_SCHEMA}.user_account.user_id", ondelete="RESTRICT"), nullable=False
    )
    # NULL only for accounts without any membership yet (self-registered, not yet linked).
    organization_id: Mapped[str | None] = mapped_column(
        ForeignKey(f"{IDENTITY_SCHEMA}.organization.organization_id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    revoke_reason: Mapped[str | None] = mapped_column(String(64))

    __table_args__ = (
        Index("ix_auth_session_user", "user_id"),
        {"schema": IDENTITY_SCHEMA},
    )


class AuthToken(IdentityBase):
    """Access/refresh token, stored only as the SHA-256 of the random token."""

    __tablename__ = "auth_token"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey(f"{IDENTITY_SCHEMA}.auth_session.session_id", ondelete="RESTRICT"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(String(8), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    __table_args__ = (
        CheckConstraint(_in("kind", ("access", "refresh")), name="kind"),
        CheckConstraint("used_at IS NULL OR kind = 'refresh'", name="only_refresh_used"),
        Index("ix_auth_token_session", "session_id"),
        {"schema": IDENTITY_SCHEMA},
    )


class OneTimeToken(IdentityBase):
    """Single-use password-reset / account-activation token (hash only)."""

    __tablename__ = "one_time_token"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        ForeignKey(f"{IDENTITY_SCHEMA}.user_account.user_id", ondelete="RESTRICT"), nullable=False
    )
    purpose: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(36))
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    __table_args__ = (
        CheckConstraint(_in("purpose", ("password_reset", "activation")), name="purpose"),
        Index("ix_one_time_token_user", "user_id"),
        {"schema": IDENTITY_SCHEMA},
    )


class PatientOrganization(IdentityBase):
    """Which organization owns a synthetic patient record (one organization per patient)."""

    __tablename__ = "patient_organization"

    patient_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey(f"{IDENTITY_SCHEMA}.organization.organization_id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(36))

    __table_args__ = (
        Index("ix_patient_organization_org", "organization_id"),
        {"schema": IDENTITY_SCHEMA},
    )


class PatientAssignment(IdentityBase):
    __tablename__ = "patient_assignment"

    assignment_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey(f"{IDENTITY_SCHEMA}.organization.organization_id", ondelete="RESTRICT"),
        nullable=False,
    )
    staff_user_id: Mapped[str] = mapped_column(
        ForeignKey(f"{IDENTITY_SCHEMA}.user_account.user_id", ondelete="RESTRICT"), nullable=False
    )
    patient_id: Mapped[str] = mapped_column(String(64), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(36))
    ended_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    ended_by: Mapped[str | None] = mapped_column(String(36))

    __table_args__ = (
        CheckConstraint("is_active = (ended_at IS NULL)", name="active_matches_ended"),
        Index(
            "uq_patient_assignment_active",
            "staff_user_id",
            "patient_id",
            unique=True,
            postgresql_where=text("is_active"),
            sqlite_where=text("is_active"),
        ),
        Index("ix_patient_assignment_org_staff", "organization_id", "staff_user_id"),
        Index("ix_patient_assignment_patient", "patient_id"),
        {"schema": IDENTITY_SCHEMA},
    )


class PatientInvitation(IdentityBase):
    """Staff-issued one-time code that lets a patient account claim one patient record."""

    __tablename__ = "patient_invitation"

    invitation_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey(f"{IDENTITY_SCHEMA}.organization.organization_id", ondelete="RESTRICT"),
        nullable=False,
    )
    patient_id: Mapped[str] = mapped_column(String(64), nullable=False)
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    created_by: Mapped[str] = mapped_column(String(36), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    failed_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    used_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    used_by: Mapped[str | None] = mapped_column(String(36))
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    __table_args__ = (
        UniqueConstraint("code_hash", name="uq_patient_invitation_code_hash"),
        Index("ix_patient_invitation_patient", "patient_id"),
        {"schema": IDENTITY_SCHEMA},
    )


class PatientLink(IdentityBase):
    """Verified mapping of a PATIENT account to exactly one synthetic patient record."""

    __tablename__ = "patient_link"

    link_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        ForeignKey(f"{IDENTITY_SCHEMA}.user_account.user_id", ondelete="RESTRICT"), nullable=False
    )
    patient_id: Mapped[str] = mapped_column(String(64), nullable=False)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey(f"{IDENTITY_SCHEMA}.organization.organization_id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    verification_method: Mapped[str] = mapped_column(String(64), nullable=False)
    invitation_id: Mapped[str | None] = mapped_column(
        ForeignKey(f"{IDENTITY_SCHEMA}.patient_invitation.invitation_id", ondelete="RESTRICT")
    )
    verified_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    revoked_by: Mapped[str | None] = mapped_column(String(36))

    __table_args__ = (
        CheckConstraint(_in("status", ("active", "revoked")), name="status"),
        CheckConstraint("(status = 'revoked') = (revoked_at IS NOT NULL)", name="revoked_consistency"),
        Index(
            "uq_patient_link_active_patient",
            "patient_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
            sqlite_where=text("status = 'active'"),
        ),
        Index(
            "uq_patient_link_active_user",
            "user_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
            sqlite_where=text("status = 'active'"),
        ),
        Index("ix_patient_link_org", "organization_id"),
        {"schema": IDENTITY_SCHEMA},
    )


class AuditEvent(IdentityBase):
    """Append-only security/workflow audit event (UPDATE/DELETE/TRUNCATE rejected in PostgreSQL)."""

    __tablename__ = "audit_event"

    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(64))
    actor_user_id: Mapped[str | None] = mapped_column(String(36))
    actor_role: Mapped[str | None] = mapped_column(String(40))
    organization_id: Mapped[str | None] = mapped_column(String(36))
    permission: Mapped[str | None] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(40), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(128))
    patient_id: Mapped[str | None] = mapped_column(String(64))
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    status_code: Mapped[int | None] = mapped_column(Integer)
    details: Mapped[dict[str, Any]] = mapped_column(_JSON, nullable=False, default=dict)

    __table_args__ = (
        CheckConstraint(_in("outcome", ("success", "denied", "failed")), name="outcome"),
        Index("ix_audit_event_org_occurred", "organization_id", "occurred_at"),
        Index("ix_audit_event_actor", "actor_user_id", "occurred_at"),
        Index("ix_audit_event_patient", "patient_id", "occurred_at"),
        {"schema": IDENTITY_SCHEMA},
    )


# --------------------------------------------------------------------------------------------
# engagement
# --------------------------------------------------------------------------------------------


class FollowUpTask(IdentityBase):
    """Assigned, patient-facing follow-up work item linked to a care gap (optional)."""

    __tablename__ = "follow_up_task"

    task_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey(f"{IDENTITY_SCHEMA}.organization.organization_id", ondelete="RESTRICT"),
        nullable=False,
    )
    patient_id: Mapped[str] = mapped_column(String(64), nullable=False)
    care_gap_id: Mapped[str | None] = mapped_column(String(64))
    rule_id: Mapped[str | None] = mapped_column(String(128))
    assigned_to_user_id: Mapped[str | None] = mapped_column(
        ForeignKey(f"{IDENTITY_SCHEMA}.user_account.user_id", ondelete="RESTRICT")
    )
    created_by_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date)
    language: Mapped[str] = mapped_column(String(8), nullable=False)
    message_key: Mapped[str] = mapped_column(String(64), nullable=False)
    patient_visible: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    staff_note: Mapped[str | None] = mapped_column(Text)  # internal; never shown to the patient
    patient_reported_completion: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    completion_follow_up_id: Mapped[str | None] = mapped_column(String(64))
    priority: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'routine'"))  # 0013
    escalated_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    __table_args__ = (
        CheckConstraint(_in("status", TASK_STATUSES), name="status"),
        CheckConstraint(_in("language", LOCALES), name="language"),
        CheckConstraint("(status = 'completed') = (completed_at IS NOT NULL)", name="completed_at"),
        CheckConstraint(_in("priority", TASK_PRIORITIES), name="priority"),
        Index("ix_follow_up_task_org_status", "organization_id", "status"),
        Index("ix_follow_up_task_patient", "patient_id"),
        Index("ix_follow_up_task_assignee", "assigned_to_user_id", "status"),
        {"schema": ENGAGEMENT_SCHEMA},
    )


class FollowUpTaskEvent(IdentityBase):
    """Append-only history of a follow-up task. `visibility='internal'` is never shown to patients."""

    __tablename__ = "follow_up_task_event"

    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    task_id: Mapped[str] = mapped_column(
        ForeignKey(f"{ENGAGEMENT_SCHEMA}.follow_up_task.task_id", ondelete="RESTRICT"),
        nullable=False,
    )
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    patient_id: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    actor_role: Mapped[str] = mapped_column(String(40), nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    visibility: Mapped[str] = mapped_column(String(16), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(24))
    to_status: Mapped[str | None] = mapped_column(String(24))
    response_code: Mapped[str | None] = mapped_column(String(32))
    message: Mapped[str | None] = mapped_column(Text)
    # 0013: new priority for `created`/`priority_changed`; channel for `contact_attempt`
    # (its outcome is stored in `response_code`).
    priority: Mapped[str | None] = mapped_column(String(16))
    contact_channel: Mapped[str | None] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)

    __table_args__ = (
        CheckConstraint(_in("visibility", ("patient", "internal")), name="visibility"),
        CheckConstraint(_in("event_type", TASK_EVENT_TYPES), name="event_type"),
        Index("ix_follow_up_task_event_task", "task_id", "created_at"),
        {"schema": ENGAGEMENT_SCHEMA},
    )


class PatientRequest(IdentityBase):
    """Appointment / assistance / appointment-change request submitted by a patient."""

    __tablename__ = "patient_request"

    request_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey(f"{IDENTITY_SCHEMA}.organization.organization_id", ondelete="RESTRICT"),
        nullable=False,
    )
    patient_id: Mapped[str] = mapped_column(String(64), nullable=False)
    submitted_by_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    request_type: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    task_id: Mapped[str | None] = mapped_column(
        ForeignKey(f"{ENGAGEMENT_SCHEMA}.follow_up_task.task_id", ondelete="RESTRICT")
    )
    care_gap_id: Mapped[str | None] = mapped_column(String(64))
    appointment_id: Mapped[str | None] = mapped_column(String(64))
    change_action: Mapped[str | None] = mapped_column(String(16))
    preferred_dates: Mapped[list[str]] = mapped_column(_JSON, nullable=False, default=list)
    preferred_time_of_day: Mapped[str | None] = mapped_column(String(16))
    message: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(8), nullable=False)
    staff_response: Mapped[str | None] = mapped_column(Text)  # patient-visible
    internal_note: Mapped[str | None] = mapped_column(Text)  # staff only
    handled_by_user_id: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)

    __table_args__ = (
        CheckConstraint(_in("request_type", REQUEST_TYPES), name="request_type"),
        CheckConstraint(_in("status", REQUEST_STATUSES), name="status"),
        CheckConstraint(_in("language", LOCALES), name="language"),
        CheckConstraint(
            "request_type <> 'appointment_change' OR (appointment_id IS NOT NULL AND change_action IS NOT NULL)",
            name="change_requires_appointment",
        ),
        CheckConstraint(
            "change_action IS NULL OR (request_type = 'appointment_change' "
            "AND change_action IN ('cancel', 'reschedule'))",
            name="change_action",
        ),
        CheckConstraint(
            "preferred_time_of_day IS NULL OR preferred_time_of_day IN ('morning', 'afternoon', 'evening')",
            name="preferred_time_of_day",
        ),
        Index("ix_patient_request_org_status", "organization_id", "status"),
        Index("ix_patient_request_patient", "patient_id", "created_at"),
        {"schema": ENGAGEMENT_SCHEMA},
    )
