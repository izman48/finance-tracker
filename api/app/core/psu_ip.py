"""The user's address for TrueLayer's X-PSU-IP header (T-08-22, sec option B).

Sent only on a sync the user starts in the web app, so the bank counts the
read as attended (PSD2) and not against its unattended-access limit. Never
on the MCP path: the user isn't at the bank interface there. The address
comes only from `request.client.host`, which uvicorn sets from Caddy's
X-Forwarded-For for the pinned proxy only; no header the client sends is
read. It is held for the request only, and never stored, logged or returned.
"""
from __future__ import annotations

import ipaddress
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

from fastapi import Request

# The address to send for the current request, or None (unattended).
current_psu_ip: ContextVar[str | None] = ContextVar("current_psu_ip", default=None)


def public_ip(host: str | None) -> str | None:
    """A global unicast address in its normal form (an IPv4-mapped IPv6 as
    the IPv4), or None for anything private, loopback, link-local, reserved,
    shared or unparsable: an omitted header just means unattended (safe)."""
    try:
        ip = ipaddress.ip_address(host or "")
    except ValueError:
        return None
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return str(ip) if ip.is_global else None


@contextmanager
def user_present(request: Request) -> Iterator[None]:
    """For a sync the user started in the web app: TrueLayer calls made in
    this block send their address. Reset afterwards."""
    token = current_psu_ip.set(public_ip(request.client.host if request.client else None))
    try:
        yield
    finally:
        current_psu_ip.reset(token)
