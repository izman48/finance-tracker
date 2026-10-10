"""Small in-process rate limiters: per client IP for public authentication
endpoints, per user for expensive authenticated reads.

This is deliberately a backstop, not a distributed abuse-control system.

Client identity is ``request.client.host``. Behind the production reverse
proxy that is only the real caller because uvicorn is started with
``--forwarded-allow-ips`` set to the proxy's pinned address (see
docker-compose.prod.yml): uvicorn then rewrites the peer from the proxy's
X-Forwarded-For, and ignores that header from anyone else. Without it every
request appears to come from the proxy and each limit becomes one global
budget shared by all users — a trivial lockout.

Counters live in process memory. Production runs two uvicorn workers, each
with its own counters, so a caller can get up to ``limit × workers`` attempts
per window. That is an accepted trade for keeping Argon2-heavy logins off a
single process; enforce limits in a shared store before scaling further.
"""
from collections import defaultdict, deque
from collections.abc import Iterator
from contextlib import contextmanager
from threading import Lock
from time import monotonic

from fastapi import HTTPException, Request, status


# Every this many checks, keys idle past their own window are dropped, so
# per-user keys don't accumulate for the life of the process.
SWEEP_EVERY = 1024


class SlidingWindowRateLimiter:
    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._windows: dict[str, int] = {}
        self._checks = 0
        self._lock = Lock()

    def check(self, request: Request, scope: str, limit: int, window_seconds: int) -> None:
        # Never read X-Forwarded-For here: uvicorn has already resolved the
        # peer from it when (and only when) the request came via the trusted
        # proxy. Reading it ourselves would let any caller pick a fresh
        # identity per request.
        peer = request.client.host if request.client else "unknown"
        self.check_key(f"{scope}:{peer}", limit, window_seconds)

    def check_key(self, key: str, limit: int, window_seconds: int) -> None:
        """Count one event against `key`; 429 with Retry-After past `limit`."""
        now = monotonic()
        with self._lock:
            self._checks += 1
            if self._checks % SWEEP_EVERY == 0:
                self._sweep(now)
            self._windows[key] = window_seconds
            events = self._events[key]
            cutoff = now - window_seconds
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= limit:
                retry_after = max(1, int(window_seconds - (now - events[0])))
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Too many attempts. Please try again later.",
                    headers={"Retry-After": str(retry_after)},
                )
            events.append(now)

    def sweep(self) -> None:
        """Drop keys with no event inside their own window."""
        with self._lock:
            self._sweep(monotonic())

    def _sweep(self, now: float) -> None:
        idle = [k for k, ev in self._events.items() if not ev or ev[-1] <= now - self._windows.get(k, 0)]
        for k in idle:
            del self._events[k]
            self._windows.pop(k, None)

    def tracked_keys(self) -> set[str]:
        with self._lock:
            return set(self._events)

    def reset(self) -> None:
        """Clear counters for isolated tests; never call from request code."""
        with self._lock:
            self._events.clear()
            self._windows.clear()


class InFlightGuard:
    """At most one call per key at a time, per process. A second call while
    the first is running gets 429 at once instead of queueing behind it."""

    def __init__(self) -> None:
        self._held: set[str] = set()
        self._lock = Lock()

    @contextmanager
    def hold(self, key: str, retry_after: int = 2) -> Iterator[None]:
        with self._lock:
            if key in self._held:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="A search is already running. Please try again shortly.",
                    headers={"Retry-After": str(retry_after)},
                )
            self._held.add(key)
        try:
            yield
        finally:
            with self._lock:
                self._held.discard(key)


auth_rate_limiter = SlidingWindowRateLimiter()
# Keyed by user id, never IP: remote MCP calls all reach the API from the MCP
# container's address, so an IP key would throttle every user as one.
user_rate_limiter = SlidingWindowRateLimiter()
user_in_flight = InFlightGuard()
