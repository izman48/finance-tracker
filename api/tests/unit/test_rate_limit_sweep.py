"""Idle limiter keys are evicted, so per-user keys don't accumulate forever."""
from app.core import rate_limit
from app.core.rate_limit import SlidingWindowRateLimiter


def test_keys_idle_past_their_window_are_swept(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(rate_limit, "monotonic", lambda: clock[0])
    limiter = SlidingWindowRateLimiter()
    limiter.check_key("search:a", limit=10, window_seconds=60)
    limiter.check_key("login:b", limit=10, window_seconds=900)

    clock[0] += 61
    limiter.sweep()
    assert limiter.tracked_keys() == {"login:b"}  # still inside its own window

    clock[0] += 900
    limiter.sweep()
    assert limiter.tracked_keys() == set()


def test_check_key_sweeps_now_and_then(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(rate_limit, "monotonic", lambda: clock[0])
    limiter = SlidingWindowRateLimiter()
    limiter.check_key("search:old", limit=10, window_seconds=60)
    clock[0] += 61
    for i in range(rate_limit.SWEEP_EVERY):
        limiter.check_key(f"search:{i % 5}", limit=10_000, window_seconds=60)
    assert "search:old" not in limiter.tracked_keys()
