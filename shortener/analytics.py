"""Aggregations over click events for a single link."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from shortener.models import Click, Link
from shortener.schemas import CountRow, DayRow, LinkAnalytics


def _top(
    db: Session, link_id: int, column, limit: int, label_null: str | None = None
) -> list[CountRow]:  # noqa: ANN001
    stmt = (
        select(column, func.count(Click.id))
        .where(Click.link_id == link_id)
        .group_by(column)
        .order_by(func.count(Click.id).desc(), column)
        .limit(limit)
    )
    rows = []
    for key, count in db.execute(stmt):
        if key is None:
            if label_null is None:
                continue
            key = label_null
        rows.append(CountRow(key=str(key), count=int(count)))
    return rows


def clicks_by_day(db: Session, link_id: int, days: int) -> list[DayRow]:
    """Daily click counts for the last ``days`` days, zero-filled."""
    today = datetime.now(timezone.utc).date()
    start = datetime.combine(
        today - timedelta(days=days - 1), datetime.min.time(), tzinfo=timezone.utc
    )
    rows = db.execute(
        select(Click.clicked_at).where(Click.link_id == link_id, Click.clicked_at >= start)
    ).all()
    counts: dict[str, int] = {}
    for (clicked_at,) in rows:
        if clicked_at.tzinfo is None:
            clicked_at = clicked_at.replace(tzinfo=timezone.utc)
        key = clicked_at.date().isoformat()
        counts[key] = counts.get(key, 0) + 1
    return [
        DayRow(
            day=(start.date() + timedelta(days=i)).isoformat(),
            count=counts.get((start.date() + timedelta(days=i)).isoformat(), 0),
        )
        for i in range(days)
    ]


def link_analytics(db: Session, link: Link, days: int = 30, top: int = 10) -> LinkAnalytics:
    total = db.scalar(select(func.count(Click.id)).where(Click.link_id == link.id)) or 0
    unique = (
        db.scalar(
            select(func.count(func.distinct(Click.ip_hash))).where(
                Click.link_id == link.id, Click.ip_hash.is_not(None)
            )
        )
        or 0
    )
    return LinkAnalytics(
        code=link.code,
        total_clicks=int(total),
        unique_visitors=int(unique),
        clicks_by_day=clicks_by_day(db, link.id, days),
        top_referrers=_top(db, link.id, Click.referrer_host, top, label_null="(direct)"),
        browsers=_top(db, link.id, Click.browser, top),
        operating_systems=_top(db, link.id, Click.os, top),
        devices=_top(db, link.id, Click.device, top),
        countries=_top(db, link.id, Click.country, top),
    )
