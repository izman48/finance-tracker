"""Budgets on Cashflow: the payday strip and the dotted line (T-09-4;
concept section 12, BC1-BC11; sec's max rule).

All to payday (the next payday), from the same inputs as the
reconciliation line on GET /budgets:
- scheduled_balance: the forecast balance on the day before payday (the
  solid line, unchanged);
- stick_to_budgets_balance: scheduled - remaining budgets - other spending
  at pace;
- current_pace_balance: scheduled - all spending at pace;
- series: the solid line less the stick-to-budgets total, spread evenly
  from today to the day before payday, clipped to the chart's horizon.
A budget paused or removed this cycle keeps counting for the rest of the
cycle at max(remaining limit then, its spend at pace), so pausing or
removing never raises stick_to_budgets_balance or the headroom.
"""
from datetime import timedelta
from decimal import Decimal

import pytest

from tests.clock import TODAY
from tests.integration.test_budgets_api import API, World
from tests.integration.test_oauth import _bearer


@pytest.fixture
def w(client, db_session):
    world = World(client, db_session)
    world.history()
    return world


def _forecast(w, horizon="payday"):
    r = w.client.get(f"{API}/analytics/forecast", params={"horizon": horizon}, headers=_bearer(w.web))
    assert r.status_code == 200, r.text
    return r.json()


def _strip(w, horizon="payday"):
    return _forecast(w, horizon)["budget_projection"]


def test_no_budgets_no_projection(w):
    assert _forecast(w)["budget_projection"] is None


def test_the_three_payday_figures(w):
    w.create("Eating out", 150)  # 40 spent, 110 left
    body = _forecast(w)
    strip = body["budget_projection"]
    payday = TODAY - timedelta(days=20)
    # next payday: a month after the last one
    eve = [p for p in body["timeline"] if p["date"] < strip["payday"]][-1]
    assert Decimal(strip["scheduled_balance"]) == Decimal(eve["balance"])
    budgets = w.get().json()
    rec = budgets["reconciliation"]
    assert Decimal(strip["stick_to_budgets_balance"]) == (
        Decimal(strip["scheduled_balance"]) - Decimal(rec["budgets_left"]) - Decimal(rec["other_at_pace"]))
    assert Decimal(strip["current_pace_balance"]) <= Decimal(strip["scheduled_balance"])
    assert strip["payday"] > TODAY.isoformat() and payday.isoformat() < strip["payday"]


def test_the_dotted_line_ends_at_the_day_before_payday(w):
    w.create("Eating out", 150)
    strip = _strip(w)
    series = strip["series"]
    assert series[0]["date"] == TODAY.isoformat()
    assert series[-1]["date"] < strip["payday"]
    assert Decimal(series[-1]["balance"]) == Decimal(strip["stick_to_budgets_balance"])


def test_a_short_horizon_clips_the_line_but_keeps_the_payday_figures(w):
    w.create("Eating out", 150)
    full, week = _strip(w), _strip(w, "7")
    assert week["series"][-1]["date"] <= (TODAY + timedelta(days=7)).isoformat()
    assert week["stick_to_budgets_balance"] == full["stick_to_budgets_balance"]


def test_the_solid_line_and_lowest_point_never_move(w):
    before = _forecast(w)
    w.create("Eating out", 1)
    after = _forecast(w)
    for key in ("timeline", "min_balance", "min_date", "end_balance", "breaches"):
        assert after[key] == before[key]


def test_no_payday_no_projection(client, db_session):
    w = World(client, db_session, email="nopayday@example.com")

    def drop_payday():
        from app.models import CommitmentRule
        w.db.query(CommitmentRule).filter(CommitmentRule.direction == "income").delete()
        w.db.commit()
    w.history()
    w.as_user(drop_payday)
    w.create("Eating out", 150)
    assert _strip(w) is None


# --- sec's max rule -----------------------------------------------------------------

def _stick(w):
    return Decimal(_strip(w)["stick_to_budgets_balance"])


def _headroom(w):
    return Decimal(w.get().json()["reconciliation"]["headroom"])


def test_pausing_never_raises_the_figures(w):
    budget_id = w.create("Eating out", 300).json()["id"]  # 40 spent: 260 left, more than its pace
    w.create("Groceries", 400)
    stick, headroom = _stick(w), _headroom(w)
    w.patch(budget_id, paused=True)
    assert _stick(w) <= stick
    assert _headroom(w) <= headroom


def test_removing_never_raises_the_figures(w):
    budget_id = w.create("Eating out", 300).json()["id"]
    w.create("Groceries", 400)
    stick, headroom = _stick(w), _headroom(w)
    w.delete(budget_id)
    assert _stick(w) <= stick
    assert _headroom(w) <= headroom


def test_a_paused_category_counts_at_its_remaining_limit_this_cycle(w):
    budget_id = w.create("Eating out", 300).json()["id"]
    w.create("Groceries", 400)
    w.patch(budget_id, paused=True)
    rec = w.get().json()["reconciliation"]
    # Groceries 400 - 80 = 320, plus Eating out held at max(260, its pace).
    assert Decimal(rec["budgets_left"]) >= Decimal("580")


def test_resuming_ends_the_hold(w):
    budget_id = w.create("Eating out", 300).json()["id"]
    w.patch(budget_id, paused=True)
    w.patch(budget_id, paused=False)
    rec = w.get().json()["reconciliation"]
    assert Decimal(rec["budgets_left"]) == Decimal("260")


def test_lowering_a_limit_raises_the_figure_by_the_difference(w):
    """BC11: accepted (display only, informed preview)."""
    budget_id = w.create("Eating out", 300).json()["id"]
    stick = _stick(w)
    w.patch(budget_id, limit_pounds=50)
    assert _stick(w) == stick + Decimal("250")


def test_the_single_budget_lookup_is_a_404_if_gone(w):
    """sec's low nit on #150: the helper falls back to 404, never a 500."""
    import uuid

    from app.routers import budgets as router

    with pytest.raises(Exception) as err:
        w.as_user(lambda: router._one(w.db, w.user, uuid.uuid4()))
    assert getattr(err.value, "status_code", None) == 404


def test_the_strip_carries_the_headroom_and_the_difference(w):
    """ux BC4/BC12: both figures and their difference come from the API, so
    the UI never computes one."""
    w.create("Eating out", 150)
    strip = _strip(w)
    rec = w.get().json()["reconciliation"]
    assert Decimal(strip["headroom"]) == Decimal(rec["headroom"])
    assert Decimal(strip["difference"]) == (
        Decimal(strip["stick_to_budgets_balance"]) - Decimal(strip["headroom"]))


def test_on_the_day_before_payday_the_line_ends_at_the_strip(client, db_session):
    """eng-a on #154: with no days left, today's point is the full deduction."""
    from app.models import CommitmentRule

    w = World(client, db_session, email="eve@example.com")
    w.history()

    def payday_tomorrow():
        rule = w.db.query(CommitmentRule).filter(CommitmentRule.is_payday.is_(True)).one()
        rule.next_date = TODAY + timedelta(days=1)
        w.db.commit()
    w.as_user(payday_tomorrow)
    w.create("Eating out", 150)
    strip = _strip(w)
    assert strip["payday"] == (TODAY + timedelta(days=1)).isoformat()
    assert [p["date"] for p in strip["series"]] == [TODAY.isoformat()]
    assert Decimal(strip["series"][-1]["balance"]) == Decimal(strip["stick_to_budgets_balance"])
