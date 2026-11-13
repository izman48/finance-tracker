"""Budgets on Cashflow: the payday strip and the dotted line (T-09-14, the
owner's simple rule, replacing T-09-4's pace model).

The dotted line is the scheduled (solid) line less the budgets, over the
whole forecast horizon, one point per timeline day from today:
- this cycle: what's left of the active, unpaused budgets (each
  max(0, limit - spent), so overspending never raises the line), spread
  evenly from today to the day before payday;
- each later cycle (paydays as `current_cycle` finds them): the total of
  those limits, spread evenly over that cycle's days, so the line rises
  with income exactly as the solid line does; less, per budget, the
  commitment instalments the forecast already has in that category
  (T-24-3b, below).
Unbudgeted spending is never projected; paused and removed budgets don't
count. The strip: scheduled_balance and after_budgets_balance on the day
before payday.
"""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.services.analytics import _add_months
from tests.clock import TODAY
from tests.integration.test_budgets_api import API, World
from tests.integration.test_oauth import _bearer
from tests.integration.test_transactions_endpoint import _tx


@pytest.fixture
def w(client, db_session):
    world = World(client, db_session)
    world.history()  # this cycle (payday 20 days ago): Eating out 40, Groceries 80, Shopping 120
    return world


def _forecast(w, horizon="90"):
    r = w.client.get(f"{API}/analytics/forecast", params={"horizon": horizon}, headers=_bearer(w.web))
    assert r.status_code == 200, r.text
    return r.json()


def _strip(w, horizon="90"):
    return _forecast(w, horizon)["budget_projection"]


def _spend(w, amount, category, days_ago=3):
    w.as_user(lambda: _tx(w.db, w.current, amount, TODAY - timedelta(days=days_ago), merchant=f"Shop {category}",
                          category=category))


def _drops(body) -> dict[str, Decimal]:
    """{date: solid line - dotted line} over the series."""
    solid = {p["date"]: Decimal(p["balance"]) for p in body["timeline"]}
    return {p["date"]: solid[p["date"]] - Decimal(p["balance"]) for p in body["budget_projection"]["series"]}


def _eve(payday: date) -> str:
    return (payday - timedelta(days=1)).isoformat()


def _owners_budgets(w):
    """The owner's case: £200 + £190 + £500 = £890, £631 spent, £259 left."""
    w.create("Eating out", 200)   # 40 spent: 160 left
    w.create("Groceries", 190)    # 80 + 11 spent: 99 left
    w.create("Shopping", 500)     # 120 + 380 spent: 0 left
    _spend(w, "11.00", "Groceries")
    _spend(w, "380.00", "Shopping")


def test_the_owners_case_this_cycle_and_the_next(w):
    _owners_budgets(w)
    body = _forecast(w, "90")
    strip, drops = body["budget_projection"], _drops(body)
    payday = date.fromisoformat(strip["payday"])
    assert drops[_eve(payday)] == Decimal("259.00")
    assert drops[_eve(_add_months(payday, 1))] == Decimal("259.00") + Decimal("890.00")
    assert Decimal(strip["after_budgets_balance"]) == Decimal(strip["scheduled_balance"]) - Decimal("259")
    solid = {p["date"]: Decimal(p["balance"]) for p in body["timeline"]}
    assert Decimal(strip["scheduled_balance"]) == solid[_eve(payday)]


def test_the_line_starts_on_the_solid_line_today_and_covers_the_horizon(w):
    _owners_budgets(w)
    body = _forecast(w, "90")
    series = body["budget_projection"]["series"]
    assert [p["date"] for p in series] == [p["date"] for p in body["timeline"] if p["date"] >= TODAY.isoformat()]
    assert _drops(body)[TODAY.isoformat()] == 0


def test_this_cycle_spreads_evenly_to_the_day_before_payday(w):
    _owners_budgets(w)
    body = _forecast(w, "90")
    payday = date.fromisoformat(body["budget_projection"]["payday"])
    span = (payday - timedelta(days=1) - TODAY).days
    tomorrow = (TODAY + timedelta(days=1)).isoformat()
    assert _drops(body)[tomorrow] == (Decimal("259") / span).quantize(Decimal("0.01"))


def test_the_whole_year(w):
    _owners_budgets(w)
    body = _forecast(w, "365")
    drops = _drops(body)
    assert body["budget_projection"]["series"][-1]["date"] == body["timeline"][-1]["date"]
    payday = date.fromisoformat(body["budget_projection"]["payday"])
    for n in range(10):
        eve = _eve(_add_months(payday, n))
        if eve in drops:
            assert drops[eve] == Decimal("259") + Decimal("890") * n
    values = [drops[d] for d in sorted(drops)]
    assert values == sorted(values)  # never gives budget back


def test_paused_budgets_dont_count(w):
    _owners_budgets(w)
    shopping = next(b for b in w.get().json()["budgets"] if b["category"] == "Groceries")["id"]
    w.patch(shopping, paused=True)
    body = _forecast(w, "90")
    payday = date.fromisoformat(body["budget_projection"]["payday"])
    drops = _drops(body)
    assert drops[_eve(payday)] == Decimal("160")
    assert drops[_eve(_add_months(payday, 1))] == Decimal("160") + Decimal("700")


def test_removed_budgets_dont_count(w):
    _owners_budgets(w)
    groceries = next(b for b in w.get().json()["budgets"] if b["category"] == "Groceries")["id"]
    w.delete(groceries)
    body = _forecast(w, "90")
    assert _drops(body)[_eve(date.fromisoformat(body["budget_projection"]["payday"]))] == Decimal("160")


def test_nothing_left_means_no_drop_this_cycle(w):
    w.create("Eating out", 40)  # 40 spent
    body = _forecast(w, "90")
    payday = date.fromisoformat(body["budget_projection"]["payday"])
    drops = _drops(body)
    assert drops[_eve(payday)] == 0
    assert drops[_eve(_add_months(payday, 1))] == Decimal("40")


def test_an_overspent_budget_counts_as_nothing_left(w):
    """sec: max(0, limit - spent), so overspending never raises the line."""
    w.create("Eating out", 30)   # 40 spent: 10 over
    w.create("Groceries", 100)   # 80 spent: 20 left
    body = _forecast(w, "90")
    assert _drops(body)[_eve(date.fromisoformat(body["budget_projection"]["payday"]))] == Decimal("20")


def test_unbudgeted_spending_never_moves_the_line(w):
    w.create("Eating out", 200)
    before = _strip(w)
    _spend(w, "500.00", "Bills")
    assert _strip(w) == before


def test_no_budgets_no_projection(w):
    body = _forecast(w)
    assert (body["budget_projection"], body["budget_projection_reason"]) == (None, "no_budgets")


def test_only_paused_budgets_no_projection(w):
    budget_id = w.create("Eating out", 200).json()["id"]
    w.patch(budget_id, paused=True)
    body = _forecast(w)
    assert (body["budget_projection"], body["budget_projection_reason"]) == (None, "no_budgets")


def test_no_payday_no_projection(client, db_session):
    w = World(client, db_session, email="nopayday@example.com")

    def drop_payday():
        from app.models import CommitmentRule
        w.db.query(CommitmentRule).filter(CommitmentRule.direction == "income").delete()
        w.db.commit()
    w.history()
    w.as_user(drop_payday)
    w.create("Eating out", 150)
    body = _forecast(w)
    assert (body["budget_projection"], body["budget_projection_reason"]) == (None, "no_payday")


def test_the_strip_has_exactly_the_agreed_fields(w):
    w.create("Eating out", 200)
    # left_raised_by_marks: agreed in T-03-2 section 5, for the dotted-line copy (T-03-6).
    assert set(_strip(w)) == {"payday", "scheduled_balance", "after_budgets_balance", "series", "left_raised_by_marks"}


def test_a_short_horizon_clips_the_line_but_keeps_the_payday_figures(w):
    w.create("Eating out", 150)
    full, week = _strip(w), _strip(w, "7")
    assert week["series"][-1]["date"] <= (TODAY + timedelta(days=7)).isoformat()
    assert (week["scheduled_balance"], week["after_budgets_balance"]) == (
        full["scheduled_balance"], full["after_budgets_balance"])


def test_the_solid_line_and_lowest_point_never_move(w):
    before = _forecast(w)
    w.create("Eating out", 1)
    after = _forecast(w)
    for key in ("timeline", "min_balance", "min_date", "end_balance", "breaches"):
        assert after[key] == before[key]


def test_lowering_a_limit_raises_the_line_by_the_difference(w):
    """BC11: accepted (display only, informed preview)."""
    budget_id = w.create("Eating out", 300).json()["id"]
    after = Decimal(_strip(w)["after_budgets_balance"])
    w.patch(budget_id, limit_pounds=50)
    assert Decimal(_strip(w)["after_budgets_balance"]) == after + Decimal("250")


def test_on_the_day_before_payday_today_has_the_full_drop(client, db_session):
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
    body = _forecast(w, "30")
    strip = body["budget_projection"]
    assert strip["payday"] == (TODAY + timedelta(days=1)).isoformat()
    assert _drops(body)[TODAY.isoformat()] == Decimal(strip["scheduled_balance"]) - Decimal(
        strip["after_budgets_balance"])


def test_put_leaves_a_paused_budget_paused(w):
    """ux on #157: Edit all and Suggest again (PUT /budgets) change the limit
    only; a paused budget stays paused (and out of the line)."""
    budget_id = w.create("Eating out", 300).json()["id"]
    w.create("Groceries", 400)
    w.patch(budget_id, paused=True)
    r = w.put([{"category": "Eating out", "limit_pounds": 120}, {"category": "Groceries", "limit_pounds": 400}])
    assert r.status_code == 200, r.text
    eating = next(b for b in r.json()["budgets"] if b["category"] == "Eating out")
    assert (eating["paused"], eating["limit_pounds"], eating["status"]) == (True, 120, None)


def test_the_single_budget_lookup_is_a_404_if_gone(w):
    """sec's low nit on #150: the helper falls back to 404, never a 500."""
    import uuid

    from app.routers import budgets as router

    with pytest.raises(Exception) as err:
        w.as_user(lambda: router._one(w.db, w.user, uuid.uuid4()))
    assert getattr(err.value, "status_code", None) == 404


def test_a_longer_horizon_reads_the_paydays_no_more_often(w, monkeypatch):
    """eng-a on #170: the later cycles come from one read of the payday
    commitment, stepped in memory, not one lookup per cycle."""
    from app.services.analytics import commitments

    calls = []
    real = commitments._payday_incomes

    def counted(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)
    monkeypatch.setattr(commitments, "_payday_incomes", counted)
    w.create("Eating out", 200)
    _forecast(w, "30")
    short = len(calls)
    calls.clear()
    _forecast(w, "365")
    assert len(calls) <= short


# --- commitments inside budgets (T-24-3b; sec's T-24-3 criteria) ---------------
# A budgeted category's commitment instalments are already on the solid line
# (the forecast schedules them), so the dotted line subtracts, per budget,
# only what the instalments leave of it: this cycle max(0, limit - spent -
# instalments due by the eve), each later cycle max(0, limit - that cycle's
# instalments). The instalments are the forecast's own (one held call, the
# same window), never GET /budgets' coming_up.

from tests.integration.test_budget_commitments import KIT, _weekly, bill  # noqa: E402,F401


def _events(body, label, after: date, until: date) -> Decimal:
    """What the solid line schedules for `label` in (after, until]."""
    return sum((-Decimal(str(e["amount"])) for p in body["timeline"] for e in p["events"]
                if e.get("label") == label and after.isoformat() < p["date"] <= until.isoformat()), Decimal(0))


def test_this_cycle_nets_off_the_instalments_the_forecast_schedules(w):
    _weekly(w)  # £16 a week in Eating out: 3 paid this cycle, the next in 2 days
    w.create("Eating out", 200)
    body = _forecast(w, "90")
    strip = body["budget_projection"]
    payday = date.fromisoformat(strip["payday"])
    due = _events(body, KIT, TODAY, payday - timedelta(days=1))
    assert due > 0
    left = Decimal("200") - Decimal("88.00") - due  # £40 purchases + 3 x £16 paid
    assert _drops(body)[_eve(payday)] == left
    assert Decimal(strip["after_budgets_balance"]) == Decimal(strip["scheduled_balance"]) - left


def test_each_budget_nets_only_its_own_instalments(w):
    """sec: £0 left with £50 due, and £100 left with nothing due, subtract
    £100 (per budget, never max(0, total left - total due))."""
    _weekly(w, label="SHOP CLUB", amount="25.00", category="Shopping", paid_days_ago=(23,), next_in=1)
    w.create("Shopping", 120)    # £120 spent: nothing left, £50 due
    w.create("Groceries", 180)   # £80 spent: £100 left
    body = _forecast(w, "90")
    payday = date.fromisoformat(body["budget_projection"]["payday"])
    assert _events(body, "SHOP CLUB", TODAY, payday - timedelta(days=1)) == Decimal("50.00")
    assert _drops(body)[_eve(payday)] == Decimal("100")


def test_a_later_cycle_nets_that_cycles_instalments(w):
    """sec: rent (£950 a month, category Rent) inside a £1,000 Rent budget
    takes £50 off each later cycle, not £1,000: the forecast already has the
    rent (the 2026-10-12 double count)."""
    w.create("Rent", 1000)
    body = _forecast(w, "90")
    payday = date.fromisoformat(body["budget_projection"]["payday"])
    drops = _drops(body)
    assert drops[_eve(payday)] == 0  # £950 paid, £950 due: nothing left to spend
    assert drops[_eve(_add_months(payday, 1))] - drops[_eve(payday)] == Decimal("50")


def test_a_weekly_commitment_nets_the_instalments_of_each_later_cycle(w):
    _weekly(w)
    w.create("Eating out", 200)
    body = _forecast(w, "90")
    payday = date.fromisoformat(body["budget_projection"]["payday"])
    drops = _drops(body)
    for n in (1, 2):
        start, eve = _add_months(payday, n - 1), _add_months(payday, n) - timedelta(days=1)
        if eve.isoformat() not in drops:
            continue
        due = _events(body, KIT, start - timedelta(days=1), eve)
        assert due >= Decimal("64.00")  # 4 or 5 instalments
        assert drops[eve.isoformat()] - drops[_eve(start)] == Decimal("200") - due


@pytest.mark.parametrize("change", ["cut", "dismiss", "raise", "weekly_from_next_cycle"])
def test_a_pending_claude_change_never_raises_the_dotted_line(bill, change):
    """sec probe: whatever Claude changes on a budgeted bill (£300 Phone bill
    due in 5 days, £400 Phone budget, payday in 10), the strip's "after
    budgets" and the dotted line at every cycle's eve are no higher than
    before. "Monthly, due this cycle" to "weekly from next cycle" is the
    case where coming_up (held over this cycle only) would keep £300 the
    3-month forecast no longer schedules, lifting this eve by £300.

    Checked at the eves, not every day: the budget is spread evenly while a
    bill is a lump, so between a bill's date and the eve the dotted line
    follows the solid one, which the held view itself may move (here the
    bill leaves this cycle)."""
    def line():
        body = bill.client.get(f"{API}/analytics/forecast", params={"horizon": "90"}, headers=_bearer(bill.web)).json()
        strip = body["budget_projection"]
        series = {p["date"]: Decimal(p["balance"]) for p in strip["series"]}
        payday = date.fromisoformat(strip["payday"])
        eves = [_eve(_add_months(payday, n)) for n in range(3) if _eve(_add_months(payday, n)) in series]
        return Decimal(strip["after_budgets_balance"]), {d: series[d] for d in eves}
    before_strip, before = line()
    assert len(before) >= 2
    if change == "dismiss":
        bill.claude_dismiss(bill.bill)
    elif change == "weekly_from_next_cycle":
        bill.claude_update(bill.bill, cadence="weekly", next_date=(TODAY + timedelta(days=12)).isoformat())
    else:
        bill.claude_update(bill.bill, amount="100.00" if change == "cut" else "350.00")
    after_strip, after = line()
    assert after_strip <= before_strip
    assert after.keys() == before.keys()
    assert [d for d in after if after[d] > before[d]] == []
