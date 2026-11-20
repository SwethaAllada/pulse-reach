"""Authentication and profile endpoints (`/api/v1/auth/*`, `/api/v1/me*`).

Available in `AUTH_MODE=users` only (404 in legacy mode, which has no user accounts).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app.core.auth import Principal, authenticated, public_endpoint
from app.core.config import settings
from app.core.i18n import AppError, direction, resolve_locale, t
from app.core.permissions import permissions_for
from app.core.rate_limit import raise_if_limited
from app.models.identity import Organization, UserAccount
from app.schemas.identity import (
    LoginIn,
    MembershipOut,
    MeOut,
    MessageOut,
    MeUpdateIn,
    PasswordChangeIn,
    PasswordResetConfirmIn,
    PasswordResetRequestIn,
    PreferencesIn,
    PreferencesOut,
    RefreshIn,
    RegisterIn,
    SwitchOrganizationIn,
    TokenOut,
    UserOut,
)
from app.services.identity import service as auth
from app.services.identity.audit import record_event
from app.services.identity.store import identity_session


def _users_mode_only() -> None:
    if settings.auth_mode != "users":
        raise HTTPException(status_code=404, detail="Not Found")


router = APIRouter(prefix="/api/v1", tags=["auth"], dependencies=[Depends(_users_mode_only)])


def _user_out(u: UserAccount) -> UserOut:
    return UserOut(user_id=u.user_id, email=u.email, full_name=u.full_name,
                   preferred_language=u.preferred_language, is_active=u.is_active,
                   created_at=u.created_at, last_login_at=u.last_login_at)


def _message(request: Request, key: str, user_locale: str | None = None) -> MessageOut:
    loc = resolve_locale(request, user_locale)
    return MessageOut(message=t(key, loc), message_key=key, locale=loc, direction=direction(loc))


def _token_out(pair: auth.TokenPair, user: UserAccount, patient_access: str | None) -> TokenOut:
    perms = permissions_for(pair.role, patient_access or "assigned") if pair.role else frozenset()
    return TokenOut(access_token=pair.access_token, expires_in=pair.expires_in,
                    refresh_token=pair.refresh_token, refresh_expires_in=pair.refresh_expires_in,
                    user=_user_out(user), organization_id=pair.organization_id, role=pair.role,
                    permissions=sorted(perms))


def _issue(session, pair: auth.TokenPair) -> TokenOut:
    user = session.get(UserAccount, pair.user_id)
    m = next((m for m in auth.active_memberships(session, pair.user_id)
              if m.organization_id == pair.organization_id), None)
    return _token_out(pair, user, m.patient_access if m else None)


@router.post("/auth/login", response_model=TokenOut, dependencies=[Depends(public_endpoint)])
def login(req: LoginIn, request: Request) -> TokenOut:
    email = req.email.strip().lower()
    raise_if_limited(request, "login", email)
    try:
        with identity_session() as s:
            pair = auth.login(s, email, req.password, req.organization_id)
            out = _issue(s, pair)
    except AppError as exc:
        record_event(None, "auth.login", "session", outcome="denied" if exc.status_code < 500 else "failed",
                     status_code=exc.status_code, actor_user_id=getattr(exc, "audit_user_id", None),
                     organization_id=getattr(exc, "audit_org_id", None), details={"reason": exc.message_key})
        raise
    record_event(None, "auth.login", "session", resource_id=pair.session_id, actor_user_id=pair.user_id,
                 organization_id=pair.organization_id, status_code=200, details={"role": pair.role})
    return out


@router.post("/auth/refresh", response_model=TokenOut, dependencies=[Depends(public_endpoint)])
def refresh_tokens(req: RefreshIn, request: Request) -> TokenOut:
    raise_if_limited(request, "refresh")
    try:
        with identity_session() as s:
            pair = auth.refresh(s, req.refresh_token)
            out = _issue(s, pair)
    except AppError as exc:
        action = getattr(exc, "audit_action", None)
        if action:
            record_event(None, action, "session", outcome="denied", status_code=401,
                         actor_user_id=getattr(exc, "audit_user_id", None),
                         organization_id=getattr(exc, "audit_org_id", None))
        raise
    record_event(None, "auth.refresh", "session", resource_id=pair.session_id, actor_user_id=pair.user_id,
                 organization_id=pair.organization_id, status_code=200)
    return out


@router.post("/auth/switch-organization", response_model=TokenOut, dependencies=[Depends(authenticated)])
def switch_organization(req: SwitchOrganizationIn, p: Principal = Depends(authenticated)) -> TokenOut:
    with identity_session() as s:
        user = s.get(UserAccount, p.user_id)
        pair = auth.start_session(s, user, req.organization_id)
        auth.revoke_session(s, p.session_id, "organization_switched")
        out = _issue(s, pair)
    record_event(p, "auth.switch_organization", "session", resource_id=pair.session_id,
                 organization_id=pair.organization_id, status_code=200)
    return out


@router.post("/auth/logout", status_code=204, dependencies=[Depends(authenticated)])
def logout(p: Principal = Depends(authenticated)) -> Response:
    with identity_session() as s:
        auth.revoke_session(s, p.session_id, "logout")
    record_event(p, "auth.logout", "session", resource_id=p.session_id, status_code=204)
    return Response(status_code=204)


@router.post("/auth/logout-all", status_code=204, dependencies=[Depends(authenticated)])
def logout_all(p: Principal = Depends(authenticated)) -> Response:
    with identity_session() as s:
        auth.revoke_user_sessions(s, p.user_id, "logout_all")
    record_event(p, "auth.logout_all", "user", resource_id=p.user_id, status_code=204)
    return Response(status_code=204)


@router.post("/auth/register", response_model=MessageOut, status_code=202,
             dependencies=[Depends(public_endpoint)])
def register(req: RegisterIn, request: Request) -> MessageOut:
    """Patient self-registration. The account has no organization or patient record until it
    redeems a staff-issued invitation (`POST /api/v1/portal/link`). Same answer whether or not
    the address was already registered."""
    if not settings.self_registration_enabled:
        raise AppError(403, "auth.registration_disabled")
    raise_if_limited(request, "register", req.email.strip().lower())
    with identity_session() as s:
        user = auth.register_self(s, email=req.email, password=req.password, full_name=req.full_name,
                                  preferred_language=req.preferred_language or resolve_locale(request))
        user_id = user.user_id if user else None
    record_event(None, "auth.register", "user", resource_id=user_id, actor_user_id=user_id,
                 outcome="success" if user_id else "denied", status_code=202,
                 details={} if user_id else {"reason": "email_unavailable"})
    return _message(request, "auth.registration_accepted", req.preferred_language)


@router.post("/auth/password/change", status_code=204, dependencies=[Depends(authenticated)])
def change_password(req: PasswordChangeIn, request: Request, p: Principal = Depends(authenticated)) -> Response:
    raise_if_limited(request, "password_change", p.user_id or "")
    try:
        with identity_session() as s:
            auth.change_password(s, p.user_id, req.current_password, req.new_password, p.session_id)
    except AppError as exc:
        record_event(p, "auth.password_change", "user", resource_id=p.user_id, outcome="denied",
                     status_code=exc.status_code, details={"reason": exc.message_key})
        raise
    record_event(p, "auth.password_change", "user", resource_id=p.user_id, status_code=204)
    return Response(status_code=204)


@router.post("/auth/password-reset/request", response_model=MessageOut, status_code=202,
             dependencies=[Depends(public_endpoint)])
def request_password_reset(req: PasswordResetRequestIn, request: Request) -> MessageOut:
    """Always 202. PulseReach has no e-mail integration: the request is audited and an organization
    administrator issues the single-use reset code (`POST /api/v1/admin/users/{id}/password-reset`)."""
    email = req.email.strip().lower()
    raise_if_limited(request, "password_reset", email)
    with identity_session() as s:
        user = auth.get_user_by_email(s, email)
        user_id = user.user_id if user and user.is_active else None
    record_event(None, "auth.password_reset_requested", "user", resource_id=user_id, actor_user_id=user_id,
                 outcome="success" if user_id else "denied", status_code=202)
    return _message(request, "auth.password_reset_requested")


@router.post("/auth/password-reset/confirm", status_code=204, dependencies=[Depends(public_endpoint)])
def confirm_password_reset(req: PasswordResetConfirmIn, request: Request) -> Response:
    """Redeem a password-reset or account-activation code; every session of the user is revoked."""
    raise_if_limited(request, "password_reset_confirm")
    try:
        with identity_session() as s:
            user_id = auth.redeem_one_time_token(s, req.token, req.new_password)
    except AppError as exc:
        record_event(None, "auth.password_reset", "user", outcome="denied", status_code=exc.status_code,
                     details={"reason": exc.message_key})
        raise
    record_event(None, "auth.password_reset", "user", resource_id=user_id, actor_user_id=user_id, status_code=204)
    return Response(status_code=204)


def _me(request: Request, p: Principal) -> MeOut:
    with identity_session() as s:
        user = s.get(UserAccount, p.user_id)
        memberships = []
        for m in auth.active_memberships(s, p.user_id):
            org = s.get(Organization, m.organization_id)
            memberships.append(MembershipOut(organization_id=m.organization_id, organization_name=org.name,
                                             role=m.role, patient_access=m.patient_access, is_active=m.is_active))
    loc = resolve_locale(request, user.preferred_language)
    return MeOut(user=_user_out(user), organization_id=p.organization_id, role=p.role,
                 permissions=sorted(p.permissions), patient_linked=p.patient_id is not None,
                 memberships=memberships, locale=loc, direction=direction(loc))


@router.get("/me", response_model=MeOut, dependencies=[Depends(authenticated)])
def get_me(request: Request, p: Principal = Depends(authenticated)) -> MeOut:
    return _me(request, p)


@router.patch("/me", response_model=MeOut, dependencies=[Depends(authenticated)])
def update_me(req: MeUpdateIn, request: Request, p: Principal = Depends(authenticated)) -> MeOut:
    changed = req.model_dump(exclude_none=True)
    with identity_session() as s:
        user = s.get(UserAccount, p.user_id)
        for k, v in changed.items():
            setattr(user, k, v)
        user.updated_at = auth.now()
    request.state.user_locale = changed.get("preferred_language", p.preferred_language)
    record_event(p, "user.profile_update", "user", resource_id=p.user_id, status_code=200,
                 details={"fields": sorted(changed)})
    return _me(request, p)


@router.get("/me/preferences", response_model=PreferencesOut, dependencies=[Depends(authenticated)])
def get_preferences(request: Request, p: Principal = Depends(authenticated)) -> PreferencesOut:
    loc = resolve_locale(request, p.preferred_language)
    return PreferencesOut(preferred_language=p.preferred_language, locale=loc, direction=direction(loc),
                          default_locale=settings.default_locale)


@router.patch("/me/preferences", response_model=PreferencesOut, dependencies=[Depends(authenticated)])
def update_preferences(req: PreferencesIn, request: Request, p: Principal = Depends(authenticated)) -> PreferencesOut:
    with identity_session() as s:
        user = s.get(UserAccount, p.user_id)
        user.preferred_language = req.preferred_language
        user.updated_at = auth.now()
    request.state.user_locale = req.preferred_language
    record_event(p, "user.language_update", "user", resource_id=p.user_id, status_code=200,
                 details={"preferred_language": req.preferred_language})
    loc = resolve_locale(request, req.preferred_language)
    return PreferencesOut(preferred_language=req.preferred_language, locale=loc, direction=direction(loc),
                          default_locale=settings.default_locale)
