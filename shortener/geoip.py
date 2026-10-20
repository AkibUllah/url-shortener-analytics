"""Country lookup for click events.

The real deployment would plug in MaxMind GeoLite2 (``geoip2`` package) here.
This module ships a ``StaticGeoIP`` stub that resolves a handful of well-known
prefixes so the analytics pipeline can be exercised end-to-end without a
licensed database, and a ``NullGeoIP`` that disables the feature.
"""

from __future__ import annotations

import ipaddress
from typing import Protocol


class GeoIPResolver(Protocol):
    def country(self, ip: str | None) -> str | None: ...


class NullGeoIP:
    def country(self, ip: str | None) -> str | None:
        return None


class StaticGeoIP:
    """Stub resolver: maps CIDR prefixes to ISO-3166 alpha-2 country codes."""

    DEFAULT_TABLE: dict[str, str] = {
        # Sample public ranges (illustrative only, not authoritative).
        "103.108.140.0/22": "BD",  # Dhaka
        "114.130.0.0/16": "BD",
        "27.147.0.0/16": "BD",
        "8.8.8.0/24": "US",
        "1.1.1.0/24": "AU",
        "81.2.69.0/24": "GB",
        "49.36.0.0/14": "IN",
    }

    def __init__(self, table: dict[str, str] | None = None) -> None:
        source = table if table is not None else self.DEFAULT_TABLE
        self._networks = [(ipaddress.ip_network(cidr), cc) for cidr, cc in source.items()]
        # Longest prefix first so overlapping ranges resolve most-specifically.
        self._networks.sort(key=lambda item: item[0].prefixlen, reverse=True)

    def country(self, ip: str | None) -> str | None:
        if not ip:
            return None
        try:
            address = ipaddress.ip_address(ip)
        except ValueError:
            return None
        if address.is_private or address.is_loopback:
            return None
        for network, cc in self._networks:
            if address in network:
                return cc
        return None


def build_geoip(enabled: bool) -> GeoIPResolver:
    return StaticGeoIP() if enabled else NullGeoIP()
