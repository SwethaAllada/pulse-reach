"""Authentication: accounts, server-side sessions, opaque access/refresh tokens, password reset.

All functions take an open identity `Session` (see `store.identity_session`). Where state must
persist even though the request fails (failed-login counters, refresh-token reuse revocation),
the function commits before raising.

Token lifecycle:
- login creates an `auth_session` (absolute lifetime `SESSION_MAX_AGE_SECONDS`) and one access
  token (`ACCESS_TOKEN_TTL_SECONDS`) + one refresh token (`REFRESH_TOKEN_TTL_SECONDS`);
- refresh marks the presented refresh token used, revokes the session's outstanding access
  tokens and issues a new pair in the same session (rotation);
- presenting an already-used refresh token is treated as theft: the whole session is revoked;
- logout revokes the session; password change/reset and deactivation revoke every session.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.i18n import AppError, normalize_locale
from app.core.permissions import Role
from app.models.identity import (
    AuthSession,
    AuthToken,
    Membership,
    OneTimeToken,
    Organization,
    PatientLink,
    UserAccount,
)
from app.services.identity.credentials import (
    hash_password,
    needs_rehash,
    new_token,
    token_digest,
    verify_password,
)

_EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s.]{2,}$")


def now() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid.uuid4())


def normalize_email(email: str) -> str:
    value = (email or "").strip().lower()
    if not _EMAIL_RE.match(value):
        raise AppError(422, "auth.email_invalid")
    return value


def validate_password(password: str, email: str | None = None) -> None:
    if len(password) < settings.password_min_length:
        raise AppError(422, "auth.password_too_short", params={"min_length": settings.password_min_length})
    if len(password.encode("utf-8")) > 1024:
        raise AppError(422, "auth.password_too_long")
    local = (email or "").split("@")[0].lower()
    if len(set(password)) < 5 or (len(local) >= 3 and local in password.lower()):
        raise AppError(422, "auth.password_weak")


@dataclass(frozen=True)
class TokenPair:
    access_token: str
    refresh_token: str
    expires_in: int
    refresh_expires_in: int
    session_id: str
    user_id: str
    organization_id: str | None
    role: str | None


@dataclass(frozen=True)
class ResolvedAccess:
    user: UserAccount
    auth_session: AuthSession
    membership: Membership | None
    patient_link: PatientLink | None


def get_user_by_email(session: Session, email: str) -> UserAccount | None:
    return session.scalars(select(UserAccount).where(UserAccount.email == email.strip().lower())).first()


def active_memberships(session: Session, user_id: str) -> list[Membership]:
    return list(
        session.scalars(
            select(Membership)
            .join(Organization, Organization.organization_id == Membership.organization_id)
            .where(Membership.user_id == user_id, Membership.is_active, Organization.is_active)
            .order_by(Membership.created_at, Membership.membership_id)
        )
    )


def active_patient_link(session: Session, user_id: str) -> PatientLink | None:
    return session.scalars(
        select(PatientLink).where(PatientLink.user_id == user_id, PatientLink.status == "active")
    ).first()


def _issue_pair(session: Session, auth: AuthSession, user: UserAccount, role: str | None) -> TokenPair:
    ts = now()
    access_exp = min(ts + timedelta(seconds=settings.access_token_ttl_seconds), auth.expires_at)
    refresh_exp = min(ts + timedelta(seconds=settings.refresh_token_ttl_seconds), auth.expires_at)
    access_raw, access_hash = new_token("pra")
    refresh_raw, refresh_hash = new_token("prr")
    session.add_all(
        [
            AuthToken(token_hash=access_hash, session_id=auth.session_id, kind="access",
                      issued_at=ts, expires_at=access_exp),
            AuthToken(token_hash=refresh_hash, session_id=auth.session_id, kind="refresh",
                      issued_at=ts, expires_at=refresh_exp),
        ]
    )
    session.flush()
    return TokenPair(
        access_token=access_raw,
        refresh_token=refresh_raw,
        expires_in=int((access_exp - ts).total_seconds()),
        refresh_expires_in=int((refresh_exp - ts).total_seconds()),
        session_id=auth.session_id,
        user_id=user.user_id,
        organization_id=auth.organization_id,
        role=role,
    )


def start_session(session: Session, user: UserAccount, organization_id: str | None) -> TokenPair:
    memberships = active_memberships(session, user.user_id)
    if organization_id is not None:
        chosen = next((m for m in memberships if m.organization_id == organization_id), None)
        if chosen is None:
            raise AppError(403, "auth.organization_not_member")
    else:
        chosen = memberships[0] if memberships else None
    ts = now()
    auth = AuthSession(
        session_id=new_id(),
        user_id=user.user_id,
        organization_id=chosen.organization_id if chosen else None,
        created_at=ts,
        expires_at=ts + timedelta(seconds=settings.session_max_age_seconds),
    )
    session.add(auth)
    session.flush()
    return _issue_pair(session, auth, user, chosen.role if chosen else None)


def login(session: Session, email: str, password: str, organization_id: str | None = None) -> TokenPair:
    """Raises 401 `auth.invalid_credentials` for unknown, wrong-password and disabled accounts
    alike, and 429 `auth.account_locked` while a lockout is active."""
    user = get_user_by_email(session, email)
    ts = now()
    if user is not None and user.locked_until is not None and user.locked_until > ts:
        raise AppError(429, "auth.account_locked")
    ok = verify_password(password, user.password_hash if user else None)
    if user is None or not ok or not user.is_active:
        if user is not None and not ok:
            user.failed_login_count += 1
            if user.failed_login_count >= settings.login_max_failures:
                user.locked_until = ts + timedelta(seconds=settings.login_lockout_seconds)
                user.failed_login_count = 0
            user.updated_at = ts
            session.commit()
        err = AppError(401, "auth.invalid_credentials")
        err.audit_user_id = user.user_id if user else None  # type: ignore[attr-defined]
        memberships = active_memberships(session, user.user_id) if user else []
        err.audit_org_id = memberships[0].organization_id if memberships else None  # type: ignore[attr-defined]
        raise err
    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = ts
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    user.updated_at = ts
    return start_session(session, user, organization_id)


def resolve_access_token(session: Session, raw: str) -> ResolvedAccess | None:
    tok = session.get(AuthToken, token_digest(raw))
    ts = now()
    if tok is None or tok.kind != "access" or tok.revoked_at is not None or tok.expires_at <= ts:
        return None
    auth = session.get(AuthSession, tok.session_id)
    if auth is None or auth.revoked_at is not None or auth.expires_at <= ts:
        return None
    user = session.get(UserAccount, auth.user_id)
    if user is None or not user.is_active:
        return None
    membership = None
    if auth.organization_id is not None:
        membership = next(
            (m for m in active_memberships(session, user.user_id) if m.organization_id == auth.organization_id),
            None,
        )
        if membership is None:  # membership or organization deactivated since login
            return None
    link = None
    if membership is not None and membership.role == Role.PATIENT:
        link = active_patient_link(session, user.user_id)
        if link is not None and link.organization_id != membership.organization_id:
            link = None
    return ResolvedAccess(user=user, auth_session=auth, membership=membership, patient_link=link)


def revoke_session(session: Session, session_id: str, reason: str) -> None:
    ts = now()
    session.execute(
        update(AuthSession)
        .where(AuthSession.session_id == session_id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=ts, revoke_reason=reason)
    )
    session.execute(
        update(AuthToken)
        .where(AuthToken.session_id == session_id, AuthToken.revoked_at.is_(None))
        .values(revoked_at=ts)
    )


def revoke_user_sessions(
    session: Session, user_id: str, reason: str, *, keep_session_id: str | None = None,
    organization_id: str | None = None,
) -> None:
    stmt = select(AuthSession.session_id).where(
        AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None)
    )
    if keep_session_id is not None:
        stmt = stmt.where(AuthSession.session_id != keep_session_id)
    if organization_id is not None:
        stmt = stmt.where(AuthSession.organization_id == organization_id)
    for sid in list(session.scalars(stmt)):
        revoke_session(session, sid, reason)


def refresh(session: Session, raw: str) -> TokenPair:
    tok = session.get(AuthToken, token_digest(raw or ""))
    ts = now()
    invalid = AppError(401, "auth.refresh_invalid")
    if tok is None or tok.kind != "refresh":
        raise invalid
    auth = session.get(AuthSession, tok.session_id)
    if tok.used_at is not None:
        # Replay of a rotated refresh token: assume it leaked and end the whole session.
        revoke_session(session, tok.session_id, "refresh_token_reuse")
        session.commit()
        invalid.audit_user_id = auth.user_id if auth else None  # type: ignore[attr-defined]
        invalid.audit_org_id = auth.organization_id if auth else None  # type: ignore[attr-defined]
        invalid.audit_action = "auth.refresh_reuse_detected"  # type: ignore[attr-defined]
        raise invalid
    if tok.revoked_at is not None or tok.expires_at <= ts or auth is None:
        raise invalid
    if auth.revoked_at is not None or auth.expires_at <= ts:
        raise invalid
    user = session.get(UserAccount, auth.user_id)
    if user is None or not user.is_active:
        raise invalid
    role = None
    if auth.organization_id is not None:
        m = next(
            (m for m in active_memberships(session, user.user_id) if m.organization_id == auth.organization_id),
            None,
        )
        if m is None:
            raise invalid
        role = m.role
    tok.used_at = ts
    session.execute(
        update(AuthToken)
        .where(AuthToken.session_id == auth.session_id, AuthToken.kind == "access",
               AuthToken.revoked_at.is_(None))
        .values(revoked_at=ts)
    )
    return _issue_pair(session, auth, user, role)


def create_user(
    session: Session,
    *,
    email: str,
    full_name: str,
    password: str | None,
    preferred_language: str = "en",
) -> UserAccount:
    email = normalize_email(email)
    if password is not None:
        validate_password(password, email)
    if get_user_by_email(session, email) is not None:
        raise AppError(409, "admin.email_unavailable")
    ts = now()
    user = UserAccount(
        user_id=new_id(),
        email=email,
        password_hash=hash_password(password) if password is not None else None,
        full_name=full_name.strip() or email,
        preferred_language=normalize_locale(preferred_language) or settings.default_locale,
        is_active=True,
        failed_login_count=0,
        password_changed_at=ts if password is not None else None,
        created_at=ts,
        updated_at=ts,
    )
    session.add(user)
    session.flush()
    return user


def register_self(
    session: Session, *, email: str, password: str, full_name: str, preferred_language: str | None
) -> UserAccount | None:
    """Self-registration (patients). Returns None when the address is already registered; the
    API answers identically in both cases so registration cannot enumerate accounts."""
    email = normalize_email(email)
    validate_password(password, email)
    if get_user_by_email(session, email) is not None:
        return None
    return create_user(
        session, email=email, full_name=full_name, password=password,
        preferred_language=preferred_language or settings.default_locale,
    )


def set_password(session: Session, user: UserAccount, new_password: str) -> None:
    validate_password(new_password, user.email)
    ts = now()
    user.password_hash = hash_password(new_password)
    user.password_changed_at = ts
    user.failed_login_count = 0
    user.locked_until = None
    user.updated_at = ts


def change_password(
    session: Session, user_id: str, current: str, new_password: str, keep_session_id: str
) -> None:
    user = session.get(UserAccount, user_id)
    if user is None or not verify_password(current, user.password_hash):
        raise AppError(400, "auth.current_password_invalid")
    set_password(session, user, new_password)
    revoke_user_sessions(session, user_id, "password_changed", keep_session_id=keep_session_id)


def issue_one_time_token(session: Session, user_id: str, purpose: str, created_by: str | None) -> tuple[str, datetime]:
    ttl = (
        settings.account_activation_ttl_seconds if purpose == "activation" else settings.password_reset_ttl_seconds
    )
    ts = now()
    # A new code invalidates earlier unused codes of the same purpose.
    session.execute(
        update(OneTimeToken)
        .where(OneTimeToken.user_id == user_id, OneTimeToken.purpose == purpose, OneTimeToken.used_at.is_(None))
        .values(used_at=ts)
    )
    raw, digest = new_token("prt")
    expires = ts + timedelta(seconds=ttl)
    session.add(OneTimeToken(token_hash=digest, user_id=user_id, purpose=purpose, created_at=ts,
                             created_by=created_by, expires_at=expires))
    session.flush()
    return raw, expires


def redeem_one_time_token(session: Session, raw: str, new_password: str) -> str:
    tok = session.get(OneTimeToken, token_digest(raw or ""))
    ts = now()
    if tok is None or tok.used_at is not None or tok.expires_at <= ts:
        raise AppError(400, "auth.one_time_token_invalid")
    user = session.get(UserAccount, tok.user_id)
    if user is None or not user.is_active:
        raise AppError(400, "auth.one_time_token_invalid")
    set_password(session, user, new_password)
    tok.used_at = ts
    revoke_user_sessions(session, user.user_id, f"{tok.purpose}_completed")
    return user.user_id
