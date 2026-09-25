"""Small in-process rate limiter for public authentication endpoints.

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
from threading import Lock
from time import monotonic

from fastapi import HTTPException, Request, status


class SlidingWindowRateLimiter:
    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def check(self, request: Request, scope: str, limit: int, window_seconds: int) -> None:
        # Never read X-Forwarded-For here: uvicorn has already resolved the
        # peer from it when (and only when) the request came via the trusted
        # proxy. Reading it ourselves would let any caller pick a fresh
        # identity per request.
        peer = request.client.host if request.client else "unknown"
        now = monotonic()
        key = f"{scope}:{peer}"
        with self._lock:
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

    def reset(self) -> None:
        """Clear counters for isolated tests; never call from request code."""
        with self._lock:
            self._events.clear()


auth_rate_limiter = SlidingWindowRateLimiter()
