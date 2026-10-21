"""Application settings loaded from environment variables (prefix ``SHORTENER_``)."""

from __future__ import annotations

from functools import lru_cache

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SHORTENER_", env_file=".env", extra="ignore", populate_by_name=True
    )

    app_name: str = "URL Shortener"
    # Render publishes the service URL as RENDER_EXTERNAL_URL; an explicit SHORTENER_BASE_URL wins.
    base_url: str = Field(
        default="http://localhost:8000",
        validation_alias=AliasChoices("SHORTENER_BASE_URL", "RENDER_EXTERNAL_URL", "base_url"),
    )
    database_url: str = "sqlite:///./shortener.db"
    redis_url: str | None = None
    api_key: str = Field(default="dev-api-key-change-me", min_length=8)
    ip_hash_secret: str = "change-me-too"
    rate_limit_per_minute: int = Field(default=60, ge=1)
    cache_ttl_seconds: int = Field(default=3600, ge=1)
    min_code_length: int = Field(default=6, ge=4, le=12)
    geoip_enabled: bool = False
    log_level: str = "INFO"

    @field_validator("database_url")
    @classmethod
    def _normalise_database_url(cls, value: str) -> str:
        """Managed Postgres (Render, Heroku) hands out ``postgres://`` or ``postgresql://`` URLs;
        SQLAlchemy needs the psycopg 3 driver spelled out."""
        for prefix in ("postgres://", "postgresql://"):
            if value.startswith(prefix):
                return "postgresql+psycopg://" + value[len(prefix) :]
        return value

    @property
    def short_url_prefix(self) -> str:
        return self.base_url.rstrip("/") + "/"


@lru_cache
def get_settings() -> Settings:
    return Settings()
