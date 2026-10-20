"""Fixed-window rate limiter built on the cache backend."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from shortener.cache import Cache


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    limit: int
    remaining: int
    retry_after: int


class RateLimiter:
    """Allow at most ``limit`` hits per ``window_seconds`` for each key.

    Uses the cache's atomic ``incr`` so the same code works on Redis (shared across
    replicas) and on the in-memory backend.
    """

    def __init__(
        self,
        cache: Cache,
        limit: int,
        window_seconds: int = 60,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._cache = cache
        self.limit = limit
        self.window = window_seconds
        self._clock = clock

    def hit(self, key: str) -> RateLimitResult:
        now = int(self._clock())
        window_start = now - (now % self.window)
        bucket = f"rl:{key}:{window_start}"
        count = self._cache.incr(bucket, ttl=self.window)
        remaining = max(self.limit - count, 0)
        retry_after = window_start + self.window - now if count > self.limit else 0
        return RateLimitResult(
            allowed=count <= self.limit,
            limit=self.limit,
            remaining=remaining,
            retry_after=retry_after,
        )
