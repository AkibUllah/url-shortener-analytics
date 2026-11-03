from __future__ import annotations

import pytest

IMPORT_URL = "/api/v1/links/import"


def upload(client, auth, body: bytes, **params):
    files = {"file": ("links.csv", body, "text/csv")}
    return client.post(IMPORT_URL, files=files, headers=auth, params=params)


def test_import_requires_api_key(client) -> None:
    response = client.post(IMPORT_URL, files={"file": ("l.csv", b"url\n", "text/csv")})
    assert response.status_code == 401


def test_import_reports_each_row_and_creates_only_valid_ones(client, auth, make_link) -> None:
    make_link(alias="eid-sale")
    body = (
        b"url,alias,title,channel\n"
        b"https://shop.example/sms,eid-sms,SMS,sms\n"
        b"https://shop.example/fb,eid-sale,,facebook\n"
        b"javascript:alert(1),,,\n"
        b"https://shop.example/qr,,Counter QR,print\n"
    )
    response = upload(client, auth, body)
    assert response.status_code == 200, response.text
    report = response.json()
    assert report["dry_run"] is False
    assert (report["total"], report["succeeded"], report["failed"]) == (4, 2, 2)
    assert report["ignored_columns"] == ["channel"]
    rows = report["rows"]
    assert rows[0] == {
        "row": 1,
        "status": "created",
        "code": "eid-sms",
        "short_url": "http://sho.rt/eid-sms",
        "error": None,
    }
    assert rows[1]["status"] == "alias_taken"
    assert rows[1]["short_url"] is None
    assert rows[2]["status"] == "invalid"
    assert rows[3]["status"] == "created"
    assert rows[3]["short_url"] == "http://sho.rt/" + rows[3]["code"]

    assert client.get("/eid-sms", follow_redirects=False).headers["location"] == (
        "https://shop.example/sms"
    )
    assert client.get("/api/v1/links", headers=auth).json()["total"] == 3


def test_import_dry_run_creates_nothing(client, auth) -> None:
    response = upload(client, auth, b"url,alias\nhttps://shop.example,promo\n", dry_run="true")
    assert response.status_code == 200
    report = response.json()
    assert report["dry_run"] is True
    assert report["rows"][0]["status"] == "valid"
    assert report["rows"][0]["short_url"] == "http://sho.rt/promo"
    assert client.get("/api/v1/links/promo", headers=auth).status_code == 404


@pytest.mark.parametrize(
    ("body", "detail"),
    [
        (b"alias\nx\n", "'url' column"),
        (b"url\n\xff\xfe\n", "UTF-8"),
    ],
)
def test_unreadable_files_are_rejected_with_422(client, auth, body: bytes, detail: str) -> None:
    response = upload(client, auth, body)
    assert response.status_code == 422
    assert detail in response.json()["detail"]


def test_row_and_size_limits_return_413(client, auth, settings) -> None:
    settings.import_max_rows = 2
    rows = b"url\n" + b"https://shop.example/x\n" * 3
    response = upload(client, auth, rows)
    assert response.status_code == 413
    assert "more than 2 rows" in response.json()["detail"]

    settings.import_max_bytes = 1024
    response = upload(client, auth, b"url\n" + b"https://shop.example/" + b"a" * 1100 + b"\n")
    assert response.status_code == 413
    assert "larger than 1024 bytes" in response.json()["detail"]
    assert client.get("/api/v1/links", headers=auth).json()["total"] == 0


def test_import_is_listed_in_openapi(client) -> None:
    spec = client.get("/openapi.json").json()
    assert "post" in spec["paths"][IMPORT_URL]


def read_export(client, auth) -> list[dict[str, str]]:
    import csv
    import io

    response = client.get("/api/v1/links/export.csv", headers=auth)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "text/csv; charset=utf-8"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["content-disposition"].startswith('attachment; filename="links-')
    assert response.content.startswith(b"\xef\xbb\xbf")
    return list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))


def test_export_requires_api_key(client) -> None:
    assert client.get("/api/v1/links/export.csv").status_code == 401


def test_export_lists_links_with_click_totals(client, auth, make_link) -> None:
    sale = make_link("https://shop.example/eid", alias="eid-sale", title="ঈদ অফার")
    plain = make_link("https://shop.example/plain", expires_at="2030-01-01T00:00:00Z")
    make_link("https://shop.example/locked", alias="locked", password="hunter22")
    for _ in range(3):
        client.get("/eid-sale", follow_redirects=False)
    client.delete("/api/v1/links/locked", headers=auth)

    rows = read_export(client, auth)
    assert list(rows[0]) == [
        "url",
        "alias",
        "title",
        "expires_at",
        "short_url",
        "is_custom",
        "is_active",
        "is_password_protected",
        "created_at",
        "total_clicks",
        "last_click_at",
    ]
    assert [r["alias"] for r in rows] == ["eid-sale", plain["code"], "locked"]
    first, second, third = rows
    assert first["title"] == "ঈদ অফার"
    assert first["short_url"] == sale["short_url"]
    assert (first["is_custom"], first["total_clicks"]) == ("true", "3")
    assert first["last_click_at"].endswith("Z")
    assert (second["is_custom"], second["total_clicks"], second["last_click_at"]) == (
        "false",
        "0",
        "",
    )
    assert second["expires_at"] == "2030-01-01T00:00:00Z"
    assert (third["is_active"], third["is_password_protected"]) == ("false", "true")
    assert "hunter22" not in str(rows) and "pbkdf2" not in str(rows)


def test_export_neutralises_spreadsheet_formulas(client, auth, make_link) -> None:
    make_link(title='=HYPERLINK("http://evil.example","win")')
    make_link(title="-10% Eid deal")
    titles = [r["title"] for r in read_export(client, auth)]
    assert titles == ['\'=HYPERLINK("http://evil.example","win")', "'-10% Eid deal"]


def test_export_can_be_imported_elsewhere(client, auth, make_link, app, settings) -> None:
    from fastapi.testclient import TestClient

    from shortener.geoip import StaticGeoIP
    from shortener.main import create_app

    make_link("https://shop.example/a", alias="promo-a", title="Promo A")
    make_link("https://shop.example/b")
    exported = client.get("/api/v1/links/export.csv", headers=auth).content

    other = create_app(settings=settings.model_copy(), geoip=StaticGeoIP())
    with TestClient(other, base_url="http://sho.rt") as second:
        report = upload(second, auth, exported).json()
        assert (report["succeeded"], report["failed"]) == (2, 0)
        assert "total_clicks" in report["ignored_columns"]
        copied = second.get("/api/v1/links/promo-a", headers=auth).json()
        assert (copied["target_url"], copied["title"]) == ("https://shop.example/a", "Promo A")
