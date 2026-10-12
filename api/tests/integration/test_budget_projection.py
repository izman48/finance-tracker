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


def test_put_leaves_a_paused_budget_paused_and_held(w):
    """ux on #157: Edit all and Suggest again (PUT /budgets) change the limit
    only; a paused budget stays paused and keeps its hold (sec's max rule)."""
    budget_id = w.create("Eating out", 300).json()["id"]
    w.create("Groceries", 400)
    w.patch(budget_id, paused=True)
    held_before = w.get().json()["reconciliation"]["budgets_left"]
    r = w.put([{"category": "Eating out", "limit_pounds": 120}, {"category": "Groceries", "limit_pounds": 400}])
    assert r.status_code == 200, r.text
    eating = next(b for b in r.json()["budgets"] if b["category"] == "Eating out")
    assert (eating["paused"], eating["limit_pounds"], eating["status"]) == (True, 120, None)
    assert w.get().json()["reconciliation"]["budgets_left"] == held_before


# --- commitment payments are never paced (T-09-13; sec's guards) ----------------------------
# A confirmed commitment's stored key can hold last month's bank reference, so
# this month's payment doesn't key-match it and was paced as everyday spending
# (the owner's dotted line fell ~£345 a day). For the pace only, a debit that
# loosely matches a commitment occurrence this cycle (by merchant without
# references and bank codes, or by amount within 2% and 5 days of the due
# date for a commitment of £50 or more) is left out, one debit per occurrence.

def _commitment(w, label, amount, due_days_ago, match_key=None):
    """Confirmed, monthly, due `due_days_ago` this cycle (so next due next month)."""
    from app.models import CommitmentRule
    from app.services.analytics import _add_months

    def make():
        w.db.add(CommitmentRule(user_id=w.user.id, direction="expense", label=label, amount=Decimal(amount),
                                cadence="monthly", next_date=_add_months(TODAY - timedelta(days=due_days_ago), 1),
                                source="detected", status="confirmed", match_key=match_key))
        w.db.commit()
    w.as_user(make)


def _paid(w, merchant, amount, days_ago, category="Bills"):
    from tests.integration.test_transactions_endpoint import _tx
    w.as_user(lambda: _tx(w.db, w.current, amount, TODAY - timedelta(days=days_ago), merchant=merchant, category=category))


def _lines(w):
    strip = _strip(w)
    return Decimal(strip["stick_to_budgets_balance"]), Decimal(strip["current_pace_balance"]), strip["series"]


def _other_at_pace(w):
    return Decimal(w.get().json()["reconciliation"]["other_at_pace"])


RENT_KEY = "expense:jones lang lasall rent 1606landmarke ft"
EE_KEY = "expense:ee limited q42181371737681503 ddr"


def test_rent_with_a_new_reference_moves_neither_line(w):
    w.create("Eating out", 150)
    _commitment(w, "Rent", "2950", 18, match_key=RENT_KEY)
    before = _lines(w)
    _paid(w, "JONES LANG LASALL RENT 1606LANDMARKE STO", "2950.00", 18)
    assert _lines(w) == before


def test_ee_with_a_new_reference_and_amount_matches_by_merchant(w):
    w.create("Eating out", 150)
    _commitment(w, "EE", "68.50", 15, match_key=EE_KEY)
    before = _other_at_pace(w)
    _paid(w, "EE LIMITED Q42181371763503049 DDR", "49.50", 13)
    assert _other_at_pace(w) == before


def test_a_short_merchant_name_never_matches(w):
    """"ee" alone (1 token, 2 characters) is too loose to match on."""
    w.create("Eating out", 150)
    _commitment(w, "EE", "68.50", 15, match_key="expense:ee q42181371737681503 ddr")
    before = _other_at_pace(w)
    _paid(w, "EE Q99999999 DDR", "12.00", 13)
    assert _other_at_pace(w) > before


def test_a_purchase_equal_to_a_commitment_by_chance_isnt_paced(w):
    """Accepted (sec): within 2% and 5 days of a £50+ commitment's due date,
    a one-off purchase is taken for the commitment, once."""
    w.create("Eating out", 150)
    _commitment(w, "Gym", "60", 10)
    before = _other_at_pace(w)
    _paid(w, "CURRYS", "60.00", 10)
    assert _other_at_pace(w) == before


def test_a_second_matching_debit_stays_paced(w):
    w.create("Eating out", 150)
    _commitment(w, "Gym", "60", 10)
    _paid(w, "CURRYS", "60.00", 10)
    once = _other_at_pace(w)
    _paid(w, "ARGOS", "60.00", 9)
    assert _other_at_pace(w) > once


def test_a_second_payment_to_the_same_merchant_stays_paced(w):
    w.create("Eating out", 150)
    _commitment(w, "EE", "68.50", 15, match_key=EE_KEY)
    _paid(w, "EE LIMITED Q42181371763503049 DDR", "49.50", 13)
    once = _other_at_pace(w)
    _paid(w, "EE LIMITED Q42181371799999999 DDR", "20.00", 5)
    assert _other_at_pace(w) > once


def test_a_same_amount_purchase_10_days_from_the_due_date_stays_paced(w):
    w.create("Eating out", 150)
    _commitment(w, "Gym", "60", 15)
    before = _other_at_pace(w)
    _paid(w, "CURRYS", "60.00", 5)
    assert _other_at_pace(w) > before


def test_amount_only_needs_a_commitment_of_at_least_50(w):
    w.create("Eating out", 150)
    _commitment(w, "Streaming", "30", 10)
    before = _other_at_pace(w)
    _paid(w, "CURRYS", "30.00", 10)
    assert _other_at_pace(w) > before


def test_an_owner_shaped_cycle_paces_only_everyday_spending(w):
    """Big commitments early in the cycle, small everyday spending: stick to
    budgets is the scheduled balance less budgets left less everyday
    spending at pace, and current pace isn't pulled down by the bills."""
    w.create("Eating out", 150)
    before = _lines(w)
    _commitment(w, "Rent", "2950", 18, match_key=RENT_KEY)
    _commitment(w, "Council tax", "243", 17, match_key="expense:council tax 7781234 dd")
    _commitment(w, "EE", "68.50", 15, match_key=EE_KEY)
    _paid(w, "JONES LANG LASALL RENT 1606LANDMARKE STO", "2950.00", 18)
    _paid(w, "COUNCIL TAX 7789999 DD", "243.00", 17)
    _paid(w, "EE LIMITED Q42181371763503049 DDR", "49.50", 13)
    assert _lines(w) == before
    strip, rec = _strip(w), w.get().json()["reconciliation"]
    assert Decimal(strip["stick_to_budgets_balance"]) == (
        Decimal(strip["scheduled_balance"]) - Decimal(rec["budgets_left"]) - Decimal(rec["other_at_pace"]))


def test_the_max_rule_still_holds_with_commitment_payments(w):
    budget_id = w.create("Eating out", 150).json()["id"]
    _commitment(w, "Rent", "2950", 18, match_key=RENT_KEY)
    _paid(w, "JONES LANG LASALL RENT 1606LANDMARKE STO", "2950.00", 18)
    stick, headroom = _stick(w), _headroom(w)
    w.patch(budget_id, paused=True)
    assert _stick(w) <= stick and _headroom(w) <= headroom
    w.delete(budget_id)
    assert _stick(w) <= stick and _headroom(w) <= headroom


def test_headroom_is_the_same_on_cashflow_and_the_reconciliation_line(w):
    w.create("Eating out", 150)
    _commitment(w, "Rent", "2950", 18, match_key=RENT_KEY)
    _paid(w, "JONES LANG LASALL RENT 1606LANDMARKE STO", "2950.00", 18)
    assert Decimal(_strip(w)["headroom"]) == Decimal(w.get().json()["reconciliation"]["headroom"])


def test_a_key_matched_commitment_in_a_budgeted_category_is_never_counted(w):
    """AC2: key-matched commitment spending never enters a budget's spend, so
    a part-commitment category can't count a scheduled payment twice."""
    _paid(w, "Corner cafe", "100.00", 3, category="Bills")
    w.create("Bills", 300)
    spent = next(b for b in w.get().json()["budgets"] if b["category"] == "Bills")["spent"]
    _commitment(w, "OCTOPUS ENERGY", "40", 4)
    _paid(w, "OCTOPUS ENERGY", "40.00", 4)
    assert next(b for b in w.get().json()["budgets"] if b["category"] == "Bills")["spent"] == spent
