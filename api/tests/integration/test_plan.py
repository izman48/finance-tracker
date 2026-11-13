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
