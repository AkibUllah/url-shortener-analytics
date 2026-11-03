from __future__ import annotations

import pytest

from shortener.bulk import (
    ALIAS_TAKEN,
    CREATED,
    INVALID,
    VALID,
    CsvImportError,
    import_links,
    parse_import_csv,
)
from shortener.db import Base, make_engine, make_session_factory
from shortener.schemas import LinkCreate
from shortener.services import LinkService


@pytest.fixture
def service():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = make_session_factory(engine)()
    try:
        yield LinkService(db)
    finally:
        db.close()


def test_parse_strips_bom_blank_lines_and_empty_cells() -> None:
    data = (
        "﻿URL, Alias ,title,expires_at\r\n"
        "https://a.example,promo-a,,\r\n"
        ",,,\r\n"
        "\r\n"
        "https://example.com/b\r\n"
    ).encode()
    parsed = parse_import_csv(data, max_rows=10)
    assert parsed.ignored_columns == []
    assert parsed.rows == [
        (1, {"url": "https://a.example", "alias": "promo-a", "title": None, "expires_at": None}),
        (2, {"url": "https://example.com/b", "alias": None, "title": None, "expires_at": None}),
    ]


def test_parse_reports_unknown_columns_and_drops_them() -> None:
    parsed = parse_import_csv(b"url,password,channel\nhttps://example.com,secret,sms\n", 10)
    assert parsed.ignored_columns == ["password", "channel"]
    assert parsed.rows == [(1, {"url": "https://example.com"})]


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (b"", "empty"),
        (b"alias,title\nx,y\n", "'url' column"),
        (b"url,URL\nhttps://a.example,https://b.example\n", "duplicate columns: url"),
        ("url\nhttps://example.com/café\n".encode("latin-1"), "UTF-8"),
    ],
)
def test_parse_rejects_unusable_files(data: bytes, message: str) -> None:
    with pytest.raises(CsvImportError, match=message):
        parse_import_csv(data, max_rows=10)


def test_parse_enforces_row_limit_after_skipping_blank_lines() -> None:
    ok = b"url\nhttps://a.example\n\nhttps://b.example\n"
    assert len(parse_import_csv(ok, max_rows=2).rows) == 2
    with pytest.raises(CsvImportError, match="more than 2 rows") as info:
        parse_import_csv(ok + b"https://c.example\n", max_rows=2)
    assert info.value.too_large


def test_mixed_file_creates_valid_rows_and_reports_the_rest(service: LinkService) -> None:
    service.create(LinkCreate(url="https://example.com/old", alias="eid-sale"))
    data = (
        b"url,alias,title,expires_at\n"
        b"https://example.com/sms,eid-sms,SMS batch,2030-01-01T00:00:00Z\n"
        b"not a url,,,\n"
        b"https://example.com/fb,eid-sale,,\n"
        b"https://example.com/ig,,Instagram,\n"
        b"https://example.com/again,eid-sms,,\n"
        b"https://example.com/api,api,,\n"
        b"ftp://example.com/file,,,\n"
        b"https://example.com/when,,,next tuesday\n"
    )
    result = import_links(service, parse_import_csv(data, 100))

    statuses = [(r.row, r.status) for r in result.rows]
    assert statuses == [
        (1, CREATED),
        (2, INVALID),
        (3, ALIAS_TAKEN),
        (4, CREATED),
        (5, ALIAS_TAKEN),
        (6, INVALID),
        (7, INVALID),
        (8, INVALID),
    ]
    assert (result.succeeded, result.failed) == (2, 6)
    assert result.rows[0].code == "eid-sms"
    assert result.rows[2].error == "alias 'eid-sale' is already taken"
    assert result.rows[4].error == "alias 'eid-sms' is already used by row 1"
    assert result.rows[5].error.startswith("alias: ")
    assert "reserved" in result.rows[5].error
    assert result.rows[1].error.startswith("url: ")
    assert result.rows[7].error.startswith("expires_at: ")

    created = service.get_by_code("eid-sms")
    assert created.title == "SMS batch"
    assert created.expires_at.year == 2030
    generated = service.get_by_code(result.rows[3].code)
    assert generated.target_url == "https://example.com/ig"
    assert not generated.is_custom
    assert service.list(limit=100, offset=0)[1] == 3  # eid-sale + two imported


def test_dry_run_validates_without_creating(service: LinkService) -> None:
    service.create(LinkCreate(url="https://example.com/old", alias="taken"))
    data = b"url,alias\nhttps://example.com/a,fresh\nhttps://example.com/b,taken\nbad,\n"
    result = import_links(service, parse_import_csv(data, 10), dry_run=True)

    assert [(r.status, r.code) for r in result.rows] == [
        (VALID, "fresh"),
        (ALIAS_TAKEN, "taken"),
        (INVALID, None),
    ]
    assert result.dry_run
    assert service.get_by_code("fresh") is None
    assert service.list(limit=10, offset=0)[1] == 1
