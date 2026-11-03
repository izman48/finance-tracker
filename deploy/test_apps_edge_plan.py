"""Unit tests for deploy/apps_edge_plan.py: parsing `docker network inspect`
JSON as Docker 24, 27 and 29 print it. No Docker needed.
Usage: python3 deploy/test_apps_edge_plan.py   (test-apps-edge.sh runs it first)

The Docker 29 fixture is the shape the production server (Docker 29.5.3)
returned on 2026-11-03, container ids replaced. There, the old --format
template printed the same networks as
    bridge|bridge|172.17.0.0/16,172.17.0.1,invalid Prefix
and the preflight crashed splitting on the space in `invalid Prefix`.
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from apps_edge_plan import Refusal, parse_networks, plan  # noqa: E402

MARKER = "apps-edge.managed-by=preflight-apps-edge"
NAME, SUBNET, CADDY_IP = "health_edge", "172.30.251.0/24", "172.30.251.10"


def cid(n):
    return f"{n:064x}"


def network(name, configs, driver="bridge", internal=False, labels=None, containers=None, **extra):
    return {"Name": name, "Id": "0" * 64, "Driver": driver, "Internal": internal, "Labels": labels,
            "IPAM": {"Driver": "default", "Options": None, "Config": configs},
            "Containers": containers, **extra}


def holder(ip):
    return {"Name": "c", "EndpointID": "e", "MacAddress": "", "IPv4Address": ip, "IPv6Address": ""}


# Docker 29.5.3: IPRange is left out when unset; host/none have Config null;
# EnableIPv4 and Status are new keys.
DOCKER_29 = [
    network("bridge", [{"Subnet": "172.17.0.0/16", "Gateway": "172.17.0.1"}], labels={},
            containers={}, EnableIPv4=True, Status={}),
    network("finance-tracker_default", [{"Subnet": "172.18.0.0/16", "Gateway": "172.18.0.1"}],
            labels={"com.docker.compose.project": "finance-tracker"},
            containers={cid(1): holder("172.18.0.2/16"), cid(2): holder("172.18.0.3/16")}, EnableIPv4=True),
    network("finance-tracker_edge", [{"Subnet": "172.30.250.0/24", "Gateway": "172.30.250.1"}],
            labels={"com.docker.compose.project": "finance-tracker"},
            containers={cid(3): holder("172.30.250.10/24")}, EnableIPv4=True),
    network("host", None, driver="host", labels={}, containers={}),
    network("none", None, driver="null", labels={}, containers={}),
]
# Docker 24 and 27: same keys for these fields; an unset IPRange is left out
# too, a set one is a CIDR string; Containers can be {} and Labels {}.
DOCKER_24 = [
    network("bridge", [{"Subnet": "172.17.0.0/16", "Gateway": "172.17.0.1"}], labels={}, containers={}),
    network("host", None, driver="host", labels={}, containers={}),
    network("none", None, driver="null", labels={}, containers={}),
]


def ours(ip_range="172.30.251.128/25", gateway="172.30.251.1", containers=None, **kw):
    config = {"Subnet": SUBNET}
    if gateway is not None:
        config["Gateway"] = gateway
    if ip_range is not None:
        config["IPRange"] = ip_range
    return network(NAME, [config], internal=True, labels={"apps-edge.managed-by": "preflight-apps-edge"},
                   containers=containers or {}, **kw)


def run(networks, routes=(), ip=CADDY_IP):
    return plan(NAME, SUBNET, ip, MARKER, parse_networks(json.dumps(networks)), list(routes))


class Docker29(unittest.TestCase):
    def test_server_output_parses(self):
        nets = {n["name"]: n for n in parse_networks(json.dumps(DOCKER_29))}
        self.assertEqual([(str(s), str(g), r) for s, g, r in nets["bridge"]["pools"]],
                         [("172.17.0.0/16", "172.17.0.1", None)])
        self.assertEqual(nets["host"]["pools"], [])
        self.assertEqual(nets["finance-tracker_edge"]["project"], "finance-tracker")
        self.assertEqual([str(ip) for ip, _ in nets["finance-tracker_default"]["holders"]],
                         ["172.18.0.2", "172.18.0.3"])

    def test_server_output_plans_create(self):
        self.assertEqual(run(DOCKER_29), ["create 172.30.251.1 172.30.251.128/25"])

    def test_overlap_with_server_network_refused(self):
        with self.assertRaisesRegex(Refusal, "finance-tracker_edge"):
            plan(NAME, "172.30.250.0/24", "172.30.250.20", MARKER, parse_networks(json.dumps(DOCKER_29)), [])

    def test_invalid_strings_mean_unset(self):
        # In case a later Docker puts Go's String() of a zero value in the JSON.
        net = ours(ip_range="invalid Prefix", gateway="invalid IP")
        self.assertEqual(run(DOCKER_29 + [net], ip="172.30.251.200"), ["exists"])
        self.assertEqual(run(DOCKER_29 + [ours(ip_range="", gateway="")], ip="172.30.251.200"), ["exists"])

    def test_existing_network_unset_range_and_gateway(self):
        self.assertEqual(run(DOCKER_29 + [ours(ip_range=None, gateway=None)], ip="172.30.251.200"), ["exists"])

    def test_old_template_text_is_refused_not_a_traceback(self):
        text = ("bridge|bridge|172.17.0.0/16,172.17.0.1,invalid Prefix \n"
                "host|host|\n")
        with self.assertRaisesRegex(Refusal, "JSON"):
            parse_networks(text)


class Docker24(unittest.TestCase):
    def test_creates(self):
        self.assertEqual(run(DOCKER_24), ["create 172.30.251.1 172.30.251.128/25"])

    def test_accepts_its_own_network(self):
        self.assertEqual(run(DOCKER_24 + [ours()]), ["exists"])

    def test_caddy_in_existing_dynamic_range_refused(self):
        with self.assertRaisesRegex(Refusal, "dynamic range 172.30.251.128/25"):
            run(DOCKER_24 + [ours()], ip="172.30.251.200")

    def test_null_labels_and_containers(self):
        nets = DOCKER_24 + [network("x", [{"Subnet": "10.9.0.0/24"}], labels=None, containers=None)]
        self.assertEqual(run(nets), ["create 172.30.251.1 172.30.251.128/25"])


class Holders(unittest.TestCase):
    def test_held_by_container(self):
        net = ours(containers={cid(7): holder("172.30.251.10/24"), cid(8): holder("172.30.251.11/24")})
        self.assertEqual(run(DOCKER_29 + [net]), [f"held {cid(7)}", "exists"])

    def test_holder_without_ipv4_refused(self):
        for unset in ("", "invalid Prefix", None):
            with self.subTest(unset=unset), self.assertRaisesRegex(Refusal, "no IPv4 address"):
                run(DOCKER_29 + [ours(containers={cid(7): holder(unset)})])

    def test_unreadable_holder_address_refused(self):
        with self.assertRaisesRegex(Refusal, "unreadable"):
            run(DOCKER_29 + [ours(containers={cid(7): holder("garbage 1")})])


class Unreadable(unittest.TestCase):
    def test_unreadable_values_refused_not_ignored(self):
        for config in ({"Subnet": "nonsense"}, {"Subnet": "10.9.0.0/24", "Gateway": "x y"},
                       {"Subnet": "10.9.0.0/24", "IPRange": "10.9.0.0/33"}):
            with self.subTest(config=config), self.assertRaisesRegex(Refusal, "unreadable"):
                parse_networks(json.dumps([network("x", [config])]))

    def test_ipv6_pool_on_another_network_ignored_for_overlap(self):
        nets = DOCKER_29 + [network("v6", [{"Subnet": "fd00::/64", "Gateway": "fd00::1"}])]
        self.assertEqual(run(nets), ["create 172.30.251.1 172.30.251.128/25"])


if __name__ == "__main__":
    unittest.main(verbosity=1)
