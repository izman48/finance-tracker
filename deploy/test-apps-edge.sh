#!/usr/bin/env bash
# Tests for the optional shared apps network (DEPLOY.md "Shared apps network"):
# deploy/compose-prod.sh, deploy/preflight-apps-edge.sh and
# deploy/compose.apps-edge.yml, against the real Docker daemon.
#   - With the APPS_EDGE_* settings unset, nothing changes: the compose config
#     is byte-identical to plain `docker compose -f docker-compose.prod.yml`,
#     and the preflight prints nothing and creates no network.
#   - With them set, Caddy joins the external network at the pinned address,
#     keeps its edge address, and is not on the project's default network.
#   - The preflight refuses, before anything is created, a subnet that
#     overlaps any Docker network, a Caddy address outside the subnet (or on
#     its gateway or dynamic range), a partial setting, and an existing network
#     that doesn't match.
# Usage: ./deploy/test-apps-edge.sh   (needs Docker; CI runs it in test.yml)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
ID="appsedge-test-$$"
NETS=()
CONTAINERS=()
cleanup() {
  [ "${#CONTAINERS[@]}" -gt 0 ] && docker rm -f "${CONTAINERS[@]}" >/dev/null 2>&1 || true
  for n in ${NETS[@]+"${NETS[@]}"}; do docker network rm "$n" >/dev/null 2>&1 || true; done
  rm -rf "$TMP"
}
trap cleanup EXIT

failures=0
pass() { echo "ok   - $1"; }
fail() { echo "FAIL - $1" >&2; failures=$((failures + 1)); }

# A copy of what deploy.sh ships, with a fake .env.production, like the server.
SERVER="$TMP/finance-tracker"
mkdir -p "$SERVER"
cp -R "$REPO_ROOT/deploy" "$SERVER/deploy" && cp "$REPO_ROOT/docker-compose.prod.yml" "$SERVER/"
BASE_ENV=$'DOMAIN=nilu.test\nPOSTGRES_USER=x\nPOSTGRES_PASSWORD=x\nSECRET_KEY=x\nENCRYPTION_KEY=x\nTRUELAYER_CLIENT_ID=\nTRUELAYER_CLIENT_SECRET=\nSITES_DIR=/srv/sites'
# Settings in the caller's shell would leak into compose's interpolation.
unset APPS_EDGE_NETWORK APPS_EDGE_SUBNET APPS_EDGE_CADDY_IP

# with_env <extra .env.production lines> — writes the server's env file.
with_env() { printf '%s\n%s\n' "$BASE_ENV" "${1:-}" > "$SERVER/.env.production"; }
# settings <network> <subnet> <caddy ip> — the three lines, as the owner writes them.
settings() { printf 'APPS_EDGE_NETWORK=%s\nAPPS_EDGE_SUBNET=%s\nAPPS_EDGE_CADDY_IP=%s' "$1" "$2" "$3"; }
plain_config() { (cd "$SERVER" && docker compose -f docker-compose.prod.yml --env-file .env.production config "$@"); }
wrapped_config() { (cd "$SERVER" && ./deploy/compose-prod.sh config "$@"); }
preflight() { (cd "$SERVER" && ./deploy/preflight-apps-edge.sh) > "$TMP/out" 2>&1; }
net_count() { docker network ls -q | wc -l | tr -d ' '; }
exists() { docker network inspect "$1" >/dev/null 2>&1; }

# --- Unset: a no-op ------------------------------------------------------------

with_env ""
if [ "$(plain_config)" = "$(wrapped_config)" ] && [ -n "$(plain_config)" ]; then
  pass "unset: compose config is byte-identical to plain docker-compose.prod.yml"
else
  fail "unset: compose config differs: $(diff <(plain_config) <(wrapped_config) || true)"
fi
[ "$(plain_config --format json)" = "$(wrapped_config --format json)" ] \
  && pass "unset: JSON config identical too" || fail "unset: JSON config differs"
before="$(net_count)"
if preflight; then pass "unset: preflight exits 0"; else fail "unset: preflight failed: $(cat "$TMP/out")"; fi
[ -s "$TMP/out" ] && fail "unset: preflight printed: $(cat "$TMP/out")" || pass "unset: preflight prints nothing"
[ "$(net_count)" = "$before" ] && pass "unset: no network created" || fail "unset: network count changed"
with_env "APPS_EDGE_NETWORK="
preflight && pass "set to empty: treated as unset" || fail "empty value refused: $(cat "$TMP/out")"

# --- Partial settings are refused -----------------------------------------------

for partial in "APPS_EDGE_NETWORK=$ID-a" "APPS_EDGE_SUBNET=10.213.0.0/24" \
  $'APPS_EDGE_NETWORK='"$ID-a"$'\nAPPS_EDGE_SUBNET=10.213.0.0/24'; do
  with_env "$partial"
  preflight && fail "partial settings accepted: $(echo "$partial" | tr '\n' ' ')" \
    || pass "partial settings refused: $(echo "$partial" | tr '\n' ' ')"
  wrapped_config >/dev/null 2>&1 && fail "compose-prod.sh ran with partial settings" \
    || pass "compose-prod.sh refuses partial settings"
done
exists "$ID-a" && fail "a partial setting created a network" || pass "partial settings created no network"

# --- Set: Caddy joins at the pinned address -------------------------------------

NET="$ID-net"
with_env "$(settings "$NET" 10.213.0.0/24 10.213.0.10)"
json="$(wrapped_config --format json)" || fail "compose-prod.sh config failed with settings"
got="$(echo "$json" | python3 -c '
import json, sys
c = json.load(sys.stdin)
caddy = c["services"]["caddy"]["networks"]
net = c["networks"]["apps_edge"]
print(sorted(caddy), caddy["apps_edge"]["ipv4_address"], caddy["edge"]["ipv4_address"], net["name"], net["external"])')"
[ "$got" = "['apps_edge', 'edge'] 10.213.0.10 172.30.250.10 $NET True" ] \
  && pass "set: caddy on edge (172.30.250.10) and the external network at the pinned address, not on default" \
  || fail "set: caddy networks: $got"
others() { python3 -c '
import json, sys
c = json.load(sys.stdin)
print(json.dumps({k: v for k, v in c["services"].items() if k != "caddy"}, sort_keys=True))'; }
[ "$(echo "$json" | others)" = "$(plain_config --format json | others)" ] \
  && pass "set: db, api and mcp are unchanged (none joins the shared network)" \
  || fail "set: another service changed"

# --- Set: preflight refusals (nothing is created) ------------------------------

refused() { # <description> <settings...>
  local desc="$1"; shift
  with_env "$(settings "$@")"
  if preflight; then fail "$desc: accepted"; else pass "$desc: refused"; fi
  exists "$1" && { fail "$desc: network $1 was created"; docker network rm "$1" >/dev/null; } || true
}
OCCUPIED="$ID-occupied"
docker network create --subnet 10.214.0.0/24 "$OCCUPIED" >/dev/null && NETS+=("$OCCUPIED")
refused "subnet equal to an existing network's"       "$NET" 10.214.0.0/24 10.214.0.10
refused "subnet containing an existing network"       "$NET" 10.214.0.0/16 10.214.200.10
refused "subnet inside an existing network"           "$NET" 10.214.0.128/25 10.214.0.130
grep -q "$OCCUPIED" "$TMP/out" && pass "overlap message names the clashing network" \
  || fail "overlap message: $(cat "$TMP/out")"
refused "Caddy address outside the subnet"            "$NET" 10.213.0.0/24 10.213.1.10
refused "Caddy address on the network address"        "$NET" 10.213.0.0/24 10.213.0.0
refused "Caddy address on the gateway"                "$NET" 10.213.0.0/24 10.213.0.1
refused "Caddy address in the dynamic range"          "$NET" 10.213.0.0/24 10.213.0.200
refused "Caddy address on the broadcast address"      "$NET" 10.213.0.0/24 10.213.0.255
refused "not a subnet"                                "$NET" not-a-subnet 10.213.0.10
refused "subnet with host bits set"                   "$NET" 10.213.0.5/24 10.213.0.10
refused "IPv6 subnet"                                 "$NET" fd00::/64 fd00::10
refused "subnet too small"                            "$NET" 10.213.0.0/30 10.213.0.2
refused "network name with shell characters"         "x;id" 10.213.0.0/24 10.213.0.10

# --- Set: creates the network, then accepts it unchanged ---------------------------

NETS+=("$NET")
with_env "$(settings "$NET" 10.213.0.0/24 10.213.0.10)"
if preflight; then pass "valid settings: preflight exits 0"; else fail "valid settings refused: $(cat "$TMP/out")"; fi
got="$(docker network inspect "$NET" --format '{{.Driver}} {{range .IPAM.Config}}{{.Subnet}} {{.IPRange}} {{.Gateway}}{{end}}' 2>&1)"
[ "$got" = "bridge 10.213.0.0/24 10.213.0.128/25 10.213.0.1" ] \
  && pass "creates the network: bridge, the subnet, dynamic addresses in the upper half" \
  || fail "created network: $got"
preflight && pass "second run accepts the existing network" || fail "second run refused: $(cat "$TMP/out")"

# Something else already holds Caddy's address on the network: recreating Caddy
# would fail and leave the site down, so refuse before `up`.
squatter="$ID-squatter" && CONTAINERS+=("$squatter")
docker run -d --name "$squatter" --network "$NET" --ip 10.213.0.10 busybox:1.37 sleep 300 >/dev/null
preflight && fail "accepted a Caddy address held by another container" \
  || pass "refuses a Caddy address held by another container"
docker rm -f "$squatter" >/dev/null

with_env "$(settings "$NET" 10.215.0.0/24 10.215.0.10)"
preflight && fail "accepted an existing network with a different subnet" \
  || pass "refuses an existing network with a different subnet"
got="$(docker network inspect "$NET" --format '{{range .IPAM.Config}}{{.Subnet}}{{end}}')"
[ "$got" = 10.213.0.0/24 ] && pass "the existing network is left as it was" || fail "existing network changed: $got"
# A compose project's own network (e.g. nilu's edge or default) is never the shared one.
PROJECT_NET="$ID-project"
docker network create --subnet 10.216.0.0/24 --label com.docker.compose.project=other "$PROJECT_NET" >/dev/null \
  && NETS+=("$PROJECT_NET")
with_env "$(settings "$PROJECT_NET" 10.216.0.0/24 10.216.0.10)"
preflight && fail "accepted a compose project's network" || pass "refuses a compose project's network"

if [ "$failures" -gt 0 ]; then
  echo "$failures apps-edge check(s) failed" >&2
  exit 1
fi
echo "All apps-edge checks passed"
