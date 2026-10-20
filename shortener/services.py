"""Link lifecycle: creation with collision handling, resolution, click recording."""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from shortener import base62
from shortener.geoip import GeoIPResolver
from shortener.models import Click, Link, utcnow
from shortener.schemas import LinkCreate
from shortener.security import hash_ip, hash_password
from shortener.ua import parse_user_agent

logger = logging.getLogger(__name__)

MAX_COLLISION_RETRIES = 5


class AliasTakenError(Exception):
    """Raised when a custom alias is already in use."""


class LinkService:
    def __init__(self, db: Session, min_code_length: int = 6) -> None:
        self.db = db
        self.min_code_length = min_code_length

    # -- creation ---------------------------------------------------------

    def create(self, payload: LinkCreate) -> Link:
        expires_at = payload.expires_at
        if payload.expires_in_seconds is not None:
            expires_at = utcnow() + timedelta(seconds=payload.expires_in_seconds)
        if expires_at is not None and expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)

        link = Link(
            code=f"tmp-{secrets.token_hex(8)}",  # placeholder until we know the id
            target_url=str(payload.url),
            title=payload.title,
            is_custom=payload.alias is not None,
            password_hash=hash_password(payload.password) if payload.password else None,
            expires_at=expires_at,
        )

        if payload.alias is not None:
            if self.get_by_code(payload.alias) is not None:
                raise AliasTakenError(payload.alias)
            link.code = payload.alias
            self.db.add(link)
            try:
                self.db.commit()
            except IntegrityError as exc:  # lost a race with a concurrent insert
                self.db.rollback()
                raise AliasTakenError(payload.alias) from exc
            return link

        self.db.add(link)
        self.db.flush()  # assigns link.id from the sequence
        base_code = base62.code_for_id(link.id, self.min_code_length)
        link.code = base_code
        for attempt in range(MAX_COLLISION_RETRIES):
            try:
                self.db.commit()
                return link
            except IntegrityError:
                # A custom alias can equal a generated code. Append a random suffix and retry
                # with a fresh object, since rollback expunges the pending row.
                self.db.rollback()
                suffix = "".join(secrets.choice(base62.ALPHABET) for _ in range(2))
                logger.warning("short code collision on %s, retry %s", base_code, attempt + 1)
                link = Link(
                    code=f"{base_code}{suffix}",
                    target_url=str(payload.url),
                    title=payload.title,
                    is_custom=False,
                    password_hash=link.password_hash,
                    expires_at=expires_at,
                )
                self.db.add(link)
        self.db.rollback()
        raise RuntimeError("could not allocate a unique short code")

    # -- lookup -----------------------------------------------------------

    def get_by_code(self, code: str) -> Link | None:
        return self.db.scalar(select(Link).where(Link.code == code))

    def list(self, limit: int, offset: int) -> tuple[list[Link], int]:
        total = self.db.scalar(select(func.count()).select_from(Link)) or 0
        rows = self.db.scalars(
            select(Link)
            .order_by(Link.created_at.desc(), Link.id.desc())
            .limit(limit)
            .offset(offset)
        ).all()
        return list(rows), int(total)

    def deactivate(self, link: Link) -> None:
        link.is_active = False
        self.db.commit()

    # -- clicks -----------------------------------------------------------

    def record_click(
        self,
        link_id: int,
        *,
        referrer: str | None,
        user_agent: str | None,
        ip: str | None,
        ip_secret: str,
        geoip: GeoIPResolver,
        clicked_at: datetime | None = None,
    ) -> Click:
        ua = parse_user_agent(user_agent)
        click = Click(
            link_id=link_id,
            clicked_at=clicked_at or utcnow(),
            referrer=referrer[:2000] if referrer else None,
            referrer_host=referrer_host(referrer),
            user_agent=user_agent[:1000] if user_agent else None,
            browser=ua.browser,
            os=ua.os,
            device=ua.device,
            country=geoip.country(ip),
            ip_hash=hash_ip(ip, ip_secret),
        )
        self.db.add(click)
        self.db.execute(
            Link.__table__.update()
            .where(Link.id == link_id)
            .values(click_count=Link.click_count + 1)
        )
        self.db.commit()
        return click


def referrer_host(referrer: str | None) -> str | None:
    if not referrer:
        return None
    try:
        host = urlsplit(referrer).hostname
    except ValueError:
        return None
    if not host:
        return None
    return host.removeprefix("www.").lower()
