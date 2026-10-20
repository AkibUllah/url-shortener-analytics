import pytest

from shortener.geoip import NullGeoIP, StaticGeoIP
from shortener.ua import parse_user_agent

CHROME_WIN = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
SAFARI_IPHONE = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1"
)
CHROME_ANDROID = (
    "Mozilla/5.0 (Linux; Android 13; SM-A546E) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/123.0.0.0 Mobile Safari/537.36"
)
FIREFOX_LINUX = "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0"
EDGE_MAC = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0"
)
IPAD = (
    "Mozilla/5.0 (iPad; CPU OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/16.6 Mobile/15E148 Safari/604.1"
)
GOOGLEBOT = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"


@pytest.mark.parametrize(
    ("ua", "browser", "os", "device"),
    [
        (CHROME_WIN, "Chrome", "Windows", "desktop"),
        (SAFARI_IPHONE, "Safari", "iOS", "mobile"),
        (CHROME_ANDROID, "Chrome", "Android", "mobile"),
        (FIREFOX_LINUX, "Firefox", "Linux", "desktop"),
        (EDGE_MAC, "Edge", "macOS", "desktop"),
        (IPAD, "Safari", "iOS", "tablet"),
        (GOOGLEBOT, "Other", "Other", "bot"),
        ("curl/8.5.0", "Other", "Other", "bot"),
    ],
)
def test_parse_user_agent(ua, browser, os, device):
    info = parse_user_agent(ua)
    assert (info.browser, info.os, info.device) == (browser, os, device)


def test_parse_empty_user_agent():
    info = parse_user_agent(None)
    assert info.device == "other"
    assert info.browser == "Unknown"


def test_static_geoip_resolves_known_prefix():
    geo = StaticGeoIP()
    assert geo.country("103.108.141.17") == "BD"
    assert geo.country("8.8.8.8") == "US"


def test_static_geoip_ignores_private_and_invalid():
    geo = StaticGeoIP()
    assert geo.country("127.0.0.1") is None
    assert geo.country("10.0.0.5") is None
    assert geo.country("not-an-ip") is None
    assert geo.country(None) is None


def test_null_geoip():
    assert NullGeoIP().country("8.8.8.8") is None
