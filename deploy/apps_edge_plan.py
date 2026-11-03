"""Decides what deploy/preflight-apps-edge.sh does (DEPLOY.md "Shared apps
network"). Reads `docker network inspect` JSON for every network on stdin and
the settings and host routes from the environment; prints `held <container>`
for each container holding Caddy's address, then `exists` or
`create <gateway> <ip range>`; or refuses with exit 1 and a message.

It reads Docker's JSON, not a --format template: templates print an unset
address with Go's String(), which changed across Docker versions (Docker 29
prints an unset IPRange as `invalid Prefix`, with a space), while the JSON
leaves it out or empty. Values that are absent, empty or `invalid ...` all mean
"not set"; anything else that doesn't parse is refused rather than ignored.
"""
import ipaddress
import json
import os
import sys


class Refusal(Exception):
    pass


def _unset(value):
    return value is None or value == "" or (isinstance(value, str) and value.startswith("invalid"))


def _parse(kind, value, where):
    """None when unset; the parsed value; Refusal when unreadable."""
    if _unset(value):
        return None
    parse = {"network": ipaddress.ip_network, "address": ipaddress.ip_address,
             "interface": ipaddress.ip_interface}[kind]
    try:
        return parse(value)
    except (TypeError, ValueError):
        raise Refusal(f"{where} has an unreadable {kind} {value!r}") from None


def parse_networks(inspect_json):
    """`docker network inspect` JSON -> one dict per network."""
    try:
        raw = json.loads(inspect_json)
    except ValueError:
        raise Refusal("could not read `docker network inspect` output as JSON") from None
    networks = []
    for net in raw:
        name = net["Name"]
        labels = net.get("Labels") or {}
        pools = []
        for config in (net.get("IPAM") or {}).get("Config") or []:
            subnet = _parse("network", config.get("Subnet"), f"network {name}")
            if subnet is None:
                continue
            pools.append((subnet, _parse("address", config.get("Gateway"), f"network {name}"),
                          _parse("network", config.get("IPRange"), f"network {name}")))
        holders = []
        for container_id, c in (net.get("Containers") or {}).items():
            iface = _parse("interface", c.get("IPv4Address"), f"container {container_id} on network {name}")
            holders.append((iface.ip if iface is not None else None, container_id))
        networks.append({
            "name": name, "project": labels.get("com.docker.compose.project", ""),
            "labels": labels, "driver": net.get("Driver", ""), "internal": net.get("Internal") is True,
            "pools": pools, "holders": holders,
        })
    return networks


def plan(name, subnet_s, ip_s, marker, networks, routes):
    """Returns the output lines; raises Refusal."""
    try:
        subnet = ipaddress.IPv4Network(subnet_s, strict=True)
    except ValueError:
        raise Refusal(f"APPS_EDGE_SUBNET {subnet_s!r} is not an IPv4 subnet like 172.31.250.0/24") from None
    if not 16 <= subnet.prefixlen <= 28:
        raise Refusal(f"APPS_EDGE_SUBNET {subnet} must be between /16 and /28")
    try:
        ip = ipaddress.IPv4Address(ip_s)
    except ValueError:
        raise Refusal(f"APPS_EDGE_CADDY_IP {ip_s!r} is not an IPv4 address") from None

    existing = next((n for n in networks if n["name"] == name), None)
    others = [(n["name"], p[0]) for n in networks if n["name"] != name for p in n["pools"]]
    for other, other_subnet in others:
        if other_subnet.version == 4 and subnet.overlaps(other_subnet):
            raise Refusal(f"APPS_EDGE_SUBNET {subnet} overlaps Docker network {other} ({other_subnet}); pick a free range")
    docker_subnets = {str(s) for _, s in others}
    for route in routes:
        try:
            dest = ipaddress.ip_network(route, strict=False)
        except ValueError:
            continue
        if str(dest) not in docker_subnets and str(dest) != str(subnet) and subnet.overlaps(dest):
            raise Refusal(f"APPS_EDGE_SUBNET {subnet} overlaps the host route {dest}; pick a free range")

    # New networks get the first host as gateway and hand out dynamic addresses
    # from the upper half only, so the lower half is free for pinned addresses.
    gateway, dyn_range = subnet.network_address + 1, list(subnet.subnets(prefixlen_diff=1))[1]
    marker_key, marker_value = marker.split("=", 1)
    if existing is not None:
        if existing["project"]:
            raise Refusal(f"network {name} belongs to compose project {existing['project']}; use a network of its own")
        if existing["labels"].get(marker_key) != marker_value:
            raise Refusal(f"network {name} exists but was not created by this preflight (no {marker} label); "
                          "pick another name, or remove it so the preflight can create it")
        if existing["driver"] != "bridge":
            raise Refusal(f"network {name} uses the {existing['driver']} driver, not bridge")
        if not existing["internal"]:
            raise Refusal(f"network {name} is not internal; remove it so the preflight can recreate it")
        pools = existing["pools"]
        if [str(p[0]) for p in pools] != [str(subnet)]:
            raise Refusal(f"network {name} exists with subnet(s) {[str(p[0]) for p in pools]}, not {subnet}")
        _, gateway, dyn_range = pools[0]

    if ip not in subnet or ip in (subnet.network_address, subnet.broadcast_address):
        raise Refusal(f"APPS_EDGE_CADDY_IP {ip} is not a usable address in {subnet}")
    if ip == gateway:
        raise Refusal(f"APPS_EDGE_CADDY_IP {ip} is the network gateway")
    if dyn_range is not None and ip in dyn_range:
        raise Refusal(f"APPS_EDGE_CADDY_IP {ip} is in the dynamic range {dyn_range}; pick one below it")

    lines = []
    for held, container in (existing["holders"] if existing is not None else []):
        if held is None:
            raise Refusal(f"container {container} on network {name} has no IPv4 address; "
                          "can not tell whether it holds the Caddy address")
        if held == ip:
            lines.append(f"held {container}")
    lines.append("exists" if existing is not None else f"create {gateway} {dyn_range}")
    return lines


def main():
    env = os.environ
    try:
        lines = plan(env["NETWORK"], env["SUBNET"], env["CADDY_IP"], env["MARKER"],
                     parse_networks(sys.stdin.read()), env.get("ROUTES", "").split())
    except Refusal as refusal:
        print(f"preflight-apps-edge: {refusal}", file=sys.stderr)
        return 1
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
