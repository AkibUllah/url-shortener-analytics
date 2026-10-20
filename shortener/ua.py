"""Small, dependency-free user-agent classifier.

Good enough for dashboard analytics (browser family, OS family, device class).
It intentionally does not try to extract versions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_BOT_RE = re.compile(
    r"bot|crawl|spider|slurp|facebookexternalhit|preview|curl|wget|python-requests", re.I
)
_TABLET_RE = re.compile(r"iPad|Tablet|Kindle|Silk|PlayBook", re.I)
_MOBILE_RE = re.compile(r"Mobile|iPhone|iPod|Android|Windows Phone|BlackBerry|Opera Mini", re.I)

# Order matters: more specific tokens first.
_BROWSERS: list[tuple[str, re.Pattern[str]]] = [
    ("Edge", re.compile(r"Edg(e|A|iOS)?/", re.I)),
    ("Opera", re.compile(r"OPR/|Opera", re.I)),
    ("Samsung Internet", re.compile(r"SamsungBrowser", re.I)),
    ("UC Browser", re.compile(r"UCBrowser", re.I)),
    ("Firefox", re.compile(r"Firefox/|FxiOS", re.I)),
    ("Chrome", re.compile(r"Chrome/|CriOS", re.I)),
    ("Safari", re.compile(r"Safari/", re.I)),
    ("Internet Explorer", re.compile(r"MSIE|Trident/", re.I)),
]

_OSES: list[tuple[str, re.Pattern[str]]] = [
    ("Windows", re.compile(r"Windows", re.I)),
    ("iOS", re.compile(r"iPhone|iPad|iPod", re.I)),
    ("Android", re.compile(r"Android", re.I)),
    ("macOS", re.compile(r"Mac OS X|Macintosh", re.I)),
    ("Chrome OS", re.compile(r"CrOS", re.I)),
    ("Linux", re.compile(r"Linux|X11", re.I)),
]


@dataclass(frozen=True)
class UAInfo:
    browser: str
    os: str
    device: str  # desktop | mobile | tablet | bot | other


def parse_user_agent(user_agent: str | None) -> UAInfo:
    if not user_agent:
        return UAInfo(browser="Unknown", os="Unknown", device="other")
    ua = user_agent.strip()

    if _BOT_RE.search(ua):
        device = "bot"
    elif _TABLET_RE.search(ua):
        device = "tablet"
    elif _MOBILE_RE.search(ua):
        device = "mobile"
    else:
        device = "desktop"

    browser = next((name for name, rx in _BROWSERS if rx.search(ua)), "Other")
    os_name = next((name for name, rx in _OSES if rx.search(ua)), "Other")
    return UAInfo(browser=browser, os=os_name, device=device)
