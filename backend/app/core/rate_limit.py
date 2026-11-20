"""In-process sliding-window rate limiter for authentication endpoints.

Per worker process: behind several instances the effective limit is multiplied by the instance
count, so persistent per-account lockout (`identity.user_account.locked_until`) is the
authoritative brute-force control and this limiter is a first line of defence. Use the platform
(Cloud Armor / API gateway) for distributed limits. Behind Cloud Run set `TRUSTED_PROXY_HOPS=1`
so the per-IP key is the address Cloud Run appended, not the shared front-end peer.
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque

from fastapi import Request

from app.core.config import settings

_WINDOW_SECONDS = 60.0
_lock = threading.Lock()
_hits: dict[str, deque[float]] = {}


def reset_rate_limits() -> None:
    with _lock:
        _hits.clear()


def client_ip(request: Request) -> str:
    peer = request.client.host if request.client else "unknown"
    hops = settings.trusted_proxy_hops
    if not hops:
        return peer
    forwarded = [h.strip() for h in request.headers.get("x-forwarded-for", "").split(",") if h.strip()]
    return forwarded[-hops] if len(forwarded) >= hops else peer


def check_rate_limit(*keys: str, limit: int | None = None) -> None:
    """Count one hit for every key; raise 429 when any key exceeds `limit` per minute."""
    limit = limit or settings.auth_rate_limit_per_minute
    now = time.monotonic()
    retry_after = 0.0
    with _lock:
        for key in keys:
            q = _hits.setdefault(key, deque())
            while q and now - q[0] >= _WINDOW_SECONDS:
                q.popleft()
            if len(q) >= limit:
                retry_after = max(retry_after, _WINDOW_SECONDS - (now - q[0]))
                continue
            q.append(now)
        if len(_hits) > 50_000:  # bound memory: forget idle keys
            for k in [k for k, q in _hits.items() if not q or now - q[-1] >= _WINDOW_SECONDS]:
                _hits.pop(k, None)
    if retry_after:
        from app.core.i18n import AppError

        raise AppError(
            429,
            "auth.rate_limited",
            headers={"Retry-After": str(max(1, math.ceil(retry_after)))},
        )


def raise_if_limited(request: Request, scope: str, *identifiers: str) -> None:
    check_rate_limit(f"{scope}:ip:{client_ip(request)}", *(f"{scope}:id:{i}" for i in identifiers if i))

