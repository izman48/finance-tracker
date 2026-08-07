"""Small in-process rate limiter for public authentication endpoints.

This is deliberately a backstop, not a distributed abuse-control system: the
beta runs as a single API process. A production multi-instance deployment
must enforce the same limits at the edge/shared store as well.
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
        # Use the direct peer address. Deployment must only expose the API via
        # its trusted reverse proxy; accepting arbitrary forwarded headers here
        # would let an attacker choose a fresh identity on every request.
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
