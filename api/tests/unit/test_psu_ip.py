"""Which caller address may go to TrueLayer as X-PSU-IP (T-08-22, sec option B).

Only a global unicast address, in its normal form; an IPv4-mapped IPv6 goes
as the IPv4. Private, loopback, link-local, reserved, documentation or
unparsable addresses give no header (which just means unattended: safe).
"""
import pytest

from app.core.psu_ip import public_ip


@pytest.mark.parametrize("host,expected", [
    ("81.2.69.142", "81.2.69.142"),
    ("::ffff:81.2.69.142", "81.2.69.142"),
    ("2a00:1450:4009:081f:0000:0000:0000:200e", "2a00:1450:4009:81f::200e"),
    ("10.1.2.3", None),          # private
    ("172.18.0.5", None),        # Docker network
    ("192.168.1.10", None),      # private
    ("127.0.0.1", None),         # loopback
    ("::1", None),               # loopback
    ("169.254.10.1", None),      # link-local
    ("fe80::1", None),           # link-local
    ("100.64.0.1", None),        # carrier-grade NAT (shared)
    ("192.0.2.1", None),         # documentation
    ("240.0.0.1", None),         # reserved
    ("::ffff:10.0.0.1", None),   # mapped private
    ("testclient", None),        # unparsable
    ("", None),
    (None, None),
])
def test_only_a_public_address_is_sent(host, expected):
    assert public_ip(host) == expected
