"""Application factory."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from shortener import __version__
from shortener.cache import Cache, build_cache
from shortener.config import Settings, get_settings
from shortener.db import Base, make_engine, make_session_factory
from shortener.geoip import GeoIPResolver, build_geoip
from shortener.ratelimit import RateLimiter
from shortener.routers import health, links, pages, redirect

BASE_DIR = Path(__file__).resolve().parent


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def create_app(
    settings: Settings | None = None,
    cache: Cache | None = None,
    geoip: GeoIPResolver | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description="Short links with click analytics, QR codes and password protection.",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    engine = make_engine(settings.database_url)
    Base.metadata.create_all(engine)

    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = make_session_factory(engine)
    app.state.cache = cache or build_cache(settings.redis_url)
    app.state.geoip = geoip or build_geoip(settings.geoip_enabled)
    app.state.rate_limiter = RateLimiter(app.state.cache, limit=settings.rate_limit_per_minute)
    app.state.templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

    app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

    # Order matters: specific routes before the catch-all /{code} redirect.
    app.include_router(health.router)
    app.include_router(links.router)
    app.include_router(pages.router)
    app.include_router(redirect.router)

    return app


app = create_app()
