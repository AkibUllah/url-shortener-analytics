from __future__ import annotations

import pytest

from shortener.config import Settings


@pytest.mark.parametrize(
    "given",
    [
        "postgres://shortener:secret@db.render.internal:5432/shortener",
        "postgresql://shortener:secret@db.render.internal:5432/shortener",
    ],
)
def test_managed_postgres_urls_are_rewritten_to_psycopg3(given: str) -> None:
    settings = Settings(_env_file=None, database_url=given)
    assert (
        settings.database_url
        == "postgresql+psycopg://shortener:secret@db.render.internal:5432/shortener"
    )


@pytest.mark.parametrize(
    "given",
    [
        "sqlite:///:memory:",
        "sqlite:///./shortener.db",
        "postgresql+psycopg://shortener:shortener@db:5432/shortener",
    ],
)
def test_explicit_driver_urls_are_left_alone(given: str) -> None:
    assert Settings(_env_file=None, database_url=given).database_url == given


def test_base_url_falls_back_to_render_external_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SHORTENER_BASE_URL", raising=False)
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://short.onrender.com")
    assert Settings(_env_file=None).short_url_prefix == "https://short.onrender.com/"


def test_explicit_base_url_wins_over_render_external_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://short.onrender.com")
    monkeypatch.setenv("SHORTENER_BASE_URL", "https://sho.rt")
    assert Settings(_env_file=None).base_url == "https://sho.rt"
    assert Settings(_env_file=None, base_url="http://kw.example").base_url == "http://kw.example"
