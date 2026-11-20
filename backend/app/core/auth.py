"""Authentication and authorization dependencies for FastAPI routes.

- `get_principal`: validates `Authorization: Bearer <access token>` against the server-side
  session (401 when missing/invalid/expired/revoked, or when the user, membership or organization
  is no longer active). In `AUTH_MODE=legacy` it returns an unrestricted legacy principal.
- `require(*permissions)`: 403 unless the principal holds the permissions (denials are audited).
- `Principal.patient_scope()`: the patient ids the caller may see — organization patients
  (`patients.read`), assigned patients (`patients.read_assigned`) or the linked record (patients).
- `ensure_patient_access`: 404 (same message as a missing record) when a patient-owned resource is
  outside the caller's scope, so ids of other organizations' patients are never confirmed.
- `with_actor`: replaces client-supplied attribution (`recorded_by`, `reviewed_by`, `reviewer`)
  with the authenticated user id.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

from fastapi import Depends, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from app.core.config import settings
from app.core.i18n import AppError
from app.core.permissions import ALL_PERMISSIONS
from app.core.write_auth import require_write_key

_bearer = HTTPBearer(auto_error=False, description="Opaque PulseReach access token")
_WWW_AUTH = {"WWW-Authenticate": "Bearer"}
_UNSET: Any = object()
LEGACY_ACTOR = "legacy-shared-key"


@dataclass
class Principal:
    user_id: str | None
    email: str | None
    full_name: str | None
    organization_id: str | None
    role: str | None
    permissions: frozenset[str]
    session_id: str | None
    preferred_language: str
    patient_id: str | None = None
    patient_access: str | None = None
    legacy: bool = False
    _scope: Any = field(default=_UNSET, repr=False)

    @property
    def actor_ref(self) -> str:
        return self.user_id or LEGACY_ACTOR

    def has(self, permission: str) -> bool:
        return permission in self.permissions

    def patient_scope(self) -> frozenset[str] | None:
        """None = unrestricted (legacy mode only); otherwise the allowed patient ids."""
        if self.legacy:
            return None
        if self._scope is _UNSET:
            self._scope = self._compute_scope()
        return self._scope

    def _compute_scope(self) -> frozenset[str]:
        from app.services.identity import directory
        from app.services.identity.store import identity_session

        if self.organization_id is None:
            return frozenset()
        if self.has("patients.read") or self.has("patients.read_assigned"):
            with identity_session() as s:
                if self.has("patients.read"):
                    return directory.organization_patient_ids(s, self.organization_id)
                return directory.assigned_patient_ids(s, self.organization_id, self.user_id or "")
        if self.has("patients.read_self") and self.patient_id:
            return frozenset({self.patient_id})
        return frozenset()

    def can_access_patient(self, patient_id: str | None) -> bool:
        scope = self.patient_scope()
        return scope is None or (patient_id is not None and patient_id in scope)

    def audit_actor(self) -> dict[str, Any]:
        return {"actor_user_id": self.user_id, "actor_role": self.role, "organization_id": self.organization_id}


def _legacy_principal() -> Principal:
    return Principal(
        user_id=None, email=None, full_name=None, organization_id=None, role=None,
        permissions=ALL_PERMISSIONS, session_id=None, preferred_language=settings.default_locale,
        legacy=True,
    )


def get_principal(
    request: Request, creds: HTTPAuthorizationCredentials | None = Depends(_bearer)
) -> Principal:
    if settings.auth_mode == "legacy":
        p = _legacy_principal()
        request.state.principal = p
        return p
    if creds is None or creds.scheme.lower() != "bearer" or not creds.credentials:
        raise AppError(401, "auth.not_authenticated", headers=_WWW_AUTH)

    from app.core.permissions import permissions_for
    from app.services.identity.service import resolve_access_token
    from app.services.identity.store import identity_session

    with identity_session() as s:
        resolved = resolve_access_token(s, creds.credentials)
        if resolved is None:
            raise AppError(401, "auth.token_invalid", headers=_WWW_AUTH)
        m, u = resolved.membership, resolved.user
        p = Principal(
            user_id=u.user_id,
            email=u.email,
            full_name=u.full_name,
            organization_id=m.organization_id if m else None,
            role=m.role if m else None,
            permissions=permissions_for(m.role, m.patient_access) if m else frozenset(),
            session_id=resolved.auth_session.session_id,
            preferred_language=u.preferred_language,
            patient_id=resolved.patient_link.patient_id if resolved.patient_link else None,
            patient_access=m.patient_access if m else None,
        )
    request.state.principal = p
    request.state.user_locale = p.preferred_language
    return p


def require(*permissions: str, any_of: bool = False) -> Callable[..., Principal]:
    """Dependency factory: the principal must hold all (or, with `any_of`, one of) `permissions`."""
    unknown = set(permissions) - ALL_PERMISSIONS
    if unknown:
        raise ValueError(f"unknown permissions: {sorted(unknown)}")

    def dependency(request: Request, p: Principal = Depends(get_principal)) -> Principal:
        held = [x for x in permissions if p.has(x)]
        if (held if any_of else len(held) == len(permissions)):
            return p
        from app.services.identity.audit import record_event

        route = request.scope.get("route")
        record_event(
            p, "authz.denied", "endpoint",
            resource_id=f"{request.method} {getattr(route, 'path', request.url.path)}",
            outcome="denied", status_code=403, permission=",".join(permissions),
        )
        raise AppError(403, "error.forbidden")

    dependency.__pulsereach_permissions__ = permissions  # type: ignore[attr-defined]
    return dependency


def authenticated(p: Principal = Depends(get_principal)) -> Principal:
    """Any authenticated user (profile and self-service endpoints)."""
    return p


authenticated.__pulsereach_permissions__ = ("authenticated",)  # type: ignore[attr-defined]


def public_endpoint() -> None:
    """Marks an intentionally unauthenticated route (login, registration, token refresh)."""


public_endpoint.__pulsereach_permissions__ = ("public",)  # type: ignore[attr-defined]


def legacy_write_guard(request: Request) -> None:
    """The shared write key applies only in `AUTH_MODE=legacy`."""
    if settings.auth_mode == "legacy":
        require_write_key(request)


def ensure_patient_access(
    p: Principal, patient_id: str | None, not_found_detail: str, *, resource_type: str = "patient",
    resource_id: str | None = None,
) -> None:
    if p.can_access_patient(patient_id):
        return
    from app.services.identity.audit import record_event

    record_event(
        p, "authz.scope_denied", resource_type, resource_id=resource_id or patient_id,
        patient_id=patient_id, outcome="denied", status_code=404,
    )
    raise HTTPException(status_code=404, detail=not_found_detail)


M = TypeVar("M", bound=BaseModel)


def with_actor(p: Principal, req: M, field_name: str = "recorded_by") -> M:
    """Legacy: the client value is required (previous contract). Users: server-derived."""
    if p.legacy:
        if getattr(req, field_name) is None:
            raise RequestValidationError(
                [{"type": "missing", "loc": ("body", field_name), "msg": "Field required", "input": None}]
            )
        return req
    return req.model_copy(update={field_name: p.actor_ref})
