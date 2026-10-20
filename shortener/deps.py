"""FastAPI dependencies resolving per-app resources from ``app.state``."""

from __future__ import annotations

from collections.abc import Generator

from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from shortener.cache import Cache
from shortener.config import Settings
from shortener.geoip import GeoIPResolver
from shortener.ratelimit import RateLimiter
from shortener.security import client_ip
from shortener.services import LinkService


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def get_cache(request: Request) -> Cache:
    return request.app.state.cache


def get_geoip(request: Request) -> GeoIPResolver:
    return request.app.state.geoip


def get_db(request: Request) -> Generator[Session, None, None]:
    db: Session = request.app.state.session_factory()
    try:
        yield db
    finally:
        db.close()


def get_link_service(
    db: Session = Depends(get_db), settings: Settings = Depends(get_settings_dep)
) -> LinkService:
    return LinkService(db, min_code_length=settings.min_code_length)


def rate_limited(request: Request, response: Response) -> None:
    """Per-client-IP rate limit. Adds X-RateLimit-* headers; raises 429 when exceeded."""
    limiter: RateLimiter = request.app.state.rate_limiter
    result = limiter.hit(client_ip(request))
    response.headers["X-RateLimit-Limit"] = str(result.limit)
    response.headers["X-RateLimit-Remaining"] = str(result.remaining)
    if not result.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded",
            headers={
                "Retry-After": str(result.retry_after),
                "X-RateLimit-Limit": str(result.limit),
                "X-RateLimit-Remaining": "0",
            },
        )
