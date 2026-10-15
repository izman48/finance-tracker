"""Money paths use the UK day (T-11-9; sec T-11-9 clock-pinned tests).

At 23:30 UTC on the night the clocks go back (24 Oct 2026, already 25 Oct
in the UK) and on the last day of a BST month (30 Sep 2026, already 1 Oct),
the next commitment date and the next payday roll on the UK date. With the
old UTC day they stayed on "yesterday". The clock is frozen through
`app.core.clock`, and the run-wide pin of `_today` (conftest) is lifted for
these tests so the real helper runs.
"""
import sys
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.core import clock
from app.models import CommitmentRule
from tests.conftest import _real_today
from tests.integration.test_commitment_writes_api import API, World, _bearer
from tests.integration.test_transactions_endpoint import _account


@pytest.fixture
def at(monkeypatch):
    def freeze(utc: datetime):
        monkeypatch.setattr(clock, "_now_utc", lambda: utc)
        for module in list(sys.modules.values()):
            if getattr(module, "__name__", "").startswith("app.") and callable(getattr(module, "_today", None)):
                monkeypatch.setattr(module, "_today", _real_today)
    return freeze


@pytest.fixture
def world(client, db_session):
    return World(client, db_session, email="uk-today@example.com")


def _rule(world, label, direction, next_date, is_payday=False, amount="100.00"):
    with world.as_user():
        rule = CommitmentRule(user_id=world.user.id, direction=direction, label=label, amount=Decimal(amount),
                              cadence="monthly", next_date=next_date, source="manual", status="confirmed",
                              is_payday=is_payday)
        world.db.add(rule)
        world.db.commit()
        return rule.id


@pytest.mark.parametrize("utc,uk_yesterday,next_month", [
    (datetime(2026, 10, 24, 23, 30, tzinfo=timezone.utc), date(2026, 10, 24), date(2026, 11, 24)),
    (datetime(2026, 9, 30, 23, 30, tzinfo=timezone.utc), date(2026, 9, 30), date(2026, 10, 30)),
])
def test_bills_and_payday_roll_on_the_uk_date(world, at, utc, uk_yesterday, next_month):
    at(utc)
    with world.as_user():
        _account(world.db, world.user.id, name="Current", balance="2000")
    bill = _rule(world, "Gym", "expense", uk_yesterday)
    _rule(world, "Salary", "income", uk_yesterday, is_payday=True, amount="2500.00")

    rules = world.client.get(f"{API}/analytics/commitments", headers=_bearer(world.web)).json()
    (gym,) = [r for r in rules if r["id"] == str(bill)]
    assert gym["next_date"] == next_month.isoformat()

    summary = world.client.get(f"{API}/analytics/summary", headers=_bearer(world.web)).json()
    assert summary["next_payday"] == next_month.isoformat()
    # The gym bill falls due before that payday, once, so safe to spend is the
    # balance less that bill (no other bills, no budgets).
    assert Decimal(summary["committed_before_payday"]) == Decimal("100.00")
    assert Decimal(summary["safe_to_spend"]) == Decimal("1900.00")
