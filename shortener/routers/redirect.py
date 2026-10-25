"""Public redirect endpoint with hot-path caching and asynchronous click recording."""

from __future__ import annotations

import json
import logging
from datetime import timezone
from urllib.parse import urlsplit

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Request, status
from fastapi.responses import RedirectResponse

from shortener.cache import Cache
from shortener.config import Settings
from shortener.deps import get_cache, get_geoip, get_link_service, get_settings_dep, rate_limited
from shortener.geoip import GeoIPResolver
from shortener.models import Link, utcnow
from shortener.security import client_ip, verify_password
from shortener.services import LinkService

logger = logging.getLogger(__name__)
router = APIRouter(tags=["redirect"])


def cache_key(code: str) -> str:
    return f"link:{code}"


def cached_target(raw: str | bytes | None) -> tuple[int, str] | None:
    """Decode a cached redirect entry into (link_id, target_url).

    Returns None for a missing, corrupt or non-http(s) entry so the caller falls back to the
    database instead of redirecting somewhere the API would never have accepted.
    """
    if not raw:
        return None
    try:
        data = json.loads(raw)
        link_id, url = int(data["id"]), str(data["url"])
    except (ValueError, KeyError, TypeError):
        logger.warning("ignoring malformed cache entry")
        return None
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        logger.warning("ignoring cached redirect with unsupported target")
        return None
    return link_id, url


def _resolve(service: LinkService, code: str) -> Link:
    link = service.get_by_code(code)
    if link is None or not link.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Short link not found")
    if link.is_expired():
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Short link has expired")
    return link


def _schedule_click(
    request: Request,
    background: BackgroundTasks,
    link_id: int,
    settings: Settings,
    geoip: GeoIPResolver,
) -> None:
    session_factory = request.app.state.session_factory
    referrer = request.headers.get("referer")
    user_agent = request.headers.get("user-agent")
    ip = client_ip(request)

    def _record() -> None:
        db = session_factory()
        try:
            LinkService(db).record_click(
                link_id,
                referrer=referrer,
                user_agent=user_agent,
                ip=ip,
                ip_secret=settings.ip_hash_secret,
                geoip=geoip,
            )
        except Exception:  # noqa: BLE001 - never let analytics break a redirect
            logger.exception("failed to record click for link_id=%s", link_id)
        finally:
            db.close()

    background.add_task(_record)


@router.get("/{code}", dependencies=[Depends(rate_limited)], response_class=RedirectResponse)
def redirect(
    code: str,
    request: Request,
    background: BackgroundTasks,
    cache: Cache = Depends(get_cache),
    service: LinkService = Depends(get_link_service),
    settings: Settings = Depends(get_settings_dep),
    geoip: GeoIPResolver = Depends(get_geoip),
):
    hit = cached_target(cache.get(cache_key(code)))
    if hit is not None:
        link_id, target_url = hit
        _schedule_click(request, background, link_id, settings, geoip)
        return RedirectResponse(target_url, status_code=status.HTTP_302_FOUND)

    link = _resolve(service, code)
    if link.is_password_protected:
        return request.app.state.templates.TemplateResponse(
            request, "password.html", {"code": code, "error": None}, status_code=200
        )

    # Expiring links are cached only until they expire.
    ttl = settings.cache_ttl_seconds
    if link.expires_at is not None:
        expires_at = link.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        ttl = max(1, min(ttl, int((expires_at - utcnow()).total_seconds())))
    cache.set(cache_key(code), json.dumps({"id": link.id, "url": link.target_url}), ttl=ttl)

    _schedule_click(request, background, link.id, settings, geoip)
    return RedirectResponse(link.target_url, status_code=status.HTTP_302_FOUND)


@router.post("/{code}", dependencies=[Depends(rate_limited)], response_class=RedirectResponse)
def unlock(
    code: str,
    request: Request,
    background: BackgroundTasks,
    password: str = Form(...),
    service: LinkService = Depends(get_link_service),
    settings: Settings = Depends(get_settings_dep),
    geoip: GeoIPResolver = Depends(get_geoip),
):
    link = _resolve(service, code)
    if not link.is_password_protected:
        return RedirectResponse(link.target_url, status_code=status.HTTP_302_FOUND)
    if not verify_password(password, link.password_hash or ""):
        return request.app.state.templates.TemplateResponse(
            request,
            "password.html",
            {"code": code, "error": "Incorrect password"},
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
    _schedule_click(request, background, link.id, settings, geoip)
    return RedirectResponse(link.target_url, status_code=status.HTTP_302_FOUND)
