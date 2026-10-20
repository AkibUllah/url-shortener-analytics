"""Server-rendered landing page and public stats page."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from shortener.analytics import link_analytics
from shortener.config import Settings
from shortener.deps import get_db, get_link_service, get_settings_dep, rate_limited
from shortener.schemas import LinkCreate
from shortener.services import AliasTakenError, LinkService

router = APIRouter(tags=["pages"], include_in_schema=False)


@router.get("/", response_class=HTMLResponse)
def landing(request: Request, settings: Settings = Depends(get_settings_dep)):
    return request.app.state.templates.TemplateResponse(
        request, "index.html", {"app_name": settings.app_name, "result": None, "error": None}
    )


@router.post("/shorten", response_class=HTMLResponse, dependencies=[Depends(rate_limited)])
def shorten_form(
    request: Request,
    url: str = Form(...),
    alias: str = Form(default=""),
    service: LinkService = Depends(get_link_service),
    settings: Settings = Depends(get_settings_dep),
):
    """Public, rate-limited creation used by the landing page (no custom passwords/expiry)."""
    context: dict = {"app_name": settings.app_name, "result": None, "error": None}
    try:
        payload = LinkCreate(url=url, alias=alias.strip() or None)
        link = service.create(payload)
    except ValidationError as exc:
        context["error"] = "; ".join(
            err["msg"].removeprefix("Value error, ") for err in exc.errors()
        )
        return request.app.state.templates.TemplateResponse(
            request, "index.html", context, status_code=422
        )
    except AliasTakenError:
        context["error"] = f"Alias '{alias}' is already taken"
        return request.app.state.templates.TemplateResponse(
            request, "index.html", context, status_code=409
        )
    context["result"] = {
        "short_url": settings.short_url_prefix + link.code,
        "code": link.code,
        "target_url": link.target_url,
    }
    return request.app.state.templates.TemplateResponse(request, "index.html", context)


@router.get("/{code}+", response_class=HTMLResponse)
def stats_page(
    code: str,
    request: Request,
    db: Session = Depends(get_db),
    service: LinkService = Depends(get_link_service),
    settings: Settings = Depends(get_settings_dep),
):
    link = service.get_by_code(code)
    if link is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Link not found")
    stats = link_analytics(db, link, days=14)
    max_day = max((row.count for row in stats.clicks_by_day), default=0) or 1
    return request.app.state.templates.TemplateResponse(
        request,
        "stats.html",
        {
            "app_name": settings.app_name,
            "link": link,
            "short_url": settings.short_url_prefix + link.code,
            "stats": stats,
            "max_day": max_day,
        },
    )
