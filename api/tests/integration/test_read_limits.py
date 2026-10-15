"""Per-user limits on the remaining MCP-reachable reads that decrypt the
whole ledger: summary, forecast, spending and the spending trend (T-12-10b
part 3; sec-2 on #244/#246). Keyed by user, never IP (MCP calls share one
address), so two users each keep their own budget. Limits are patched small.
Transaction search was already limited per user (10 a minute)."""
import pytest

from app.core import rate_limit
from tests.integration.test_oauth import _bearer, _web_login

API = "/api/v1"


@pytest.mark.parametrize("path,scope", [
    ("/analytics/summary", "summary"),
    ("/analytics/forecast", "forecast"),
    ("/analytics/spending", "spending"),
    ("/analytics/spending/trend", "spending"),
])
def test_each_read_is_limited_per_user(client, monkeypatch, path, scope):
    monkeypatch.setitem(rate_limit.LIMITS, scope, (2, 60))
    alice = _bearer(_web_login(client, "reads-alice@example.com"))
    bob = _bearer(_web_login(client, "reads-bob@example.com"))
    assert [client.get(f"{API}{path}", headers=alice).status_code for _ in range(2)] == [200, 200]
    res = client.get(f"{API}{path}", headers=alice)
    assert res.status_code == 429 and "Retry-After" in res.headers
    assert client.get(f"{API}{path}", headers=bob).status_code == 200


def test_the_limits_leave_room_for_the_app():
    # Home and Cashflow load summary and forecast on every visit and filter.
    assert rate_limit.LIMITS["summary"][0] >= 60 and rate_limit.LIMITS["forecast"][0] >= 60
