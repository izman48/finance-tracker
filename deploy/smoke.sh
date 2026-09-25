#!/usr/bin/env bash
# Post-deploy smoke check. Runs ON THE SERVER (deploy.sh calls it over ssh)
# and goes through Caddy, so it covers TLS, routing and the containers.
# Pinning the domain to 127.0.0.1 avoids depending on hairpin NAT.
set -euo pipefail

DOMAIN="$(sed -n 's/^DOMAIN=//p' .env.production | tr -d "\"' ")"
[ -n "$DOMAIN" ] || { echo "smoke: DOMAIN missing from .env.production" >&2; exit 1; }
BASE="https://$DOMAIN"

status() { curl -s -o /dev/null -w '%{http_code}' --max-time 10 --resolve "$DOMAIN:443:127.0.0.1" "$@"; }

# expect <code> <description> <curl args...> — retries while the stack boots.
expect() {
  local want="$1" what="$2" got=""; shift 2
  for _ in $(seq 1 30); do
    got="$(status "$@" || true)"
    [ "$got" = "$want" ] && { echo "smoke ok: $what ($got)"; return 0; }
    sleep 2
  done
  echo "smoke FAILED: $what — expected $want, got $got" >&2
  return 1
}

expect 200 "API health"               "$BASE/api/v1/health"
expect 200 "MCP resource metadata"    "$BASE/.well-known/oauth-protected-resource/mcp"
# Unauthenticated MCP calls must be refused (fail closed), not served.
expect 401 "MCP refuses without token" -X POST -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' "$BASE/mcp"
