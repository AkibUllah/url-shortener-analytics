"""Liveness/readiness endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from shortener import __version__
from shortener.cache import Cache
from shortener.deps import get_cache, get_db
from shortener.schemas import HealthOut

router = APIRouter(tags=["ops"])


@router.get("/health", response_model=HealthOut)
def health(db: Session = Depends(get_db), cache: Cache = Depends(get_cache)) -> HealthOut:
    try:
        db.execute(text("SELECT 1"))
        database = "ok"
    except Exception:  # noqa: BLE001
        database = "error"
    cache_status = "ok" if cache.ping() else "error"
    status = "ok" if database == "ok" else "degraded"
    return HealthOut(status=status, database=database, cache=cache_status, version=__version__)
