from __future__ import annotations

from datetime import datetime, timedelta, timezone

from shortener import base62
from shortener.schemas import LinkCreate
from shortener.services import LinkService

CHROME_WIN = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
SAFARI_IPHONE = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1"
)


# -- creation ---------------------------------------------------------------


def test_create_link_generates_code(make_link):
    data = make_link("https://example.com/a")
    assert len(data["code"]) >= 6
    assert data["short_url"] == f"http://sho.rt/{data['code']}"
    assert data["target_url"] == "https://example.com/a"
    assert data["is_custom"] is False
    assert data["click_count"] == 0


def test_generated_codes_are_unique(make_link):
    codes = {make_link(f"https://example.com/{i}")["code"] for i in range(10)}
    assert len(codes) == 10


def test_create_with_custom_alias(make_link):
    data = make_link("https://bkash.com/offers", alias="bkash-offer")
    assert data["code"] == "bkash-offer"
    assert data["is_custom"] is True


def test_duplicate_alias_returns_409(client, auth, make_link):
    make_link("https://example.com/1", alias="taken")
    response = client.post(
        "/api/v1/links", json={"url": "https://example.com/2", "alias": "taken"}, headers=auth
    )
    assert response.status_code == 409


def test_invalid_alias_and_reserved_alias_rejected(client, auth):
    bad = client.post("/api/v1/links", json={"url": "https://x.com", "alias": "a b"}, headers=auth)
    assert bad.status_code == 422
    reserved = client.post(
        "/api/v1/links", json={"url": "https://x.com", "alias": "docs"}, headers=auth
    )
    assert reserved.status_code == 422


def test_invalid_url_rejected(client, auth):
    assert client.post("/api/v1/links", json={"url": "not a url"}, headers=auth).status_code == 422
    assert (
        client.post(
            "/api/v1/links", json={"url": "ftp://files.example.com"}, headers=auth
        ).status_code
        == 422
    )


def test_management_requires_api_key(client):
    assert client.post("/api/v1/links", json={"url": "https://x.com"}).status_code == 401
    assert client.get("/api/v1/links").status_code == 401
    assert client.get("/api/v1/links", headers={"X-API-Key": "wrong"}).status_code == 401


def test_list_links_paginates(client, auth, make_link):
    for i in range(5):
        make_link(f"https://example.com/{i}")
    page = client.get("/api/v1/links?limit=2&offset=0", headers=auth).json()
    assert page["total"] == 5
    assert len(page["items"]) == 2
    page2 = client.get("/api/v1/links?limit=2&offset=4", headers=auth).json()
    assert len(page2["items"]) == 1


def test_generated_code_collision_is_retried(client, auth, make_link, monkeypatch):
    # Pre-create a custom alias, then force the generator to produce that same code.
    make_link("https://example.com/custom", alias="clash1")
    monkeypatch.setattr(base62, "code_for_id", lambda _id, min_length=6: "clash1")
    data = make_link("https://example.com/other")
    assert data["code"] != "clash1"
    assert data["code"].startswith("clash1")
    assert len(data["code"]) == 8


# -- redirect ---------------------------------------------------------------


def test_redirect_302_and_click_recorded(client, auth, make_link):
    code = make_link("https://example.com/landing")["code"]
    response = client.get(
        f"/{code}",
        follow_redirects=False,
        headers={"User-Agent": CHROME_WIN, "Referer": "https://www.facebook.com/some/post"},
    )
    assert response.status_code == 302
    assert response.headers["location"] == "https://example.com/landing"

    detail = client.get(f"/api/v1/links/{code}", headers=auth).json()
    assert detail["click_count"] == 1


def test_unknown_code_404(client):
    assert client.get("/doesnotexist", follow_redirects=False).status_code == 404


def test_expired_link_returns_410(client, auth):
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    created = client.post(
        "/api/v1/links", json={"url": "https://example.com/old", "expires_at": past}, headers=auth
    )
    assert created.status_code == 201
    code = created.json()["code"]
    assert client.get(f"/{code}", follow_redirects=False).status_code == 410


def test_expires_in_seconds_sets_expiry(make_link):
    data = make_link("https://example.com/soon", expires_in_seconds=3600)
    assert data["expires_at"] is not None


def test_redirect_is_served_from_cache_on_second_hit(client, make_link, redis_cache):
    code = make_link("https://example.com/hot")["code"]
    assert redis_cache.get(f"link:{code}") is None
    client.get(f"/{code}", follow_redirects=False)
    assert redis_cache.get(f"link:{code}") is not None
    # Even if the DB row vanished, the cached entry answers the redirect.
    response = client.get(f"/{code}", follow_redirects=False)
    assert response.status_code == 302


def test_delete_deactivates_and_evicts_cache(client, auth, make_link, redis_cache):
    code = make_link("https://example.com/bye")["code"]
    client.get(f"/{code}", follow_redirects=False)
    assert redis_cache.get(f"link:{code}") is not None
    assert client.delete(f"/api/v1/links/{code}", headers=auth).status_code == 204
    assert redis_cache.get(f"link:{code}") is None
    assert client.get(f"/{code}", follow_redirects=False).status_code == 404
    assert client.delete("/api/v1/links/nope", headers=auth).status_code == 404


def test_password_protected_flow(client, make_link):
    code = make_link("https://example.com/secret", password="open-sesame")["code"]
    page = client.get(f"/{code}", follow_redirects=False)
    assert page.status_code == 200
    assert "password" in page.text.lower()

    wrong = client.post(f"/{code}", data={"password": "nope"}, follow_redirects=False)
    assert wrong.status_code == 401

    right = client.post(f"/{code}", data={"password": "open-sesame"}, follow_redirects=False)
    assert right.status_code == 302
    assert right.headers["location"] == "https://example.com/secret"


def test_rate_limit_returns_429(settings, redis_cache):
    from fastapi.testclient import TestClient

    from shortener.main import create_app

    limited = settings.model_copy(update={"rate_limit_per_minute": 2})
    app = create_app(settings=limited, cache=redis_cache)
    with TestClient(app) as c:
        c.get("/x1", follow_redirects=False)
        c.get("/x2", follow_redirects=False)
        blocked = c.get("/x3", follow_redirects=False)
    assert blocked.status_code == 429
    assert "Retry-After" in blocked.headers
    assert blocked.headers["X-RateLimit-Remaining"] == "0"


# -- QR, analytics, pages, health -------------------------------------------


def test_qr_endpoint_returns_png(client, make_link):
    code = make_link("https://example.com/qr")["code"]
    response = client.get(f"/api/v1/links/{code}/qr")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_analytics_aggregates_clicks(client, auth, make_link):
    code = make_link("https://example.com/stats")["code"]
    hits = [
        (CHROME_WIN, "https://www.facebook.com/p/1", "103.108.141.5"),
        (CHROME_WIN, "https://facebook.com/p/2", "103.108.141.6"),
        (SAFARI_IPHONE, "https://t.co/abc", "8.8.8.8"),
        (SAFARI_IPHONE, None, "103.108.141.5"),
    ]
    for ua, ref, ip in hits:
        headers = {"User-Agent": ua, "X-Forwarded-For": ip}
        if ref:
            headers["Referer"] = ref
        client.get(f"/{code}", follow_redirects=False, headers=headers)

    stats = client.get(f"/api/v1/links/{code}/analytics?days=7", headers=auth).json()
    assert stats["total_clicks"] == 4
    assert stats["unique_visitors"] == 3
    assert len(stats["clicks_by_day"]) == 7
    assert stats["clicks_by_day"][-1]["count"] == 4
    assert stats["top_referrers"][0] == {"key": "facebook.com", "count": 2}
    assert {r["key"]: r["count"] for r in stats["devices"]} == {"desktop": 2, "mobile": 2}
    assert {r["key"]: r["count"] for r in stats["browsers"]} == {"Chrome": 2, "Safari": 2}
    assert {r["key"]: r["count"] for r in stats["countries"]} == {"BD": 3, "US": 1}


def test_analytics_unknown_link_404(client, auth):
    assert client.get("/api/v1/links/zzz/analytics", headers=auth).status_code == 404


def test_landing_page_and_form(client):
    home = client.get("/")
    assert home.status_code == 200
    assert "Shorten" in home.text

    created = client.post(
        "/shorten", data={"url": "https://example.com/form", "alias": "from-form"}
    )
    assert created.status_code == 200
    assert "http://sho.rt/from-form" in created.text

    bad = client.post("/shorten", data={"url": "nonsense", "alias": ""})
    assert bad.status_code == 422

    dup = client.post("/shorten", data={"url": "https://example.com/x", "alias": "from-form"})
    assert dup.status_code == 409


def test_stats_page_renders(client, make_link):
    code = make_link("https://example.com/page")["code"]
    client.get(f"/{code}", follow_redirects=False, headers={"User-Agent": CHROME_WIN})
    page = client.get(f"/{code}+")
    assert page.status_code == 200
    assert "Total clicks" in page.text
    assert "Chrome" in page.text
    assert client.get("/missing+").status_code == 404


def test_health(client):
    body = client.get("/health").json()
    assert body == {"status": "ok", "database": "ok", "cache": "ok", "version": "0.1.0"}


def test_openapi_docs_available(client):
    assert client.get("/openapi.json").status_code == 200
    assert client.get("/docs").status_code == 200


# -- service level ------------------------------------------------------------


def test_service_create_rejects_both_expiry_fields():
    import pytest

    with pytest.raises(ValueError):
        LinkCreate(
            url="https://x.com", expires_at=datetime.now(timezone.utc), expires_in_seconds=60
        )


def test_service_record_click_parses_referrer_host(app):
    from shortener.geoip import NullGeoIP

    db = app.state.session_factory()
    service = LinkService(db)
    link = service.create(LinkCreate(url="https://example.com/svc"))
    click = service.record_click(
        link.id,
        referrer="https://WWW.Facebook.com/x?y=1",
        user_agent=CHROME_WIN,
        ip="1.2.3.4",
        ip_secret="s",
        geoip=NullGeoIP(),
    )
    assert click.referrer_host == "facebook.com"
    assert click.browser == "Chrome"
    assert click.country is None
    db.refresh(link)
    assert link.click_count == 1
    db.close()
