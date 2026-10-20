"""Pydantic request/response schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

ALIAS_PATTERN = r"^[A-Za-z0-9_-]{3,32}$"
RESERVED_ALIASES = frozenset(
    {"api", "health", "docs", "redoc", "openapi.json", "static", "shorten"}
)


class LinkCreate(BaseModel):
    url: HttpUrl
    alias: str | None = Field(
        default=None,
        pattern=ALIAS_PATTERN,
        description="Custom short code (3-32 chars: letters, digits, '-' or '_').",
    )
    title: str | None = Field(default=None, max_length=200)
    password: str | None = Field(default=None, min_length=4, max_length=128)
    expires_at: datetime | None = None
    expires_in_seconds: int | None = Field(default=None, ge=60, le=10 * 365 * 24 * 3600)

    @field_validator("alias")
    @classmethod
    def alias_not_reserved(cls, value: str | None) -> str | None:
        if value is not None and value.lower() in RESERVED_ALIASES:
            raise ValueError(f"'{value}' is a reserved path")
        return value

    @field_validator("url")
    @classmethod
    def url_scheme(cls, value: HttpUrl) -> HttpUrl:
        if value.scheme not in {"http", "https"}:
            raise ValueError("only http and https URLs can be shortened")
        return value

    @model_validator(mode="after")
    def single_expiry(self) -> LinkCreate:
        if self.expires_at is not None and self.expires_in_seconds is not None:
            raise ValueError("use either expires_at or expires_in_seconds, not both")
        return self


class LinkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    short_url: str
    target_url: str
    title: str | None
    is_custom: bool
    is_active: bool
    is_password_protected: bool
    created_at: datetime
    expires_at: datetime | None
    click_count: int


class LinkList(BaseModel):
    items: list[LinkOut]
    total: int
    limit: int
    offset: int


class CountRow(BaseModel):
    key: str
    count: int


class DayRow(BaseModel):
    day: str
    count: int


class LinkAnalytics(BaseModel):
    code: str
    total_clicks: int
    unique_visitors: int
    clicks_by_day: list[DayRow]
    top_referrers: list[CountRow]
    browsers: list[CountRow]
    operating_systems: list[CountRow]
    devices: list[CountRow]
    countries: list[CountRow]


class HealthOut(BaseModel):
    status: str
    database: str
    cache: str
    version: str
