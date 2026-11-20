"""Organization administration, staff assignments, patient account links and audit retrieval.

All endpoints act inside the caller's current organization (from the authenticated session, never
from the request body). Available in `AUTH_MODE=users` only.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.auth import _users_mode_only
from app.api.v1 import get_read_repository
from app.core.auth import Principal, ensure_patient_access, require
from app.core.i18n import AppError
from app.models.identity import Membership, Organization, PatientAssignment, PatientLink, UserAccount
from app.repositories.read_repo import ReadRepository
from app.schemas.identity import (
    AccountStatusOut,
    AssignableStaffListOut,
    AssignableStaffOut,
    AssignmentIn,
    AssignmentOut,
    AuditEventOut,
    InvitationOut,
    MemberOut,
    MemberUpdateIn,
    OneTimeTokenOut,
    OrganizationIn,
    OrganizationOut,
    OrganizationsOut,
    PaginatedAssignmentsOut,
    PaginatedAuditEventsOut,
    PaginatedMembersOut,
    PaginatedPatientLinksOut,
    PatientLinkOut,
    PatientOwnershipIn,
    PatientOwnershipOut,
    PatientReleaseIn,
    PatientReleaseOut,
    StaffCreateIn,
    StaffCreateOut,
)
from app.services.identity import directory
from app.services.identity import service as auth
from app.services.identity.audit import list_events, record_event
from app.services.identity.store import identity_session

router = APIRouter(prefix="/api/v1", tags=["admin"], dependencies=[Depends(_users_mode_only)])


def _org(p: Principal) -> str:
    if p.organization_id is None:
        raise AppError(403, "error.forbidden")
    return p.organization_id


def _member_out(u: UserAccount, m: Membership) -> MemberOut:
    return MemberOut(user_id=u.user_id, email=u.email, full_name=u.full_name,
                     preferred_language=u.preferred_language, account_active=u.is_active, role=m.role,
                     patient_access=m.patient_access, membership_active=m.is_active,
                     password_set=u.password_hash is not None)


def _org_out(o: Organization) -> OrganizationOut:
    return OrganizationOut(organization_id=o.organization_id, name=o.name, slug=o.slug, is_active=o.is_active,
                           created_at=o.created_at)


def _assignment_out(a: PatientAssignment) -> AssignmentOut:
    return AssignmentOut(assignment_id=a.assignment_id, organization_id=a.organization_id,
                         staff_user_id=a.staff_user_id, patient_id=a.patient_id, is_active=a.is_active,
                         created_at=a.created_at, created_by=a.created_by, ended_at=a.ended_at)


def _link_out(link: PatientLink) -> PatientLinkOut:
    return PatientLinkOut(link_id=link.link_id, user_id=link.user_id, patient_id=link.patient_id,
                          organization_id=link.organization_id, status=link.status,
                          verification_method=link.verification_method, verified_at=link.verified_at,
                          revoked_at=link.revoked_at)


def existing_patient_ids(
    repo: ReadRepository, *, region_id: int | None = None, patient_ids: set[str] | None = None
) -> list[str]:
    out: list[str] = []
    offset = 0
    scope = frozenset(patient_ids) if patient_ids is not None else None
    while True:
        page = repo.list_patients(limit=200, offset=offset, sex=None, region_id=region_id, pathway=None,
                                  patient_ids=scope)
        out.extend(p.patient_id for p in page.items)
        offset += len(page.items)
        if not page.items or offset >= page.total:
            return out


# --- organizations -------------------------------------------------------------------------


@router.get("/admin/organizations", response_model=OrganizationsOut)
def list_organizations(p: Principal = Depends(require("organizations.manage"))) -> OrganizationsOut:
    """Organizations in which the caller holds an active membership."""
    with identity_session() as s:
        orgs = [s.get(Organization, m.organization_id) for m in auth.active_memberships(s, p.user_id)]
    return OrganizationsOut(items=[_org_out(o) for o in orgs])


@router.post("/admin/organizations", response_model=OrganizationOut, status_code=201)
def create_organization(req: OrganizationIn, p: Principal = Depends(require("organizations.manage"))) -> OrganizationOut:
    """Create an organization; the creator becomes its SYSTEM_ADMIN."""
    with identity_session() as s:
        org = directory.create_organization(s, name=req.name, slug=req.slug, created_by=p.user_id)
        directory.add_membership(s, user_id=p.user_id, organization_id=org.organization_id,
                                 role="SYSTEM_ADMIN", created_by=p.user_id)
    record_event(p, "organization.create", "organization", resource_id=org.organization_id, status_code=201,
                 permission="organizations.manage")
    return _org_out(org)


@router.post("/admin/patient-ownership", response_model=PatientOwnershipOut)
def associate_patients(
    req: PatientOwnershipIn,
    p: Principal = Depends(require("organizations.manage")),
    repo: ReadRepository = Depends(get_read_repository),
) -> PatientOwnershipOut:
    """Attach existing, unowned synthetic patients (by id list and/or region) to the caller's
    organization. Patients owned by another organization are refused (409)."""
    org = _org(p)
    if not req.patient_ids and req.region_id is None:
        raise AppError(422, "error.validation", params={"reason": "patient_ids or region_id"})
    ids: set[str] = set()
    if req.patient_ids:
        ids |= set(existing_patient_ids(repo, patient_ids=set(req.patient_ids)))
    if req.region_id is not None:
        ids |= set(existing_patient_ids(repo, region_id=req.region_id))
    try:
        with identity_session() as s:
            added, already = directory.associate_patients(s, organization_id=org, patient_ids=ids,
                                                          created_by=p.user_id)
    except HTTPException as exc:
        record_event(p, "organization.patients_associate", "organization", resource_id=org, outcome="failed",
                     status_code=exc.status_code, permission="organizations.manage")
        raise
    record_event(p, "organization.patients_associate", "organization", resource_id=org, status_code=200,
                 permission="organizations.manage", details={"added": added, "already_owned": already})
    return PatientOwnershipOut(organization_id=org, added=added, already_owned=already)


@router.post("/admin/patient-ownership/release", response_model=PatientReleaseOut)
def release_patients(req: PatientReleaseIn, p: Principal = Depends(require("organizations.manage"))) -> PatientReleaseOut:
    """Release patients owned by the caller's organization (ends assignments and portal links)."""
    org = _org(p)
    with identity_session() as s:
        n = directory.release_patients(s, organization_id=org, patient_ids=req.patient_ids, actor=p.user_id)
    record_event(p, "organization.patients_release", "organization", resource_id=org, status_code=200,
                 permission="organizations.manage", details={"released": n})
    return PatientReleaseOut(organization_id=org, released=n)


# --- users and memberships -----------------------------------------------------------------


@router.get("/admin/users", response_model=PaginatedMembersOut)
def list_users(
    role: Literal["SYSTEM_ADMIN", "POPULATION_HEALTH_MANAGER", "CARE_COORDINATOR", "CLINICIAN", "PATIENT"]
    | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    p: Principal = Depends(require("users.read")),
) -> PaginatedMembersOut:
    with identity_session() as s:
        total, rows = directory.list_members(s, _org(p), role=role, limit=limit, offset=offset)
        items = [_member_out(u, m) for u, m in rows]
    return PaginatedMembersOut(total=total, limit=limit, offset=offset, items=items)


@router.post("/admin/users", response_model=StaffCreateOut, status_code=201)
def create_staff_user(req: StaffCreateIn, p: Principal = Depends(require("users.create"))) -> StaffCreateOut:
    """Create a staff account in the caller's organization. No password is set: the response
    carries a single-use activation code to hand over out of band (nothing is e-mailed)."""
    org = _org(p)
    with identity_session() as s:
        user = auth.create_user(s, email=req.email, full_name=req.full_name, password=None,
                                preferred_language=req.preferred_language)
        m = directory.add_membership(s, user_id=user.user_id, organization_id=org, role=req.role,
                                     patient_access=req.patient_access, created_by=p.user_id)
        raw, expires = auth.issue_one_time_token(s, user.user_id, "activation", p.user_id)
        out = StaffCreateOut(member=_member_out(user, m),
                             activation=OneTimeTokenOut(purpose="activation", token=raw, expires_at=expires))
    record_event(p, "user.create", "user", resource_id=user.user_id, status_code=201, permission="users.create",
                 details={"role": req.role})
    return out


def _member(s, org: str, user_id: str) -> tuple[UserAccount, Membership]:
    m = directory.membership_in(s, user_id, org)
    u = s.get(UserAccount, user_id)
    if m is None or u is None:
        raise AppError(404, "error.not_found", detail=f"User '{user_id}' not found")
    return u, m


@router.get("/admin/users/{user_id}", response_model=MemberOut)
def get_user(user_id: str, p: Principal = Depends(require("users.read"))) -> MemberOut:
    with identity_session() as s:
        return _member_out(*_member(s, _org(p), user_id))


@router.patch("/admin/users/{user_id}", response_model=MemberOut)
def update_user(user_id: str, req: MemberUpdateIn, p: Principal = Depends(require("users.update"))) -> MemberOut:
    org = _org(p)
    with identity_session() as s:
        _member(s, org, user_id)
        u, m = directory.update_member(s, organization_id=org, user_id=user_id, actor_user_id=p.user_id,
                                       **req.model_dump(exclude_none=True))
        out = _member_out(u, m)
    record_event(p, "user.update", "user", resource_id=user_id, status_code=200, permission="users.update",
                 details={"fields": sorted(req.model_dump(exclude_none=True))})
    return out


def _set_active(user_id: str, p: Principal, active: bool) -> AccountStatusOut:
    org = _org(p)
    with identity_session() as s:
        _member(s, org, user_id)
        _, scope = directory.set_account_active(s, organization_id=org, user_id=user_id,
                                                actor_user_id=p.user_id, active=active)
    record_event(p, "user.activate" if active else "user.deactivate", "user", resource_id=user_id,
                 status_code=200, permission="users.deactivate", details={"scope": scope})
    return AccountStatusOut(user_id=user_id, scope=scope, active=active)


@router.post("/admin/users/{user_id}/deactivate", response_model=AccountStatusOut)
def deactivate_user(user_id: str, p: Principal = Depends(require("users.deactivate"))) -> AccountStatusOut:
    return _set_active(user_id, p, False)


@router.post("/admin/users/{user_id}/activate", response_model=AccountStatusOut)
def activate_user(user_id: str, p: Principal = Depends(require("users.deactivate"))) -> AccountStatusOut:
    return _set_active(user_id, p, True)


@router.post("/admin/users/{user_id}/password-reset", response_model=OneTimeTokenOut)
def issue_password_reset(user_id: str, p: Principal = Depends(require("users.update"))) -> OneTimeTokenOut:
    """Single-use reset code for out-of-band delivery; redeem at `/auth/password-reset/confirm`."""
    org = _org(p)
    with identity_session() as s:
        u, _ = _member(s, org, user_id)
        purpose = "password_reset" if u.password_hash else "activation"
        raw, expires = auth.issue_one_time_token(s, user_id, purpose, p.user_id)
    record_event(p, "user.password_reset_issued", "user", resource_id=user_id, status_code=200,
                 permission="users.update", details={"purpose": purpose})
    return OneTimeTokenOut(purpose=purpose, token=raw, expires_at=expires)


# --- assignments ---------------------------------------------------------------------------


@router.get("/admin/assignments", response_model=PaginatedAssignmentsOut)
def list_assignments(
    staff_user_id: str | None = Query(default=None),
    patient_id: str | None = Query(default=None),
    active_only: bool = Query(default=True),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    p: Principal = Depends(require("assignments.manage")),
) -> PaginatedAssignmentsOut:
    with identity_session() as s:
        total, rows = directory.list_assignments(s, organization_id=_org(p), staff_user_id=staff_user_id,
                                                 patient_id=patient_id, active_only=active_only,
                                                 limit=limit, offset=offset)
        items = [_assignment_out(a) for a in rows]
    return PaginatedAssignmentsOut(total=total, limit=limit, offset=offset, items=items)


@router.get("/admin/assignments/staff", response_model=AssignableStaffListOut)
def list_assignable_staff(p: Principal = Depends(require("assignments.manage"))) -> AssignableStaffListOut:
    """Staff of the caller's organization who can be assigned patients (id, name, role only), for the
    assignment workflow. Unlike `/admin/users` (users.read) it exposes no account administration data."""
    with identity_session() as s:
        items = [AssignableStaffOut(user_id=u.user_id, full_name=u.full_name, role=m.role)
                 for u, m in directory.assignable_staff(s, _org(p))]
    return AssignableStaffListOut(items=items)


@router.post("/admin/assignments", response_model=AssignmentOut, status_code=201)
def create_assignment(req: AssignmentIn, p: Principal = Depends(require("assignments.manage"))) -> AssignmentOut:
    org = _org(p)
    try:
        with identity_session() as s:
            a = directory.create_assignment(s, organization_id=org, staff_user_id=req.staff_user_id,
                                            patient_id=req.patient_id, created_by=p.user_id)
            out = _assignment_out(a)
    except HTTPException as exc:
        record_event(p, "assignment.create", "assignment", patient_id=req.patient_id, outcome="failed",
                     status_code=exc.status_code, permission="assignments.manage")
        if exc.status_code == 404:
            raise HTTPException(status_code=404, detail=f"Synthetic patient '{req.patient_id}' not found") from exc
        raise
    record_event(p, "assignment.create", "assignment", resource_id=out.assignment_id, patient_id=req.patient_id,
                 status_code=201, permission="assignments.manage", details={"staff_user_id": req.staff_user_id})
    return out


@router.post("/admin/assignments/{assignment_id}/end", response_model=AssignmentOut)
def end_assignment(assignment_id: str, p: Principal = Depends(require("assignments.manage"))) -> AssignmentOut:
    with identity_session() as s:
        a = directory.end_assignment(s, organization_id=_org(p), assignment_id=assignment_id, actor=p.user_id)
        out = _assignment_out(a)
    record_event(p, "assignment.end", "assignment", resource_id=assignment_id, patient_id=out.patient_id,
                 status_code=200, permission="assignments.manage")
    return out


# --- patient account links -----------------------------------------------------------------


@router.post("/patients/{patient_id}/portal-invitations", response_model=InvitationOut, status_code=201)
def create_portal_invitation(
    patient_id: str, p: Principal = Depends(require("patient_links.invite"))
) -> InvitationOut:
    """One-time code (expires) for the patient to link their account; hand it over in person or
    through an approved channel. Requires access to the patient (organization + assignment)."""
    ensure_patient_access(p, patient_id, f"Synthetic patient '{patient_id}' not found")
    with identity_session() as s:
        inv, raw = directory.create_invitation(s, organization_id=_org(p), patient_id=patient_id,
                                               created_by=p.user_id)
    record_event(p, "patient_link.invite", "patient_invitation", resource_id=inv.invitation_id,
                 patient_id=patient_id, status_code=201, permission="patient_links.invite")
    return InvitationOut(invitation_id=inv.invitation_id, patient_id=patient_id, code=raw, expires_at=inv.expires_at)


@router.get("/admin/patient-links", response_model=PaginatedPatientLinksOut)
def list_patient_links(
    status: Literal["active", "revoked"] | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    p: Principal = Depends(require("patient_links.manage")),
) -> PaginatedPatientLinksOut:
    with identity_session() as s:
        total, rows = directory.list_links(s, organization_id=_org(p), status=status, limit=limit, offset=offset)
        items = [_link_out(x) for x in rows]
    return PaginatedPatientLinksOut(total=total, limit=limit, offset=offset, items=items)


@router.post("/admin/patient-links/{link_id}/revoke", response_model=PatientLinkOut)
def revoke_patient_link(link_id: str, p: Principal = Depends(require("patient_links.manage"))) -> PatientLinkOut:
    with identity_session() as s:
        link = directory.revoke_link(s, organization_id=_org(p), link_id=link_id, actor=p.user_id)
        out = _link_out(link)
    record_event(p, "patient_link.revoke", "patient_link", resource_id=link_id, patient_id=out.patient_id,
                 status_code=200, permission="patient_links.manage")
    return out


# --- audit ---------------------------------------------------------------------------------


@router.get("/audit-events", response_model=PaginatedAuditEventsOut)
def get_audit_events(
    action: str | None = Query(default=None, max_length=64),
    resource_type: str | None = Query(default=None, max_length=40),
    actor_user_id: str | None = Query(default=None, max_length=36),
    patient_id: str | None = Query(default=None, max_length=64),
    outcome: Literal["success", "denied", "failed"] | None = Query(default=None),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    p: Principal = Depends(require("audit_logs.read")),
) -> PaginatedAuditEventsOut:
    """Audit events of the caller's organization, newest first (filters applied before paging)."""
    total, rows = list_events(organization_id=_org(p), action=action, resource_type=resource_type,
                              actor_user_id=actor_user_id, patient_id=patient_id, outcome=outcome,
                              since=since, until=until, limit=limit, offset=offset)
    return PaginatedAuditEventsOut(
        total=total, limit=limit, offset=offset,
        items=[AuditEventOut(**{c: getattr(r, c) for c in AuditEventOut.model_fields}) for r in rows],
    )
