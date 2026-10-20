"""Management API: create, list, inspect, delete links; QR code; analytics."""

from __future__ import annotations

import io

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from shortener.analytics import link_analytics
from shortener.cache import Cache
from shortener.config import Settings
from shortener.deps import get_cache, get_db, get_link_service, get_settings_dep, rate_limited
from shortener.models import Link
from shortener.schemas import LinkAnalytics, LinkCreate, LinkList, LinkOut
from shortener.security import require_api_key
from shortener.services import AliasTakenError, LinkService

router = APIRouter(prefix="/api/v1/links", tags=["links"])


def to_out(link: Link, settings: Settings) -> LinkOut:
    return LinkOut(
        code=link.code,
        short_url=settings.short_url_prefix + link.code,
        target_url=link.target_url,
        title=link.title,
        is_custom=link.is_custom,
        is_active=link.is_active,
        is_password_protected=link.is_password_protected,
        created_at=link.created_at,
        expires_at=link.expires_at,
        click_count=link.click_count,
    )


def _get_or_404(service: LinkService, code: str) -> Link:
    link = service.get_by_code(code)
    if link is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Link not found")
    return link


@router.post(
    "",
    response_model=LinkOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_api_key), Depends(rate_limited)],
)
def create_link(
    payload: LinkCreate,
    service: LinkService = Depends(get_link_service),
    settings: Settings = Depends(get_settings_dep),
) -> LinkOut:
    try:
        link = service.create(payload)
    except AliasTakenError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"Alias '{exc}' is already taken"
        ) from exc
    return to_out(link, settings)


@router.get("", response_model=LinkList, dependencies=[Depends(require_api_key)])
def list_links(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    service: LinkService = Depends(get_link_service),
    settings: Settings = Depends(get_settings_dep),
) -> LinkList:
    items, total = service.list(limit=limit, offset=offset)
    return LinkList(
        items=[to_out(i, settings) for i in items], total=total, limit=limit, offset=offset
    )


@router.get("/{code}", response_model=LinkOut, dependencies=[Depends(require_api_key)])
def get_link(
    code: str,
    service: LinkService = Depends(get_link_service),
    settings: Settings = Depends(get_settings_dep),
) -> LinkOut:
    return to_out(_get_or_404(service, code), settings)


@router.delete(
    "/{code}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_api_key)]
)
def delete_link(
    code: str,
    service: LinkService = Depends(get_link_service),
    cache: Cache = Depends(get_cache),
) -> Response:
    """Deactivate a link (soft delete) and evict it from the redirect cache."""
    link = _get_or_404(service, code)
    service.deactivate(link)
    cache.delete(f"link:{code}")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{code}/qr", response_class=Response, responses={200: {"content": {"image/png": {}}}})
def qr_code(
    code: str,
    scale: int = Query(default=6, ge=1, le=20),
    service: LinkService = Depends(get_link_service),
    settings: Settings = Depends(get_settings_dep),
) -> Response:
    import segno

    link = _get_or_404(service, code)
    qr = segno.make(settings.short_url_prefix + link.code, error="m")
    buffer = io.BytesIO()
    qr.save(buffer, kind="png", scale=scale, border=2)
    return Response(
        content=buffer.getvalue(),
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get(
    "/{code}/analytics", response_model=LinkAnalytics, dependencies=[Depends(require_api_key)]
)
def analytics(
    code: str,
    days: int = Query(default=30, ge=1, le=365),
    top: int = Query(default=10, ge=1, le=50),
    db: Session = Depends(get_db),
    service: LinkService = Depends(get_link_service),
) -> LinkAnalytics:
    link = _get_or_404(service, code)
    return link_analytics(db, link, days=days, top=top)
