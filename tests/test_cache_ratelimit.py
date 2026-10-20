import fakeredis

from shortener.cache import MemoryCache, RedisCache
from shortener.ratelimit import RateLimiter


class FakeClock:
    def __init__(self, start: float = 1_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_memory_cache_set_get_delete():
    cache = MemoryCache()
    cache.set("a", "1", ttl=60)
    assert cache.get("a") == "1"
    cache.delete("a")
    assert cache.get("a") is None


def test_memory_cache_expires_entries():
    clock = FakeClock()
    cache = MemoryCache(clock=clock)
    cache.set("a", "1", ttl=10)
    clock.advance(9)
    assert cache.get("a") == "1"
    clock.advance(2)
    assert cache.get("a") is None


def test_memory_cache_incr_resets_after_ttl():
    clock = FakeClock()
    cache = MemoryCache(clock=clock)
    assert cache.incr("c", ttl=5) == 1
    assert cache.incr("c", ttl=5) == 2
    clock.advance(6)
    assert cache.incr("c", ttl=5) == 1


def test_redis_cache_roundtrip_and_incr():
    cache = RedisCache(fakeredis.FakeRedis())
    cache.set("k", "v", ttl=30)
    assert cache.get("k") == "v"
    assert cache.incr("n", ttl=30) == 1
    assert cache.incr("n", ttl=30) == 2
    assert cache.ping() is True
    cache.delete("k")
    assert cache.get("k") is None


def test_rate_limiter_blocks_after_limit_and_resets_next_window():
    clock = FakeClock(start=1_000.0)
    limiter = RateLimiter(MemoryCache(clock=clock), limit=3, window_seconds=60, clock=clock)
    results = [limiter.hit("1.2.3.4") for _ in range(4)]
    assert [r.allowed for r in results] == [True, True, True, False]
    assert results[2].remaining == 0
    assert results[3].retry_after > 0
    assert limiter.hit("5.6.7.8").allowed  # independent key
    clock.advance(60)
    assert limiter.hit("1.2.3.4").allowed


def test_rate_limiter_on_redis_backend():
    limiter = RateLimiter(RedisCache(fakeredis.FakeRedis()), limit=2)
    assert limiter.hit("k").allowed
    assert limiter.hit("k").allowed
    assert not limiter.hit("k").allowed
