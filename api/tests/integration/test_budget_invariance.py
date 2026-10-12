"""Budgets never move a money figure (T-09-1; sec's widened invariance test).

The whole summary, forecast and Wealth projection responses must be byte
for byte the same with budgets in any state as with none: safe_to_spend,
min_balance, committed_before_payday, savable, the solid forecast series,
the lowest point and the projections. Only the forecast's new
`budget_projection` key (T-09-4) may differ, so it is dropped before the
comparison.

Every scenario in SCENARIOS runs against the same seeded user and is
compared with the no-budget run: computing budget spend (T-09-1); active,
paused, removed and over-limit budgets, bulk set and suggest (T-09-2).
T-09-5 adds budgets changed by Claude.
"""
from datetime import timedelta

import pytest

from app.services.budget_spend import budget_spend
from tests.clock import TODAY
from tests.integration.test_budget_spend import START, World
from tests.integration.test_oauth import _bearer, _web_login

API = "/api/v1"
NEW_KEYS = {"budget_projection", "budget_projection_reason"}


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


def _spend_computed(w, client, token):
    """Computing budget spend (as tracking, History and the projection will)."""
    w.as_user(lambda: budget_spend(w.db, w.user, START, TODAY))
    w.as_user(lambda: budget_spend(w.db, w.user, START - timedelta(days=60), START))


def _create(client, token, category, limit):
    r = client.post(f"{API}/budgets", json={"category": category, "limit_pounds": limit}, headers=_bearer(token))
    assert r.status_code == 201, r.text
    client.get(f"{API}/budgets", headers=_bearer(token))  # the read route computes everything
    return r.json()["id"]


def _active(w, client, token):
    _create(client, token, "Eating out", 150)
    _create(client, token, "Groceries", 400)


def _paused(w, client, token):
    budget_id = _create(client, token, "Eating out", 150)
    client.patch(f"{API}/budgets/{budget_id}", json={"paused": True}, headers=_bearer(token))


def _removed(w, client, token):
    budget_id = _create(client, token, "Eating out", 150)
    client.delete(f"{API}/budgets/{budget_id}", headers=_bearer(token))


def _over_limit(w, client, token):
    _create(client, token, "Groceries", 1)  # £30 spent against £1


def _bulk_and_suggest(w, client, token):
    client.put(f"{API}/budgets", json={"budgets": [{"category": "Eating out", "limit_pounds": 5},
                                                  {"category": "Groceries", "limit_pounds": 5}]},
               headers=_bearer(token))
    client.post(f"{API}/budgets/suggest", json={}, headers=_bearer(token))


# T-09-5 adds "budgets changed by Claude".
SCENARIOS = {
    "budget spend computed": _spend_computed,
    "active budgets": _active,
    "a paused budget": _paused,
    "a removed budget": _removed,
    "an over-limit budget": _over_limit,
    "bulk set and suggest": _bulk_and_suggest,
}


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_budgets_never_move_a_money_figure(client, db_session, scenario):
    w = World(client, db_session)
    w.seed()
    token = _web_login(client, "budgets@example.com")
    before = _money(client, token)
    SCENARIOS[scenario](w, client, token)
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
