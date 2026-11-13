"""GET /plan (T-24-4; ux contract + sec's T-24-4 criteria). Synthetic data.

The world: payday 20 days ago (salary £2,500, received), rent £950 a month
(category Rent, no budget), a £16 weekly meal kit in a £150 Eating out
budget, a £300 Groceries budget, a card repaid weekly in full (£600 owed)
and a £300 one-off planned expense in 6 days.
"""
import logging
from datetime import timedelta
from decimal import Decimal

import pytest

from app.models import CommitmentRule
from app.schemas.plan import FixedItem
from app.services import plan as plan_service
from tests.clock import TODAY
from tests.integration.test_budget_commitments import KIT
from tests.integration.test_budgets_api import API, World
from tests.integration.test_money_out_items import _rule, plan_world
from tests.integration.test_oauth import _bearer
from tests.integration.test_transactions_endpoint import _tx

D = Decimal


def _plan(w):
    r = w.client.get(f"{API}/plan", headers=_bearer(w.web))
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture
def w(client, db_session):
    return plan_world(client, db_session)


def _fixed_items(p):
    return [i for g in p["fixed"]["groups"] for i in g["items"]]


def test_the_lines_add_up_to_the_penny(w):
    p = _plan(w)
    f, b = p["fixed"], p["budgets"]
    assert D(p["not_planned"]) == D(p["income"]["total"]) - D(f["total"]) - D(b["planned_total"])
    assert D(f["total"]) == D(f["paid"]) + D(f["to_pay"]) == sum(D(g["total"]) for g in f["groups"])
    assert D(b["spent"]) == sum(D(i["spent"]) for i in b["items"])
    assert D(b["limits_total"]) == D("450")
    assert D(p["outside_vs_not_planned"]) == D(p["spent_outside_budgets"]) - D(p["not_planned"])
    budget_ids = {c["commitment_id"] for i in b["items"] for c in i["commitments"]}
    assert not budget_ids & {i["commitment_id"] for i in _fixed_items(p)}


def test_income_received_is_the_salary_credit_and_late_income_adds_nothing(w):
    _rule(w, "Bonus", "400", "income", -10)       # expected 10 days ago, never came: late
    _rule(w, "Side job", "120", "income", 4)      # due before payday
    inc = _plan(w)["income"]
    by_label = {(i["label"], i["status"]): i for i in inc["items"]}
    assert by_label[("Salary", "received")]["transaction_id"] and D(by_label[("Salary", "received")]["amount"]) == 2500
    assert ("Side job", "expected") in by_label
    assert not any(i["label"] == "Bonus" for i in inc["items"])
    assert D(inc["total"]) == D("2620.00") and (inc["received_count"], inc["expected_count"]) == (1, 1)


def test_fixed_holds_the_three_sources_each_once(w):
    """sec: commitments, card repayments and planned expenses; what is still
    to pay in Fixed plus budgets' coming up is exactly what the forecast
    schedules going out in (today, eve]."""
    p = _plan(w)
    sources = {g["source"] for g in p["fixed"]["groups"]}
    assert sources == {"commitment", "card_repayment", "planned"}
    rent = next(g for g in p["fixed"]["groups"] if g["category"] == "Rent")
    assert [(i["status"], D(i["amount"])) for i in rent["items"]] == [("paid", D(950)), ("due", D(950))]
    assert rent["items"][0]["transaction_id"]
    forecast = w.client.get(f"{API}/analytics/forecast", params={"horizon": "90"}, headers=_bearer(w.web)).json()
    eve = p["cycle"]["end"]
    out = sum(-D(str(e["amount"])) for t in forecast["timeline"] if TODAY.isoformat() < t["date"] <= eve
              for e in t["events"] if e["kind"] != "income")
    assert out == D(p["fixed"]["to_pay"]) + D(p["budgets"]["coming_up"])


def test_a_budgeted_commitment_sits_under_its_budget_only(w):
    p = _plan(w)
    eating = next(i for i in p["budgets"]["items"] if i["category"] == "Eating out")
    paid = [c for c in eating["commitments"] if c["status"] == "paid"]
    assert [D(c["amount"]) for c in paid] == [D("16.00")] * 3 and all(c["transaction_id"] for c in paid)
    assert all(c["label"] == KIT for c in eating["commitments"])
    assert D(eating["other_purchases"]) == D(eating["spent"]) - D("48.00")
    assert D(eating["coming_up"]) == sum(D(c["amount"]) for c in eating["commitments"] if c["status"] == "due")
    assert not any(i["label"] == KIT for i in _fixed_items(p))


@pytest.mark.parametrize("limit", [500, 3000])
def test_moving_rent_into_a_budget_never_raises_not_planned(w, limit):
    """sec: £950 paid + £950 due; a £500 Rent budget counts at £1,900."""
    before = D(_plan(w)["not_planned"])
    assert w.create("Rent", limit).status_code == 201
    after = _plan(w)
    assert D(after["not_planned"]) <= before
    assert not any(g["category"] == "Rent" for g in after["fixed"]["groups"])


def test_every_payment_is_counted_at_most_once(w):
    """sec: Fixed paid, a budget's spent and spent outside budgets never
    share a payment, and together they are everything budgets measure."""
    p = _plan(w)
    budgets = w.get().json()
    fixed_paid = [i for i in _fixed_items(p) if i["status"] == "paid"]
    in_budgets = {c["transaction_id"] for i in p["budgets"]["items"] for c in i["commitments"] if c["transaction_id"]}
    assert not in_budgets & {i["transaction_id"] for i in fixed_paid}
    commitments_paid = sum(D(i["amount"]) for i in fixed_paid if i["source"] == "commitment")
    nc = budgets["not_counted"]
    assert commitments_paid == D(nc["commitments"]) + D(nc["commitments_no_category"])
    assert D(p["budgets"]["spent"]) + D(p["spent_outside_budgets"]) == D(budgets["total_spent"])


@pytest.fixture
def held(client, db_session):
    """sec's world: a £300 bill due in 5 days (no budget), payday in 10,
    and a £120 side income due in 4."""
    from tests.integration.test_no_claude_raise import World as BillWorld
    world = BillWorld(client, db_session, email="plan-held@example.com")

    def payday():
        db_session.get(CommitmentRule, world.salary).is_payday = True
        db_session.commit()
    world.as_user(payday)
    world.side = _rule(world, "Side job", "120", "income", 4)
    return world


@pytest.mark.parametrize("change", ["cut", "dismiss", "raise_income"])
def test_a_pending_claude_change_never_raises_not_planned(held, change):
    def figures():
        p = held.client.get(f"{API}/plan", headers=_bearer(held.web)).json()
        return D(p["not_planned"]), D(p["income"]["total"]), D(p["fixed"]["total"])
    before = figures()
    if change == "dismiss":
        held.claude_dismiss(held.bill)
    elif change == "cut":
        held.claude_update(held.bill, amount="100.00")
    else:
        held.claude_update(held.side, amount="900.00")
    after = figures()
    assert before[1] == D("120.00") and before[2] == D("300.00")  # both are in this cycle
    assert after[0] <= before[0] and after[1] <= before[1] and after[2] >= before[2]


def test_another_users_rows_never_appear(w, client, db_session):
    other = World(client, db_session, email="plan-other@example.com")
    other.history()
    _rule(other, "OTHER USERS GYM", "45", "expense", 3)
    p = _plan(w)
    assert "OTHER USERS GYM" not in str(p)


def test_plan_is_web_only(client, db_session):
    from tests.integration.test_oauth import READ, _connect
    _, _, tokens = _connect(client, scopes=(READ,), email="plan-mcp@example.com")
    r = client.get(f"{API}/plan", headers=_bearer(tokens["access_token"]))
    assert r.status_code in (401, 403)


def test_an_error_returns_the_generic_message_and_logs_the_type_only(w, monkeypatch, caplog):
    def boom(db, user):
        raise ValueError("Eating out £330.50 MEAL KIT CO")
    monkeypatch.setattr("app.routers.plan.plan", boom)
    with caplog.at_level(logging.ERROR):
        r = w.client.get(f"{API}/plan", headers=_bearer(w.web))
    assert r.status_code == 500 and r.json() == {"detail": "Couldn't load your plan."}
    assert "ValueError" in caplog.text
    assert "Eating out" not in caplog.text and "MEAL KIT" not in caplog.text and "330" not in caplog.text


def test_a_group_lists_at_most_fifty_items_and_counts_them_all():
    items = [FixedItem(source="commitment", label=f"Bill {n}", due_date=TODAY, amount=D("1.00"), status="due")
             for n in range(60)]
    group = plan_service._group("commitment", "Bills", items)
    assert len(group.items) == 50 and group.count == 60 and group.total == D("60.00")


def test_a_bill_due_earlier_this_cycle_and_unpaid_is_still_to_pay(w):
    """eng-a on #296: a £40 monthly water bill last due 10 days ago (inside
    this cycle) with no payment stays in Fixed as due, so Not planned isn't
    overstated. Rent, paid, is not listed twice."""
    _rule(w, "WATER CO", "40", "expense", 20)  # monthly: last due 10 days ago
    p = _plan(w)
    water = [i for i in _fixed_items(p) if i["label"] == "WATER CO"]
    assert [(i["status"], i["due_date"]) for i in water] == [("due", (TODAY - timedelta(days=10)).isoformat())]
    rent = next(g for g in p["fixed"]["groups"] if g["category"] == "Rent")
    assert [i["status"] for i in rent["items"]] == ["paid", "due"]


def _held_income_world(client, db_session, status, amount):
    """sec on #305: a £500 income from PAYER LTD, `status` and `amount` as
    the rule stands; a credit of `amount` already landed 3 days ago."""
    world = plan_world(client, db_session)

    def make():
        rule = CommitmentRule(user_id=world.user.id, direction="income", label="PAYER LTD", amount=D("500"),
                              cadence="monthly", next_date=TODAY - timedelta(days=3), source="detected", status=status)
        db_session.add(rule)
        db_session.commit()
        rule.created_at = rule.created_at - timedelta(days=60)
        _tx(db_session, world.current, amount, TODAY - timedelta(days=3), ttype="credit", merchant="PAYER LTD")
        db_session.commit()
        return rule.id
    world.payer = world.as_user(make)
    return world


def _income_and_not_planned(w):
    p = _plan(w)
    return D(p["income"]["total"]), D(p["not_planned"])


def test_an_unkept_claude_confirm_never_counts_a_received_income(client, db_session):
    w = _held_income_world(client, db_session, "suggested", "500.00")
    before = _income_and_not_planned(w)
    _claude(w).claude_update(w.payer, status="confirmed")
    assert _income_and_not_planned(w) == before


def test_an_unkept_claude_raise_never_lets_a_larger_credit_count(client, db_session):
    w = _held_income_world(client, db_session, "confirmed", "1000.00")
    before = _income_and_not_planned(w)
    _claude(w).claude_update(w.payer, amount="1000.00")
    assert _income_and_not_planned(w) == before


def _claude(w):
    """Claude, connected to the Plan world's user with planning writes."""
    from tests.integration.test_claude_income_parity import PLANNING
    from tests.integration.test_oauth import READ, _connect
    _, _, tokens = _connect(w.client, scopes=(READ, PLANNING), email="plan@example.com")

    class Claude:
        n = 0

        def claude_update(self, cid, **fields):
            self.n += 1
            r = w.client.post(f"{API}/planning/commitments/{cid}/update", headers=_bearer(tokens["access_token"]),
                              json={**fields, "dry_run": False, "idempotency_key": f"plan-held-{self.n:04d}"})
            assert r.status_code == 200, r.text
    return Claude()


def test_an_unkept_claude_relabel_never_lets_another_payers_credit_count(client, db_session):
    """The matcher keys on the label too, so a relabel is held like a raise."""
    w = _held_income_world(client, db_session, "confirmed", "50.00")  # PAYER LTD's credit is too small
    w.as_user(lambda: _tx(db_session, w.current, "500.00", TODAY - timedelta(days=2), ttype="credit",
                          merchant="OTHER CO"))
    before = _income_and_not_planned(w)
    _claude(w).claude_update(w.payer, label="OTHER CO")
    assert _income_and_not_planned(w) == before


def test_each_budget_carries_what_it_counts_and_they_add_up(w):
    """ux on #297: each Budgets row shows max(limit, spent + coming up), so
    the rows sum to the Budgets line; the browser computes none of it."""
    w.as_user(lambda: _tx(w.db, w.current, "200.00", TODAY - timedelta(days=1), merchant="Shop Eating out",
                          category="Eating out"))  # takes Eating out past its £150 limit
    b = _plan(w)["budgets"]
    for item in b["items"]:
        assert D(item["planned"]) == max(D(item["limit"]), D(item["spent"]) + D(item["coming_up"]))
    assert sum(D(i["planned"]) for i in b["items"]) == D(b["planned_total"])
    eating = next(i for i in b["items"] if i["category"] == "Eating out")
    assert D(eating["planned"]) > D(eating["limit"])
