"""Request/response schemas for authentication, profile and administration endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Locale = Literal["en", "ar"]
Email = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=320)]
Password = Annotated[str, StringConstraints(min_length=1, max_length=1024)]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
AssignableRole = Literal["SYSTEM_ADMIN", "POPULATION_HEALTH_MANAGER", "CARE_COORDINATOR", "CLINICIAN"]
PatientAccess = Literal["assigned", "organization"]
OUT_OF_BAND = "out_of_band_not_sent"


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LoginIn(_In):
    email: Email
    password: Password
    organization_id: str | None = None


class RefreshIn(_In):
    refresh_token: Annotated[str, StringConstraints(min_length=1, max_length=256)]


class SwitchOrganizationIn(_In):
    organization_id: str


class RegisterIn(_In):
    email: Email
    password: Password
    full_name: Name
    preferred_language: Locale | None = None


class PasswordChangeIn(_In):
    current_password: Password
    new_password: Password


class PasswordResetRequestIn(_In):
    email: Email


class PasswordResetConfirmIn(_In):
    token: Annotated[str, StringConstraints(min_length=1, max_length=256)]
    new_password: Password


class MessageOut(BaseModel):
    message: str
    message_key: str
    locale: Locale
    direction: Literal["ltr", "rtl"]


class UserOut(BaseModel):
    user_id: str
    email: str
    full_name: str
    preferred_language: Locale
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None = None


class MembershipOut(BaseModel):
    organization_id: str
    organization_name: str
    role: str
    patient_access: PatientAccess
    is_active: bool


class TokenOut(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    refresh_token: str
    refresh_expires_in: int
    user: UserOut
    organization_id: str | None
    role: str | None
    permissions: list[str]


class MeOut(BaseModel):
    user: UserOut
    organization_id: str | None
    role: str | None
    permissions: list[str]
    patient_linked: bool
    memberships: list[MembershipOut]
    locale: Locale
    direction: Literal["ltr", "rtl"]


class MeUpdateIn(_In):
    full_name: Name | None = None
    preferred_language: Locale | None = None


class PreferencesOut(BaseModel):
    preferred_language: Locale
    locale: Locale
    direction: Literal["ltr", "rtl"]
    supported_locales: list[Locale] = Field(default_factory=lambda: ["en", "ar"])
    default_locale: Locale


class PreferencesIn(_In):
    preferred_language: Locale


# --- administration -------------------------------------------------------------------------


class OrganizationIn(_In):
    name: Name
    slug: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=63)]


class OrganizationOut(BaseModel):
    organization_id: str
    name: str
    slug: str
    is_active: bool
    created_at: datetime


class OrganizationsOut(BaseModel):
    items: list[OrganizationOut]


class PatientOwnershipIn(_In):
    patient_ids: list[Annotated[str, StringConstraints(min_length=1, max_length=64)]] | None = Field(
        default=None, max_length=1000
    )
    region_id: int | None = Field(default=None, ge=1, le=3)


class PatientOwnershipOut(BaseModel):
    organization_id: str
    added: int
    already_owned: int


class PatientReleaseIn(_In):
    patient_ids: list[str] = Field(min_length=1, max_length=1000)


class PatientReleaseOut(BaseModel):
    organization_id: str
    released: int


class StaffCreateIn(_In):
    email: Email
    full_name: Name
    role: AssignableRole
    patient_access: PatientAccess | None = None
    preferred_language: Locale = "en"


class MemberOut(BaseModel):
    user_id: str
    email: str
    full_name: str
    preferred_language: Locale
    account_active: bool
    role: str
    patient_access: PatientAccess
    membership_active: bool
    password_set: bool


class PaginatedMembersOut(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[MemberOut]


class OneTimeTokenOut(BaseModel):
    purpose: Literal["activation", "password_reset"]
    token: str
    expires_at: datetime
    delivery: str = Field(
        default=OUT_OF_BAND,
        description="PulseReach sends no e-mail/SMS: hand the code to the user through an approved channel.",
    )


class StaffCreateOut(BaseModel):
    member: MemberOut
    activation: OneTimeTokenOut


class MemberUpdateIn(_In):
    full_name: Name | None = None
    role: AssignableRole | None = None
    patient_access: PatientAccess | None = None
    membership_active: bool | None = None


class AccountStatusOut(BaseModel):
    user_id: str
    scope: Literal["account", "membership"]
    active: bool


class AssignmentIn(_In):
    staff_user_id: str
    patient_id: Annotated[str, StringConstraints(min_length=1, max_length=64)]


class AssignmentOut(BaseModel):
    assignment_id: str
    organization_id: str
    staff_user_id: str
    patient_id: str
    is_active: bool
    created_at: datetime
    created_by: str | None
    ended_at: datetime | None = None


class AssignableStaffOut(BaseModel):
    """Minimum needed to choose an assignee: no e-mail, account state or other user metadata."""

    user_id: str
    full_name: str
    role: str


class AssignableStaffListOut(BaseModel):
    items: list[AssignableStaffOut]


class PaginatedAssignmentsOut(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[AssignmentOut]


class PatientLinkOut(BaseModel):
    link_id: str
    user_id: str
    patient_id: str
    organization_id: str
    status: Literal["active", "revoked"]
    verification_method: str
    verified_at: datetime
    revoked_at: datetime | None = None


class PaginatedPatientLinksOut(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[PatientLinkOut]


class InvitationOut(BaseModel):
    invitation_id: str
    patient_id: str
    code: str
    expires_at: datetime
    delivery: str = OUT_OF_BAND


class AuditEventOut(BaseModel):
    event_id: str
    occurred_at: datetime
    request_id: str | None
    actor_user_id: str | None
    actor_role: str | None
    organization_id: str | None
    permission: str | None
    action: str
    resource_type: str
    resource_id: str | None
    patient_id: str | None
    outcome: Literal["success", "denied", "failed"]
    status_code: int | None
    details: dict[str, Any]


class PaginatedAuditEventsOut(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[AuditEventOut]
