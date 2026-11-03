#!/usr/bin/env bash
# Pre-deploy check for the optional shared apps network (DEPLOY.md "Shared
# apps network"). Runs ON THE SERVER from the repo folder; deploy.sh calls it
# before `up`. With the APPS_EDGE_* settings unset it does nothing and prints
# nothing. With them set it makes sure the network exists, creating it if
# needed, and refuses (exit non-zero, before Caddy is touched) anything that
# would stop the new Caddy starting and take the site down with it:
#   - a subnet that overlaps any Docker network or a host route,
#   - a Caddy address outside the subnet, or on its network, gateway or
#     broadcast address, or in the range Docker hands out to other containers,
#   - an existing network of that name that this preflight didn't create:
#     no marker label (Docker's own bridge, a hand-made or compose-owned
#     network), not a bridge, not internal, or another subnet,
#   - Caddy's address already held by another container,
#   - a host without `ip`, where the host-route check can't run.
# The network it creates is internal: no gateway out, so the other app has no
# internet through it, and Caddy's default route (ACME, egress) stays on edge.
set -euo pipefail

cd "$(dirname "$0")/.."
. deploy/apps-edge-env.sh
apps_edge_resolve
[ -n "$APPS_EDGE_NETWORK" ] || exit 0

refuse() { echo "preflight-apps-edge: $1" >&2; exit 1; }
# Before any docker command sees it: a leading - would be read as a flag.
[[ "$APPS_EDGE_NETWORK" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]{0,62}$ ]] \
  || refuse "APPS_EDGE_NETWORK '$APPS_EDGE_NETWORK' is not a valid network name"
command -v ip >/dev/null 2>&1 \
  || refuse "the ip command is missing, so the subnet can't be checked against host routes; install iproute2"
# Marks the network as made by this preflight; nothing else is ever accepted.
MARKER_KEY=apps-edge.managed-by MARKER_VALUE=preflight-apps-edge

# Every Docker network as `docker network inspect` JSON, not a --format
# template: Docker 29 prints unset addresses in templates as `invalid Prefix`
# (see deploy/apps_edge_plan.py). The built-in networks always exist, so the
# id list is never empty.
networks="$(docker network ls -q | xargs docker network inspect)"
routes="$(ip -4 route show | awk '$1 != "default" { print $1 }')"

plan="$(MARKER="$MARKER_KEY=$MARKER_VALUE" NETWORK="$APPS_EDGE_NETWORK" SUBNET="$APPS_EDGE_SUBNET" CADDY_IP="$APPS_EDGE_CADDY_IP" \
  ROUTES="$routes" python3 -I deploy/apps_edge_plan.py <<<"$networks")"

# Caddy's address may already be held, but only by this stack's own Caddy.
while read -r word container; do
  [ "$word" = held ] || continue
  service="$(docker inspect "$container" --format \
    '{{index .Config.Labels "com.docker.compose.project"}}/{{index .Config.Labels "com.docker.compose.service"}}')"
  if [ "$service" != "$COMPOSE_PROJECT/caddy" ]; then
    echo "preflight-apps-edge: $APPS_EDGE_CADDY_IP on $APPS_EDGE_NETWORK is held by another container ($service); Caddy could not start" >&2
    exit 1
  fi
done <<<"$plan"

action="$(echo "$plan" | tail -n 1)"
case "$action" in
  exists) echo "preflight-apps-edge ok: $APPS_EDGE_NETWORK" ;;
  create\ *)
    read -r _ gateway ip_range <<<"$action"
    docker network create --driver bridge --internal --label "$MARKER_KEY=$MARKER_VALUE" \
      --subnet "$APPS_EDGE_SUBNET" --gateway "$gateway" --ip-range "$ip_range" \
      "$APPS_EDGE_NETWORK" >/dev/null
    echo "preflight-apps-edge ok: created $APPS_EDGE_NETWORK ($APPS_EDGE_SUBNET, internal)" ;;
  *) echo "preflight-apps-edge: unexpected plan '$action'" >&2; exit 1 ;;
esac
