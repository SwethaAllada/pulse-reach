"""Organizations, memberships, patient ownership, staff assignments and patient account links.

Tenant model (patient-anchored): every synthetic patient belongs to at most one organization
(`identity.patient_organization`). Clinical and workflow records (evaluations, care gaps,
appointments, referrals, follow-ups, AI subjects) are owned by a patient and therefore inherit the
patient's organization. Unowned patients are visible to nobody in `AUTH_MODE=users`.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import date, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.i18n import AppError
from app.core.permissions import ASSIGNABLE_ROLES, DEFAULT_PATIENT_ACCESS, STAFF_ROLES, Role
from app.models.identity import (
    Membership,
    Organization,
    PatientAssignment,
    PatientInvitation,
    PatientLink,
    PatientOrganization,
    UserAccount,
)
from app.services.identity.credentials import new_invitation_code, normalize_invitation_code, token_digest
from app.services.identity.service import (
    active_memberships,
    active_patient_link,
    new_id,
    now,
    revoke_user_sessions,
)

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")


# --- scope queries -----------------------------------------------------------------------


def organization_patient_ids(session: Session, organization_id: str) -> frozenset[str]:
    return frozenset(
        session.scalars(
            select(PatientOrganization.patient_id).where(
                PatientOrganization.organization_id == organization_id
            )
        )
    )


def assigned_patient_ids(session: Session, organization_id: str, user_id: str) -> frozenset[str]:
    return frozenset(
        session.scalars(
            select(PatientAssignment.patient_id)
            .join(
                PatientOrganization,
                (PatientOrganization.patient_id == PatientAssignment.patient_id)
                & (PatientOrganization.organization_id == PatientAssignment.organization_id),
            )
            .where(
                PatientAssignment.organization_id == organization_id,
                PatientAssignment.staff_user_id == user_id,
                PatientAssignment.is_active,
            )
        )
    )


def patient_organization_id(session: Session, patient_id: str) -> str | None:
    row = session.get(PatientOrganization, patient_id)
    return row.organization_id if row else None


# --- organizations -----------------------------------------------------------------------


def create_organization(session: Session, *, name: str, slug: str, created_by: str | None) -> Organization:
    slug = slug.strip().lower()
    if not _SLUG_RE.match(slug) or not name.strip():
        raise AppError(422, "error.validation", params={"reason": "slug"})
    if session.scalars(select(Organization).where(Organization.slug == slug)).first() is not None:
        raise AppError(409, "admin.slug_unavailable")
    org = Organization(organization_id=new_id(), name=name.strip(), slug=slug, is_active=True,
                       created_at=now(), created_by=created_by)
    session.add(org)
    session.flush()
    return org


def add_membership(
    session: Session,
    *,
    user_id: str,
    organization_id: str,
    role: str,
    patient_access: str | None = None,
    created_by: str | None,
) -> Membership:
    role = Role(role)
    existing = session.scalars(
        select(Membership).where(Membership.user_id == user_id, Membership.organization_id == organization_id)
    ).first()
    ts = now()
    access = patient_access or DEFAULT_PATIENT_ACCESS[role]
    if existing is not None:
        existing.role, existing.patient_access, existing.is_active, existing.updated_at = role, access, True, ts
        return existing
    m = Membership(membership_id=new_id(), user_id=user_id, organization_id=organization_id, role=role,
                   patient_access=access, is_active=True, created_at=ts, created_by=created_by, updated_at=ts)
    session.add(m)
    session.flush()
    return m


def membership_in(session: Session, user_id: str, organization_id: str) -> Membership | None:
    return session.scalars(
        select(Membership).where(Membership.user_id == user_id, Membership.organization_id == organization_id)
    ).first()


def list_members(
    session: Session, organization_id: str, *, role: str | None, limit: int, offset: int
) -> tuple[int, list[tuple[UserAccount, Membership]]]:
    stmt = (
        select(UserAccount, Membership)
        .join(Membership, Membership.user_id == UserAccount.user_id)
        .where(Membership.organization_id == organization_id)
    )
    if role is not None:
        stmt = stmt.where(Membership.role == role)
    total = int(session.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    rows = session.execute(stmt.order_by(UserAccount.email).limit(limit).offset(offset)).all()
    return total, [(u, m) for u, m in rows]


def update_member(
    session: Session,
    *,
    organization_id: str,
    user_id: str,
    actor_user_id: str,
    full_name: str | None = None,
    role: str | None = None,
    patient_access: str | None = None,
    membership_active: bool | None = None,
) -> tuple[UserAccount, Membership]:
    m = membership_in(session, user_id, organization_id)
    user = session.get(UserAccount, user_id)
    if m is None or user is None:
        raise AppError(404, "error.not_found")
    if user_id == actor_user_id and (role is not None or membership_active is not None):
        raise AppError(403, "admin.cannot_modify_self")
    ts = now()
    if role is not None:
        if Role(role) not in ASSIGNABLE_ROLES or m.role == Role.PATIENT:
            raise AppError(422, "admin.role_not_assignable")
        m.role = role
    if patient_access is not None:
        m.patient_access = patient_access
    if membership_active is not None:
        m.is_active = membership_active
        if not membership_active:
            revoke_user_sessions(session, user_id, "membership_deactivated", organization_id=organization_id)
    if full_name is not None and full_name.strip():
        user.full_name = full_name.strip()
        user.updated_at = ts
    m.updated_at = ts
    if role is not None or patient_access is not None:
        # Permissions are resolved per request, but end sessions so clients re-authenticate.
        revoke_user_sessions(session, user_id, "membership_changed", organization_id=organization_id)
    return user, m


def set_account_active(
    session: Session, *, organization_id: str, user_id: str, actor_user_id: str, active: bool
) -> tuple[UserAccount, str]:
    """Deactivate/reactivate. If the account also belongs to other organizations only this
    organization's membership changes (an org admin cannot disable access elsewhere).
    Returns (user, scope) with scope 'account' or 'membership'."""
    if user_id == actor_user_id:
        raise AppError(403, "admin.cannot_modify_self")
    m = membership_in(session, user_id, organization_id)
    user = session.get(UserAccount, user_id)
    if m is None or user is None:
        raise AppError(404, "error.not_found")
    others = [x for x in session.scalars(select(Membership).where(Membership.user_id == user_id))
              if x.organization_id != organization_id and x.is_active]
    ts = now()
    if others:
        m.is_active, m.updated_at = active, ts
        if not active:
            revoke_user_sessions(session, user_id, "membership_deactivated", organization_id=organization_id)
        return user, "membership"
    user.is_active, user.updated_at = active, ts
    m.is_active, m.updated_at = active, ts
    if not active:
        revoke_user_sessions(session, user_id, "account_deactivated")
    return user, "account"


# --- patient ownership -------------------------------------------------------------------


def associate_patients(
    session: Session, *, organization_id: str, patient_ids: Iterable[str], created_by: str | None
) -> tuple[int, int]:
    """Attach unowned patients to the organization. Patients owned by another organization are
    rejected (409) — ownership never moves across tenants through this call."""
    ids = sorted(set(patient_ids))
    existing = {
        p.patient_id: p.organization_id
        for p in session.scalars(select(PatientOrganization).where(PatientOrganization.patient_id.in_(ids)))
    } if ids else {}
    foreign = [pid for pid, org in existing.items() if org != organization_id]
    if foreign:
        raise AppError(409, "admin.patient_in_other_organization", params={"count": len(foreign)})
    ts = now()
    new = [pid for pid in ids if pid not in existing]
    session.add_all(
        PatientOrganization(patient_id=pid, organization_id=organization_id, created_at=ts, created_by=created_by)
        for pid in new
    )
    session.flush()
    return len(new), len(ids) - len(new)


def release_patients(session: Session, *, organization_id: str, patient_ids: Iterable[str], actor: str) -> int:
    ids = set(patient_ids)
    rows = list(session.scalars(select(PatientOrganization).where(
        PatientOrganization.organization_id == organization_id, PatientOrganization.patient_id.in_(ids))))
    if not rows:
        return 0
    released = [r.patient_id for r in rows]
    ts = now()
    session.execute(
        update(PatientAssignment)
        .where(PatientAssignment.organization_id == organization_id,
               PatientAssignment.patient_id.in_(released), PatientAssignment.is_active)
        .values(is_active=False, ended_at=ts, ended_by=actor)
    )
    for link in session.scalars(select(PatientLink).where(
            PatientLink.patient_id.in_(released), PatientLink.status == "active")):
        link.status, link.revoked_at, link.revoked_by = "revoked", ts, actor
        revoke_user_sessions(session, link.user_id, "patient_released")
    for r in rows:
        session.delete(r)
    return len(rows)


# --- assignments -------------------------------------------------------------------------


def create_assignment(
    session: Session, *, organization_id: str, staff_user_id: str, patient_id: str, created_by: str
) -> PatientAssignment:
    if patient_organization_id(session, patient_id) != organization_id:
        raise AppError(404, "error.not_found")
    m = membership_in(session, staff_user_id, organization_id)
    if m is None or not m.is_active or Role(m.role) not in STAFF_ROLES:
        raise AppError(422, "admin.staff_not_eligible")
    existing = session.scalars(select(PatientAssignment).where(
        PatientAssignment.staff_user_id == staff_user_id, PatientAssignment.patient_id == patient_id,
        PatientAssignment.is_active)).first()
    if existing is not None:
        return existing
    a = PatientAssignment(assignment_id=new_id(), organization_id=organization_id, staff_user_id=staff_user_id,
                          patient_id=patient_id, is_active=True, created_at=now(), created_by=created_by)
    session.add(a)
    session.flush()
    return a


def end_assignment(session: Session, *, organization_id: str, assignment_id: str, actor: str) -> PatientAssignment:
    a = session.get(PatientAssignment, assignment_id)
    if a is None or a.organization_id != organization_id:
        raise AppError(404, "error.not_found")
    if a.is_active:
        a.is_active, a.ended_at, a.ended_by = False, now(), actor
    return a


def list_assignments(
    session: Session, *, organization_id: str, staff_user_id: str | None, patient_id: str | None,
    active_only: bool, limit: int, offset: int,
) -> tuple[int, list[PatientAssignment]]:
    stmt = select(PatientAssignment).where(PatientAssignment.organization_id == organization_id)
    if staff_user_id:
        stmt = stmt.where(PatientAssignment.staff_user_id == staff_user_id)
    if patient_id:
        stmt = stmt.where(PatientAssignment.patient_id == patient_id)
    if active_only:
        stmt = stmt.where(PatientAssignment.is_active)
    total = int(session.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    rows = list(session.scalars(stmt.order_by(PatientAssignment.created_at.desc(),
                                              PatientAssignment.assignment_id).limit(limit).offset(offset)))
    return total, rows


def can_staff_access_patient(session: Session, user_id: str, organization_id: str, patient_id: str) -> bool:
    if patient_organization_id(session, patient_id) != organization_id:
        return False
    m = membership_in(session, user_id, organization_id)
    if m is None or not m.is_active or Role(m.role) not in STAFF_ROLES:
        return False
    return m.patient_access == "organization" or patient_id in assigned_patient_ids(session, organization_id, user_id)


# --- patient invitations and links ---------------------------------------------------------


def create_invitation(
    session: Session, *, organization_id: str, patient_id: str, created_by: str
) -> tuple[PatientInvitation, str]:
    if patient_organization_id(session, patient_id) != organization_id:
        raise AppError(404, "error.not_found")
    ts = now()
    # Only one outstanding invitation per patient.
    session.execute(
        update(PatientInvitation)
        .where(PatientInvitation.patient_id == patient_id, PatientInvitation.used_at.is_(None),
               PatientInvitation.revoked_at.is_(None))
        .values(revoked_at=ts)
    )
    raw, digest = new_invitation_code()
    inv = PatientInvitation(
        invitation_id=new_id(), organization_id=organization_id, patient_id=patient_id, code_hash=digest,
        created_at=ts, created_by=created_by,
        expires_at=ts + timedelta(seconds=settings.patient_invitation_ttl_seconds), failed_attempts=0,
    )
    session.add(inv)
    session.flush()
    return inv, raw


def redeem_invitation(
    session: Session, *, user_id: str, code: str, date_of_birth: date, patient_dob_lookup
) -> PatientLink:
    """Verify (one-time code + date of birth on the record) and link the account.

    `patient_dob_lookup(patient_id) -> date | None | False` reads the clinical record (False when the
    record does not exist). Failures are deliberately indistinguishable; each wrong date of birth
    counts against the invitation, which is revoked after `PATIENT_INVITATION_MAX_ATTEMPTS`.
    """
    invalid = AppError(400, "link.invitation_invalid")
    if active_patient_link(session, user_id) is not None:
        raise AppError(409, "link.already_linked")
    memberships = active_memberships(session, user_id)
    if any(m.role != Role.PATIENT for m in memberships):
        raise AppError(403, "link.staff_account")
    inv = session.scalars(
        select(PatientInvitation).where(PatientInvitation.code_hash == token_digest(normalize_invitation_code(code)))
    ).first()
    ts = now()
    if inv is None or inv.used_at is not None or inv.revoked_at is not None or inv.expires_at <= ts:
        raise invalid
    if patient_organization_id(session, inv.patient_id) != inv.organization_id:
        raise invalid
    dob = patient_dob_lookup(inv.patient_id)
    if dob is False or dob is None or dob != date_of_birth:
        inv.failed_attempts += 1
        if inv.failed_attempts >= settings.patient_invitation_max_attempts:
            inv.revoked_at = ts
        session.commit()
        raise invalid
    if session.scalars(select(PatientLink).where(
            PatientLink.patient_id == inv.patient_id, PatientLink.status == "active")).first() is not None:
        raise invalid
    if any(m.organization_id != inv.organization_id for m in memberships):
        raise AppError(403, "link.staff_account")
    add_membership(session, user_id=user_id, organization_id=inv.organization_id, role=Role.PATIENT,
                   created_by=inv.created_by)
    inv.used_at, inv.used_by = ts, user_id
    link = PatientLink(link_id=new_id(), user_id=user_id, patient_id=inv.patient_id,
                       organization_id=inv.organization_id, status="active",
                       verification_method="staff_invitation_code+date_of_birth",
                       invitation_id=inv.invitation_id, verified_at=ts)
    session.add(link)
    session.flush()
    return link


def list_links(
    session: Session, *, organization_id: str, status: str | None, limit: int, offset: int
) -> tuple[int, list[PatientLink]]:
    stmt = select(PatientLink).where(PatientLink.organization_id == organization_id)
    if status:
        stmt = stmt.where(PatientLink.status == status)
    total = int(session.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    return total, list(session.scalars(stmt.order_by(PatientLink.verified_at.desc()).limit(limit).offset(offset)))


def revoke_link(session: Session, *, organization_id: str, link_id: str, actor: str) -> PatientLink:
    link = session.get(PatientLink, link_id)
    if link is None or link.organization_id != organization_id:
        raise AppError(404, "error.not_found")
    if link.status == "active":
        link.status, link.revoked_at, link.revoked_by = "revoked", now(), actor
        revoke_user_sessions(session, link.user_id, "patient_link_revoked")
    return link
