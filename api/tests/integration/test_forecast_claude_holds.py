"""The forecast holds Claude's pending changes like the summary does
(T-12-9a; sec T-12-9).

Until the user keeps a Claude change, a bill counts the higher of now and
before-Claude (a dismissal, a cut or a later date waits), an income the
lower, and a planned expense Claude removed still counts. The summary and
projection already read commitments through `counted_commitments` and
planned items with `held_removed_planned`; the forecast read them as they
are, so the Cashflow chart moved up while safe-to-spend didn't. Equality
test: with a pending change, the forecast's bills before payday equal the
summary's `committed_before_payday`. Synthetic figures only.
"""
from datetime import timedelta
from decimal import Decimal

import pytest

from tests.clock import TODAY
from tests.integration.test_no_claude_raise import World as BillWorld
from tests.integration.test_oauth import _bearer
from tests.integration.test_planned_events_api import World as PlanWorld
from tests.integration.test_planned_removal_hold import _added
from tests.integration.test_transactions_endpoint import _account

API = "/api/v1"


def _forecast(w, horizon="payday"):
    r = w.client.get(f"{API}/analytics/forecast", params={"horizon": horizon}, headers=_bearer(w.web))
    assert r.status_code == 200, r.text
    return r.json()


def _bills_before(forecast, end) -> Decimal:
    """Commitment and planned expenses in the forecast up to `end`."""
    return -sum(
        (Decimal(str(e["amount"])) for p in forecast["timeline"] for e in p["events"]
         if e["kind"] in ("expense", "planned") and Decimal(str(e["amount"])) < 0 and p["date"] < end),
        Decimal(0),
    )


@pytest.fixture
def w(client, db_session):
    world = BillWorld(client, db_session, email="forecast-holds@example.com")
    world.as_user(lambda: _account(db_session, world.user.id, name="Current", balance="500"))
    return world


def _payday(w):
    return w.summary()["next_payday"]


@pytest.mark.parametrize("change", ["dismiss", "cut", "later"])
def test_a_pending_claude_change_to_a_bill_leaves_the_forecast_as_before(w, change):
    before = _forecast(w)
    if change == "dismiss":
        audit_id = w.claude_dismiss(w.bill)
    elif change == "cut":
        audit_id = w.claude_update(w.bill, amount="100.00")
    else:
        audit_id = w.claude_update(w.bill, next_date=(TODAY + timedelta(days=15)).isoformat())
    held = _forecast(w)
    assert (held["min_balance"], held["end_balance"]) == (before["min_balance"], before["end_balance"])
    # sec's equality: the forecast's bills before payday = the summary's.
    assert _bills_before(held, _payday(w)) == Decimal(w.summary()["committed_before_payday"])
    # Kept, the change applies to both.
    assert w.keep(audit_id).status_code == 200
    kept = _forecast(w)
    assert Decimal(str(kept["end_balance"])) > Decimal(str(before["end_balance"])) or change == "later"
    assert _bills_before(kept, _payday(w)) == Decimal(w.summary()["committed_before_payday"])


def test_a_pending_raise_of_an_income_waits_too(w):
    before = _forecast(w, horizon="30")
    audit_id = w.claude_update(w.salary, amount="2500.00")
    assert _forecast(w, horizon="30")["end_balance"] == before["end_balance"]
    w.keep(audit_id)
    after = _forecast(w, horizon="30")
    assert Decimal(str(after["end_balance"])) - Decimal(str(before["end_balance"])) == Decimal("500.00")


def test_a_claude_raise_of_a_bill_applies_at_once(w):
    before = _forecast(w)
    w.claude_update(w.bill, amount="350.00")
    after = _forecast(w)
    assert Decimal(str(before["end_balance"])) - Decimal(str(after["end_balance"])) == Decimal("50.00")


def test_a_planned_expense_claude_removed_stays_in_the_forecast_until_kept(client, db_session):
    pw = PlanWorld(client, db_session, email="forecast-holds-plan@example.com")
    item_id = _added(pw)
    before = _forecast(pw, horizon="30")
    audit_id = pw.remove(item_id).json()["audit_id"]
    held = _forecast(pw, horizon="30")
    assert held["end_balance"] == before["end_balance"]
    assert any(e["label"] == "Car insurance" for p in held["timeline"] for e in p["events"])
    pw.client.post(f"{API}/audit/{audit_id}/keep", headers=_bearer(pw.web))
    kept = _forecast(pw, horizon="30")
    assert Decimal(str(kept["end_balance"])) - Decimal(str(before["end_balance"])) == Decimal("200.00")


def _balance_before(forecast, day: str) -> Decimal:
    """The forecast's running balance on the last day before `day`."""
    return Decimal(str([p for p in forecast["timeline"] if p["date"] < day][-1]["balance"]))


def test_with_a_pending_cut_the_forecast_reaches_payday_at_safe_to_spend(w):
    """eng-b on #229: one figure, two surfaces. One account, no card, so the
    balance the day before payday is what safe-to-spend leaves."""
    w.claude_update(w.bill, amount="100.00")
    summary = w.summary()
    assert _balance_before(_forecast(w), summary["next_payday"]) == Decimal(summary["safe_to_spend"])


def test_a_pending_claude_move_of_payday_closer_keeps_the_horizon(w):
    """sec-1 on #229: the payday horizon ends where the summary's committed
    window does, so moving the salary 8 days earlier drops no bill off the
    chart until the user keeps the change."""
    before = _forecast(w)
    audit_id = w.claude_update(w.salary, next_date=(TODAY + timedelta(days=2)).isoformat())
    held = _forecast(w)
    assert (held["horizon_end"], held["end_balance"]) == (before["horizon_end"], before["end_balance"])
    assert w.keep(audit_id).status_code == 200
    assert _forecast(w)["horizon_end"] == (TODAY + timedelta(days=2)).isoformat()


def test_a_pending_claude_move_of_payday_closer_keeps_the_budget_line(w):
    """T-12-9d: the budget cycle (the "after budgets" strip) ends where the
    summary's committed window does, so a pending salary move can't take
    the bill before the old payday out of the strip and lift it."""
    _add_budget(w)
    before = _forecast(w)["budget_projection"]
    assert before is not None
    audit_id = w.claude_update(w.salary, next_date=(TODAY + timedelta(days=2)).isoformat())
    held = _forecast(w)["budget_projection"]
    assert (held["payday"], held["after_budgets_balance"]) == (before["payday"], before["after_budgets_balance"])
    assert w.keep(audit_id).status_code == 200
    assert _forecast(w)["budget_projection"]["payday"] == (TODAY + timedelta(days=2)).isoformat()


def test_a_pending_claude_move_of_payday_closer_leaves_every_day_as_before(w):
    """T-12-9d: the salary counts the same either way, so the tie goes to
    before-Claude. Otherwise pay landing early in the chart would hide a dip
    between the new and the old payday until the user keeps the move."""
    before = _forecast(w)
    w.claude_update(w.salary, next_date=(TODAY + timedelta(days=2)).isoformat())
    held = _forecast(w)
    assert [(p["date"], p["balance"]) for p in held["timeline"]] == [(p["date"], p["balance"]) for p in before["timeline"]]


def test_a_pending_claude_move_of_payday_later_shows_the_later_date(w):
    """eng-b on #238, the mirror: an income tie counts the version whose pay
    lands later, so moving pay later shows the later date at once and no day
    between the two dates is overstated."""
    before = _forecast(w, horizon="30")
    audit_id = w.claude_update(w.salary, next_date=(TODAY + timedelta(days=14)).isoformat())
    held = _forecast(w, horizon="30")
    assert all(Decimal(str(h["balance"])) <= Decimal(str(b["balance"]))
               for h, b in zip(held["timeline"], before["timeline"]))
    w.keep(audit_id)
    kept = _forecast(w, horizon="30")
    assert [(p["date"], p["balance"]) for p in held["timeline"]] == [(p["date"], p["balance"]) for p in kept["timeline"]]


def test_a_pending_claude_move_of_payday_closer_leaves_the_dotted_line_as_before(w):
    """sec-1 on #238 (criterion 3): the cycles after this one step at the
    later of payday now and before Claude, so the whole dotted series is
    unchanged while the move is pending."""
    _add_budget(w)
    before = _forecast(w, horizon="90")["budget_projection"]["series"]
    w.claude_update(w.salary, next_date=(TODAY + timedelta(days=2)).isoformat())
    assert _forecast(w, horizon="90")["budget_projection"]["series"] == before


def _add_budget(w):
    from app.models import Budget

    def add():
        w.db.add(Budget(user_id=w.user.id, category="Groceries", limit_pounds=Decimal("90")))
        w.db.commit()
    w.as_user(add)
