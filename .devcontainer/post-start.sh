#!/usr/bin/env bash
# Codespaces start hook: bring up API + PostgreSQL + Redis and seed a demo short link.
set -euo pipefail
cd "$(dirname "$0")/.."

# Short URLs must point at the forwarded Codespaces address, not localhost.
if [ -n "${CODESPACE_NAME:-}" ] && [ -n "${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN:-}" ]; then
  export SHORTENER_BASE_URL="https://${CODESPACE_NAME}-8000.${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN}"
fi

docker compose up -d --build

echo "waiting for the API on :8000 ..."
for _ in $(seq 1 60); do
  if curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

KEY=${SHORTENER_API_KEY:-dev-api-key-change-me}   # docker-compose.yml default
if [ ! -f .demo-seeded ]; then
  curl -fsS -X POST http://127.0.0.1:8000/api/v1/links \
    -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
    -d '{"url":"https://shop.example.com/eid-sale?utm_source=sms","alias":"eid-sale","title":"Eid sale landing page"}' \
    >/dev/null
  date -u +%FT%TZ > .demo-seeded
fi

cat <<MSG

URL Shortener is up.
  Landing page:  forwarded port 8000, path /         (form-based shortening)
  API docs:      forwarded port 8000, path /docs     (X-API-Key: $KEY)
  Demo link:     /eid-sale redirects, /eid-sale+ shows its stats page
MSG
