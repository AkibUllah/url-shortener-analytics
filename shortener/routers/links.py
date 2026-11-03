"""Management API: create, list, inspect, delete links; QR code; analytics."""

from __future__ import annotations

import io

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from shortener.analytics import link_analytics
from shortener.bulk import CREATED, VALID, CsvImportError, import_links, parse_import_csv
from shortener.cache import Cache
from shortener.config import Settings
from shortener.deps import get_cache, get_db, get_link_service, get_settings_dep, rate_limited
from shortener.models import Link
from shortener.schemas import (
    ImportReport,
    ImportRowOut,
    LinkAnalytics,
    LinkCreate,
    LinkList,
    LinkOut,
)
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


async def _read_limited(upload: UploadFile, max_bytes: int) -> bytes:
    data = await upload.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File is larger than {max_bytes} bytes",
        )
    return data


@router.post(
    "/import",
    response_model=ImportReport,
    dependencies=[Depends(require_api_key), Depends(rate_limited)],
)
async def import_links_csv(
    file: UploadFile = File(description="UTF-8 CSV with a header: url, alias, title, expires_at"),
    dry_run: bool = Query(default=False, description="Validate and check aliases only"),
    service: LinkService = Depends(get_link_service),
    settings: Settings = Depends(get_settings_dep),
) -> ImportReport:
    """Create many links from one CSV file.

    Every row is validated like ``POST /api/v1/links``. Valid rows are created, the others are
    reported with a reason (``invalid``, ``alias_taken``); the file as a whole only fails when it
    cannot be read, has no ``url`` column or exceeds the size or row limit.
    """
    data = await _read_limited(file, settings.import_max_bytes)
    try:
        parsed = parse_import_csv(data, settings.import_max_rows)
    except CsvImportError as exc:
        # Numbers, not constants: newer Starlette renamed both and warns on the old names.
        code = 413 if exc.too_large else 422
        raise HTTPException(status_code=code, detail=str(exc)) from exc

    result = await run_in_threadpool(import_links, service, parsed, dry_run=dry_run)
    return ImportReport(
        dry_run=result.dry_run,
        total=len(result.rows),
        succeeded=result.succeeded,
        failed=result.failed,
        ignored_columns=result.ignored_columns,
        rows=[
            ImportRowOut(
                row=r.row,
                status=r.status,
                code=r.code,
                short_url=(
                    settings.short_url_prefix + r.code
                    if r.code and r.status in (CREATED, VALID)
                    else None
                ),
                error=r.error,
            )
            for r in result.rows
        ],
    )


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
