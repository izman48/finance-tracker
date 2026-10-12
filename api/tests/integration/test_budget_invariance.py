"""Budgets never move a money figure (T-09-1; sec's widened invariance test).

The whole summary, forecast and Wealth projection responses must be byte
for byte the same with budgets in any state as with none: safe_to_spend,
min_balance, committed_before_payday, savable, the solid forecast series,
the lowest point and the projections. Only the forecast's new
`budget_projection` key (T-09-4) may differ, so it is dropped before the
comparison.

Every scenario in SCENARIOS runs against the same seeded user and is
compared with the no-budget run. T-09-1 ships the harness and the counting
function's scenario (computing budget spend must not write or move
anything); T-09-2 adds active, paused, removed and over-limit budgets, and
T-09-5 budgets changed by Claude.
"""
from datetime import timedelta

import pytest

from app.services.budget_spend import budget_spend
from tests.clock import TODAY
from tests.integration.test_budget_spend import START, World
from tests.integration.test_oauth import _bearer, _web_login

API = "/api/v1"
NEW_KEYS = {"budget_projection"}


def _money(client, token) -> dict:
    """Everything a budget must not move, as raw response bytes."""
    out = {}
    for name, path, params in (
        ("summary", "/analytics/summary", {}),
        ("forecast_payday", "/analytics/forecast", {"horizon": "payday"}),
        ("forecast_90", "/analytics/forecast", {"horizon": "90"}),
        ("projection", "/analytics/net-worth-projection", {}),
    ):
        r = client.get(f"{API}{path}", params=params, headers=_bearer(token))
        assert r.status_code == 200, (name, r.text)
        body = r.json()
        for key in NEW_KEYS:
            body.pop(key, None)
        out[name] = body
    return out


def _spend_computed(w):
    """Computing budget spend (as tracking, History and the projection will)."""
    w.as_user(lambda: budget_spend(w.db, w.user, START, TODAY))
    w.as_user(lambda: budget_spend(w.db, w.user, START - timedelta(days=60), START))


SCENARIOS = {"budget spend computed": _spend_computed}


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_budgets_never_move_a_money_figure(client, db_session, scenario):
    w = World(client, db_session)
    w.seed()
    token = _web_login(client, "budgets@example.com")
    before = _money(client, token)
    SCENARIOS[scenario](w)
    assert _money(client, token) == before


def test_the_harness_sees_a_real_change(client, db_session):
    """Guard: the comparison would catch a moved figure (a new bill)."""
    from decimal import Decimal

    from app.models import CommitmentRule

    w = World(client, db_session)
    w.seed()
    token = _web_login(client, "budgets@example.com")
    before = _money(client, token)

    def bill():
        w.db.add(CommitmentRule(user_id=w.user.id, direction="expense", label="Gym", amount=Decimal("40"),
                                cadence="monthly", next_date=TODAY + timedelta(days=3), source="manual",
                                status="confirmed"))
        w.db.commit()
    w.as_user(bill)
    after = _money(client, token)
    assert after["summary"]["safe_to_spend"] != before["summary"]["safe_to_spend"]
