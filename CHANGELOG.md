# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- CodeQL code scanning workflow and Dependabot configuration (pip, Docker, GitHub Actions).
- API reference and terminal screenshots in the README.
- Roadmap tracked as GitHub issues under the `v0.2.0` milestone.

### Changed

- CI workflow runs with a read-only `GITHUB_TOKEN` by default.

### Fixed

- Redirects served from the cache validate the cached entry (well-formed JSON, http/https target) and fall back to the database otherwise, instead of failing on a corrupt entry or trusting whatever the shared cache returns.

## [0.1.0] - 2026-10-25

First public release.

### Added

- Base62 short codes from the DB sequence through a bijective permutation; custom aliases with reserved-word checks and collision retry.
- 302 redirects served from Redis (or an in-process cache) with TTL clamped to link expiry.
- Link expiry (`410 Gone`) and soft delete (`404`).
- Password-protected links (PBKDF2) with a server-rendered unlock form.
- QR code PNG for every link.
- Background click tracking: referrer host, browser/OS/device, pluggable GeoIP country, keyed IP hash for unique visitors.
- Analytics endpoint with zero-filled clicks by day and top referrers, browsers, operating systems, devices and countries.
- Fixed-window rate limiting per client IP shared across replicas through Redis.
- Static API key on management endpoints; landing page and public stats page at `/<code>+`.
- Docker image, docker compose with PostgreSQL and Redis, CI on Python 3.10/3.11, Pages API reference, Codespaces and Render kits.

### Fixed

- Deploy-friendly settings for managed hosting (`RENDER_EXTERNAL_URL`, `postgres://` URLs).

[Unreleased]: https://github.com/AkibUllah/url-shortener-analytics/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/AkibUllah/url-shortener-analytics/releases/tag/v0.1.0
