"""Cache abstraction with Redis and in-memory implementations.

Hot redirects are served from the cache so the database is only hit on a miss.
The in-memory implementation is used when ``SHORTENER_REDIS_URL`` is not set
and in the test-suite (alongside ``fakeredis`` for the Redis code path).
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Protocol

logger = logging.getLogger(__name__)


class Cache(Protocol):
    def get(self, key: str) -> str | None: ...

    def set(self, key: str, value: str, ttl: int) -> None: ...

    def delete(self, key: str) -> None: ...

    def incr(self, key: str, ttl: int) -> int:
        """Increment a counter, setting ``ttl`` when the key is first created."""
        ...

    def ping(self) -> bool: ...


class MemoryCache:
    """Thread-safe dict cache with per-key TTL. ``clock`` is injectable for tests."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._data: dict[str, tuple[str, float]] = {}

    def _purge_expired(self) -> None:
        now = self._clock()
        expired = [k for k, (_, exp) in self._data.items() if exp <= now]
        for k in expired:
            del self._data[k]

    def get(self, key: str) -> str | None:
        with self._lock:
            item = self._data.get(key)
            if item is None:
                return None
            value, expires_at = item
            if expires_at <= self._clock():
                del self._data[key]
                return None
            return value

    def set(self, key: str, value: str, ttl: int) -> None:
        with self._lock:
            if len(self._data) > 10_000:
                self._purge_expired()
            self._data[key] = (value, self._clock() + ttl)

    def delete(self, key: str) -> None:
        with self._lock:
            self._data.pop(key, None)

    def incr(self, key: str, ttl: int) -> int:
        with self._lock:
            now = self._clock()
            item = self._data.get(key)
            if item is None or item[1] <= now:
                self._data[key] = ("1", now + ttl)
                return 1
            value = int(item[0]) + 1
            self._data[key] = (str(value), item[1])
            return value

    def ping(self) -> bool:
        return True


class RedisCache:
    """Cache backed by a redis-py client (real Redis or fakeredis)."""

    def __init__(self, client) -> None:  # noqa: ANN001 - redis.Redis or fakeredis.FakeRedis
        self._client = client

    def get(self, key: str) -> str | None:
        value = self._client.get(key)
        if value is None:
            return None
        return value.decode("utf-8") if isinstance(value, bytes) else str(value)

    def set(self, key: str, value: str, ttl: int) -> None:
        self._client.set(key, value, ex=ttl)

    def delete(self, key: str) -> None:
        self._client.delete(key)

    def incr(self, key: str, ttl: int) -> int:
        pipe = self._client.pipeline()
        pipe.incr(key)
        pipe.expire(key, ttl, nx=True)
        count, _ = pipe.execute()
        return int(count)

    def ping(self) -> bool:
        try:
            return bool(self._client.ping())
        except Exception:  # noqa: BLE001 - any connection error means "down"
            return False


def build_cache(redis_url: str | None) -> Cache:
    """Create the cache for the given settings, falling back to memory when Redis is unavailable."""
    if not redis_url:
        logger.info("cache: using in-memory backend")
        return MemoryCache()
    import redis

    client = redis.Redis.from_url(redis_url, socket_connect_timeout=1, socket_timeout=1)
    cache = RedisCache(client)
    if cache.ping():
        logger.info("cache: using redis backend at %s", redis_url)
        return cache
    logger.warning("cache: redis at %s unreachable, falling back to memory", redis_url)
    return MemoryCache()
