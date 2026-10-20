"""Password hashing, IP hashing and API-key authentication."""

from __future__ import annotations

import hashlib
import hmac
import secrets

from fastapi import Header, HTTPException, Request, status

from shortener.config import Settings

_PBKDF2_ITERATIONS = 200_000


def hash_password(password: str) -> str:
    """Hash a link password with PBKDF2-HMAC-SHA256. Format: ``pbkdf2$iter$salt$hash``."""
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("ascii"), _PBKDF2_ITERATIONS
    )
    return f"pbkdf2${_PBKDF2_ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, iterations, salt, expected = stored.split("$")
        if scheme != "pbkdf2":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt.encode("ascii"), int(iterations)
        )
    except (ValueError, AttributeError):
        return False
    return hmac.compare_digest(digest.hex(), expected)


def hash_ip(ip: str | None, secret: str) -> str | None:
    """Keyed hash of a client IP so we can count unique visitors without storing addresses."""
    if not ip:
        return None
    return hmac.new(secret.encode("utf-8"), ip.encode("utf-8"), hashlib.sha256).hexdigest()[:32]


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def require_api_key(
    request: Request,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> None:
    """Dependency guarding management endpoints with the configured static API key."""
    settings: Settings = request.app.state.settings
    if not x_api_key or not hmac.compare_digest(x_api_key, settings.api_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )
