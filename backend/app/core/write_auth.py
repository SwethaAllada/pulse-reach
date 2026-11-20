"""Shared-key protection for state-changing `/api/v1` requests (hackathon deployment).

Every non-GET request needs `X-PulseReach-Write-Key` equal to `WRITE_API_KEY`, except the
read-oriented POSTs in `READ_ONLY_POSTS`, which store no workflow state. Fails closed: without a
configured key, writes are refused (503) unless `ALLOW_UNPROTECTED_WRITES=true` is set explicitly
(local development and tests only). This is a shared demo access code, not user identity.
"""

from __future__ import annotations

import hmac

from fastapi import HTTPException, Request

from app.core.config import settings

WRITE_KEY_HEADER = "X-PulseReach-Write-Key"

# Read-oriented POSTs (request bodies only for convenience): `/evaluations` and
# `/outreach/preview` store nothing; `/explanations` changes no workflow state (it appends one
# AI-audit record, and calls the LLM only when `LLM_ENABLED=true`).
READ_ONLY_POSTS = frozenset(
    {"/api/v1/evaluations", "/api/v1/outreach/preview", "/api/v1/explanations"}
)
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def write_protection_status() -> str:
    """'enforced' | 'unprotected' (explicitly allowed) | 'writes_disabled' (no key: fail closed)."""
    if settings.write_api_key is not None and settings.write_api_key.get_secret_value():
        return "enforced"
    return "unprotected" if settings.allow_unprotected_writes else "writes_disabled"


def require_write_key(request: Request) -> None:
    if request.method in _SAFE_METHODS:
        return
    route = request.scope.get("route")
    if getattr(route, "path", None) in READ_ONLY_POSTS:
        return
    status = write_protection_status()
    if status == "unprotected":
        return
    if status == "writes_disabled":
        raise HTTPException(
            status_code=503,
            detail="Write protection is not configured (WRITE_API_KEY); writes are disabled.",
        )
    supplied = request.headers.get(WRITE_KEY_HEADER, "")
    expected = settings.write_api_key.get_secret_value()  # type: ignore[union-attr]
    if not hmac.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8")):
        raise HTTPException(
            status_code=401,
            detail=f"Missing or invalid {WRITE_KEY_HEADER} header.",
            headers={"WWW-Authenticate": "PulseReach-Write-Key"},
        )
