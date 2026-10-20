"""ORM models: a short ``Link`` and the ``Click`` events recorded against it."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shortener.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Link(Base):
    __tablename__ = "links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    target_url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    is_custom: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    click_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    clicks: Mapped[list[Click]] = relationship(
        back_populates="link", cascade="all, delete-orphan", passive_deletes=True
    )

    @property
    def is_password_protected(self) -> bool:
        return self.password_hash is not None

    def is_expired(self, now: datetime | None = None) -> bool:
        if self.expires_at is None:
            return False
        now = now or utcnow()
        expires_at = self.expires_at
        if expires_at.tzinfo is None:  # SQLite drops tzinfo
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        return expires_at <= now


class Click(Base):
    __tablename__ = "clicks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    link_id: Mapped[int] = mapped_column(
        ForeignKey("links.id", ondelete="CASCADE"), nullable=False, index=True
    )
    clicked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    referrer: Mapped[str | None] = mapped_column(Text, nullable=True)
    referrer_host: Mapped[str | None] = mapped_column(String(255), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    browser: Mapped[str] = mapped_column(String(50), default="Unknown")
    os: Mapped[str] = mapped_column(String(50), default="Unknown")
    device: Mapped[str] = mapped_column(String(20), default="other")
    country: Mapped[str | None] = mapped_column(String(2), nullable=True)
    ip_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    link: Mapped[Link] = relationship(back_populates="clicks")


Index("ix_clicks_link_clicked_at", Click.link_id, Click.clicked_at)
