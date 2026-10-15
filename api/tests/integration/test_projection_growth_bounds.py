"""The projection's growth % is bounded at the route (T-11-4b, sec T-11-4).

The holding engine refuses a growth % outside -100..50 instead of clamping
it, so the route must answer 422 first, never a 500.
"""
import pytest

from tests.integration.test_oauth import _bearer, _web_login

URL = "/api/v1/analytics/net-worth-projection"


@pytest.mark.parametrize("pct,status", [("60", 422), ("50.01", 422), ("-101", 422), ("50", 200), ("-100", 200)])
def test_annual_growth_pct_outside_minus_100_to_50_is_422(client, pct, status):
    headers = _bearer(_web_login(client, "growth-bounds@example.com"))
    r = client.get(URL, params={"annual_growth_pct": pct, "monthly_contribution": "0"}, headers=headers)
    assert r.status_code == status, r.text
