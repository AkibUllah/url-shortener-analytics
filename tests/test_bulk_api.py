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
