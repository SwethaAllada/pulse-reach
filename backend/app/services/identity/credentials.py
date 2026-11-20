"""Password hashing and opaque token helpers (standard-library primitives only).

- Passwords: scrypt (`hashlib.scrypt`, memory-hard, listed by OWASP) with a random 16-byte salt,
  stored as `scrypt$<n>$<r>$<p>$<salt_b64>$<hash_b64>` so parameters can be raised later and old
  hashes re-hashed on the next successful login (`needs_rehash`).
- Tokens: 256-bit random values from `secrets`; only their SHA-256 digest is ever stored.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

from app.core.config import settings

_R, _P, _DKLEN = 8, 1, 32
_MAX_PASSWORD_BYTES = 1024


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _scrypt(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8")[:_MAX_PASSWORD_BYTES],
        salt=salt,
        n=n,
        r=r,
        p=p,
        maxmem=2 * 128 * r * n + 1024 * 1024,
        dklen=_DKLEN,
    )


def hash_password(password: str) -> str:
    n = settings.password_scrypt_n
    salt = secrets.token_bytes(16)
    return f"scrypt${n}${_R}${_P}${_b64(salt)}${_b64(_scrypt(password, salt, n, _R, _P))}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        _dummy_verify(password)
        return False
    try:
        algo, n, r, p, salt_b64, hash_b64 = stored.split("$")
        if algo != "scrypt":
            return False
        expected = base64.b64decode(hash_b64)
        actual = _scrypt(password, base64.b64decode(salt_b64), int(n), int(r), int(p))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def needs_rehash(stored: str | None) -> bool:
    try:
        return int(str(stored).split("$")[1]) < settings.password_scrypt_n
    except (IndexError, ValueError):
        return True


def _dummy_verify(password: str) -> None:
    """Spend comparable time when the account does not exist (limits user enumeration)."""
    _scrypt(password, b"\x00" * 16, settings.password_scrypt_n, _R, _P)


def new_token(prefix: str) -> tuple[str, str]:
    """(raw token for the client, SHA-256 hex digest for storage)."""
    raw = f"{prefix}_{secrets.token_urlsafe(32)}"
    return raw, token_digest(raw)


def token_digest(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def new_invitation_code() -> tuple[str, str]:
    """Human-transcribable one-time code (`XXXX-XXXX-XXXX`, 60 bits, no ambiguous characters)."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    raw = "-".join("".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(3))
    return raw, token_digest(raw)


def normalize_invitation_code(code: str) -> str:
    cleaned = "".join(ch for ch in code.upper() if ch.isalnum())
    return "-".join(cleaned[i : i + 4] for i in range(0, len(cleaned), 4))
