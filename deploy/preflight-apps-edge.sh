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

# One line per Docker network: name, compose project, marker label, driver,
# internal, then subnet/gateway/range triples. The built-in networks always
# exist, so the id list is never empty.
networks="$(docker network ls -q | xargs docker network inspect --format \
  '{{.Name}}|{{index .Labels "com.docker.compose.project"}}|{{index .Labels "'"$MARKER_KEY"'"}}|{{.Driver}}|{{.Internal}}|{{range .IPAM.Config}}{{.Subnet}},{{.Gateway}},{{.IPRange}} {{end}}')"
# Holders of each address on the network, if it exists: "<ip> <container id>".
holders=""
if docker network inspect "$APPS_EDGE_NETWORK" >/dev/null 2>&1; then
  holders="$(docker network inspect "$APPS_EDGE_NETWORK" --format \
    '{{range $id, $c := .Containers}}{{$c.IPv4Address}} {{$id}}{{"\n"}}{{end}}')"
fi
routes="$(ip -4 route show | awk '$1 != "default" { print $1 }')"

plan="$(MARKER="$MARKER_KEY=$MARKER_VALUE" NETWORK="$APPS_EDGE_NETWORK" SUBNET="$APPS_EDGE_SUBNET" CADDY_IP="$APPS_EDGE_CADDY_IP" \
  NETWORKS="$networks" HOLDERS="$holders" ROUTES="$routes" python3 -c '
import ipaddress, os, sys

def refuse(msg):
    print("preflight-apps-edge: " + msg, file=sys.stderr)
    sys.exit(1)

name, subnet_s, ip_s = os.environ["NETWORK"], os.environ["SUBNET"], os.environ["CADDY_IP"]
marker = os.environ["MARKER"]
try:
    subnet = ipaddress.IPv4Network(subnet_s, strict=True)
except ValueError:
    refuse(f"APPS_EDGE_SUBNET {subnet_s!r} is not an IPv4 subnet like 172.31.250.0/24")
if not 16 <= subnet.prefixlen <= 28:
    refuse(f"APPS_EDGE_SUBNET {subnet} must be between /16 and /28")
try:
    ip = ipaddress.IPv4Address(ip_s)
except ValueError:
    refuse(f"APPS_EDGE_CADDY_IP {ip_s!r} is not an IPv4 address")

existing, others = None, []
for line in os.environ["NETWORKS"].splitlines():
    net_name, project, label, driver, internal, configs = line.split("|", 5)
    pools = []
    for triple in configs.split():
        sub, gw, rng = triple.split(",")
        try:
            pools.append((ipaddress.ip_network(sub), gw, rng))
        except ValueError:
            continue
    if net_name == name:
        existing = (project, label, driver, internal, pools)
    else:
        others.extend((net_name, p[0]) for p in pools)

for other, other_subnet in others:
    if other_subnet.version == 4 and subnet.overlaps(other_subnet):
        refuse(f"APPS_EDGE_SUBNET {subnet} overlaps Docker network {other} ({other_subnet}); pick a free range")
docker_subnets = {str(s) for _, s in others}
for route in os.environ["ROUTES"].split():
    try:
        dest = ipaddress.ip_network(route, strict=False)
    except ValueError:
        continue
    if str(dest) not in docker_subnets and str(dest) != str(subnet) and subnet.overlaps(dest):
        refuse(f"APPS_EDGE_SUBNET {subnet} overlaps the host route {dest}; pick a free range")

# New networks get the first host as gateway and hand out dynamic addresses
# from the upper half only, so the lower half is free for pinned addresses.
gateway, dyn_range = subnet.network_address + 1, list(subnet.subnets(prefixlen_diff=1))[1]
if existing is not None:
    project, label, driver, internal, pools = existing
    if project:
        refuse(f"network {name} belongs to compose project {project}; use a network of its own")
    if label != marker.split("=", 1)[1]:
        refuse(f"network {name} exists but was not created by this preflight (no {marker} label); "
               "pick another name, or remove it so the preflight can create it")
    if driver != "bridge":
        refuse(f"network {name} uses the {driver} driver, not bridge")
    if internal != "true":
        refuse(f"network {name} is not internal; remove it so the preflight can recreate it")
    if [str(p[0]) for p in pools] != [str(subnet)]:
        refuse(f"network {name} exists with subnet(s) {[str(p[0]) for p in pools]}, not {subnet}")
    gateway = ipaddress.IPv4Address(pools[0][1]) if pools[0][1] else None
    dyn_range = ipaddress.IPv4Network(pools[0][2]) if pools[0][2] else None

if ip not in subnet or ip in (subnet.network_address, subnet.broadcast_address):
    refuse(f"APPS_EDGE_CADDY_IP {ip} is not a usable address in {subnet}")
if ip == gateway:
    refuse(f"APPS_EDGE_CADDY_IP {ip} is the network gateway")
if dyn_range is not None and ip in dyn_range:
    refuse(f"APPS_EDGE_CADDY_IP {ip} is in the dynamic range {dyn_range}; pick one below it")
for line in os.environ["HOLDERS"].splitlines():
    fields = line.split()
    if not fields:
        continue
    if len(fields) != 2:
        refuse(f"container {fields[-1]} on network {name} has no IPv4 address; "
               "can not tell whether it holds the Caddy address")
    held, container = fields
    try:
        held_ip = ipaddress.ip_interface(held).ip
    except ValueError:
        refuse(f"container {container} on network {name} has an unreadable address {held!r}")
    if held_ip == ip:
        print(f"held {container}")

print("exists" if existing is not None else f"create {gateway} {dyn_range}")
')"

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
