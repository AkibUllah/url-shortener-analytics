from __future__ import annotations

import fakeredis
import pytest
from fastapi.testclient import TestClient

from shortener.cache import RedisCache
from shortener.config import Settings
from shortener.geoip import StaticGeoIP
from shortener.main import create_app

API_KEY = "test-api-key-123"


@pytest.fixture
def settings() -> Settings:
    return Settings(
        base_url="http://sho.rt",
        database_url="sqlite:///:memory:",
        redis_url=None,
        api_key=API_KEY,
        ip_hash_secret="unit-test-secret",
        rate_limit_per_minute=1000,
        cache_ttl_seconds=60,
        min_code_length=6,
        geoip_enabled=True,
        log_level="WARNING",
        _env_file=None,
    )


@pytest.fixture
def redis_cache() -> RedisCache:
    return RedisCache(fakeredis.FakeRedis())


@pytest.fixture
def app(settings: Settings, redis_cache: RedisCache):
    return create_app(settings=settings, cache=redis_cache, geoip=StaticGeoIP())


@pytest.fixture
def client(app):
    with TestClient(app, base_url="http://sho.rt") as c:
        yield c


@pytest.fixture
def auth() -> dict[str, str]:
    return {"X-API-Key": API_KEY}


@pytest.fixture
def make_link(client, auth):
    def _make(url: str = "https://example.com/some/long/path", **extra):
        payload = {"url": url, **extra}
        response = client.post("/api/v1/links", json=payload, headers=auth)
        assert response.status_code == 201, response.text
        return response.json()

    return _make
