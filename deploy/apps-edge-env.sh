# Sourced by deploy/compose-prod.sh and deploy/preflight-apps-edge.sh, from the
# repo folder. apps_edge_resolve sets APPS_EDGE_NETWORK, APPS_EDGE_SUBNET,
# APPS_EDGE_CADDY_IP and COMPOSE_PROJECT as compose resolves them from
# .env.production (and the shell), rather than parsing the file here: compose
# expands variables, quotes, `export` and inline comments. All three settings
# set, or none; anything in between fails, so a half-done switch-on never
# reaches Caddy.
apps_edge_resolve() {
  local resolved
  resolved="$(docker compose -f docker-compose.prod.yml -f deploy/compose.apps-edge.yml \
      --env-file .env.production config --format json \
    | python3 -c '
import json, sys
c = json.load(sys.stdin)
x = c.get("x-apps-edge", {})
print(c.get("name", ""))
for key in ("network", "subnet", "caddy_ip"):
    print((x.get(key) or "").strip())
')" || { echo "apps-edge: could not read the compose config" >&2; return 1; }
  COMPOSE_PROJECT="$(echo "$resolved" | sed -n 1p)"
  APPS_EDGE_NETWORK="$(echo "$resolved" | sed -n 2p)"
  APPS_EDGE_SUBNET="$(echo "$resolved" | sed -n 3p)"
  APPS_EDGE_CADDY_IP="$(echo "$resolved" | sed -n 4p)"
  local set=0
  for v in "$APPS_EDGE_NETWORK" "$APPS_EDGE_SUBNET" "$APPS_EDGE_CADDY_IP"; do
    [ -n "$v" ] && set=$((set + 1))
  done
  if [ "$set" -ne 0 ] && [ "$set" -ne 3 ]; then
    echo "apps-edge: set all of APPS_EDGE_NETWORK, APPS_EDGE_SUBNET and APPS_EDGE_CADDY_IP, or none" >&2
    return 1
  fi
}
