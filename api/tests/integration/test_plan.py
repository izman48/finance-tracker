"""GET /plan (T-25-2): Money in, Commitments by group, Budgets, Left over.
Synthetic data.

The world (`plan_world`): payday 20 days ago (salary £2,500, received),
rent £950 a month (category Rent, paid 5 days ago, next due in 5), a £16
weekly meal kit in a £150 Eating out budget, a £300 Groceries budget, a
card repaid weekly (£600 owed) and a £300 one-off planned expense in 6 days.
"""
import logging
import uuid
from datetime import timedelta
from decimal import Decimal

import pytest

from app.models import CommitmentLink, CommitmentRule
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


def _groups(p):
    return {g["name"]: g for g in p["commitments"]["groups"]}


def _items(p):
    return [i for g in p["commitments"]["groups"] for i in g["items"]]


def _paid(w, label, amount, days_ago, category):
    w.as_user(lambda: _tx(w.db, w.current, amount, TODAY - timedelta(days=days_ago), merchant=label, category=category))


def test_the_rows_add_up_to_the_penny(w):
    _rule(w, "STREAMLY", "9.99", "expense", 3)
    p = _plan(w)
    m, c, b = p["money_in"], p["commitments"], p["budgets"]
    assert D(p["left_over"]) == D(m["total"]) - D(c["total"]) - D(b["planned_total"])
    assert D(m["total"]) == sum(D(i["amount"]) for i in m["items"])
    assert D(c["total"]) == sum(D(g["total"]) for g in c["groups"])
    for g in c["groups"]:
        assert D(g["total"]) == sum(D(i["amount"]) for i in g["items"])
    assert D(b["planned_total"]) == sum(D(i["planned"]) for i in b["items"])
    for item in b["items"]:
        assert D(item["planned"]) == max(D(item["limit"]), D(item["spent"]) + D(item["coming_up"]))


# --- Money in -------------------------------------------------------------------

def test_money_in_counts_matched_and_expected_income_but_not_late_income(w):
    _rule(w, "Bonus", "400", "income", -10)       # expected 10 days ago, never came: late
    _rule(w, "Side job", "120", "income", 4)      # due before payday
    m = _plan(w)["money_in"]
    by_label = {(i["label"], i["status"]): i for i in m["items"]}
    assert by_label[("Salary", "received")]["transaction_id"] and D(by_label[("Salary", "received")]["amount"]) == 2500
    assert ("Side job", "expected") in by_label
    assert not any(i["label"] == "Bonus" for i in m["items"])
    assert D(m["total"]) == D("2620.00")


def test_money_in_lists_income_credits_by_description_and_leaves_out_transfers_and_refunds(w):
    def credits():
        for merchant, category, account in [
            ("AUNT GIFT", "Income", w.current),              # counts, labelled by description
            ("SHOP REFUND", "Income", w.current),            # a refund
            ("FROM MY SAVINGS", "Transfers", w.current),     # a transfer
            ("COFFEE CO", "Eating out", w.current),          # not categorised Income
        ]:
            _tx(w.db, account, "75.00", TODAY - timedelta(days=3), ttype="credit", merchant=merchant, category=category)
        tx = _tx(w.db, w.current, "60.00", TODAY - timedelta(days=2), ttype="credit", merchant="MOVED IN",
                 category="Income")
        tx.counts_as_override = "transfer"                   # the user marked it a transfer
        _tx(w.db, w.current, "80.00", TODAY - timedelta(days=40), ttype="credit", merchant="OLD GIFT",
            category="Income")                               # last cycle
        w.db.commit()
    w.as_user(credits)
    m = _plan(w)["money_in"]
    labels = [i["label"] for i in m["items"]]
    assert "AUNT GIFT" in labels
    assert not {"SHOP REFUND", "FROM MY SAVINGS", "COFFEE CO", "MOVED IN", "OLD GIFT"} & set(labels)
    assert labels.count("Salary") == 1  # the matched salary credit is not listed again by description
    assert D(m["total"]) == D("2575.00")


# --- Commitments ----------------------------------------------------------------

def test_commitments_group_by_category_with_paid_coming_and_not_seen(w):
    water = _rule(w, "WATER CO", "40", "expense", -10)       # due 10 days ago, no payment
    _rule(w, "STREAMLY", "9.99", "expense", 0)               # due today, not paid yet
    _rule(w, "CLOUDBOX", "4.50", "expense", 3)
    _rule(w, "GYM CLUB", "25", "expense", 2)
    for label, days, category in [("WATER CO", 40, "Utilities"), ("STREAMLY", 30, "Subscriptions"),
                                  ("CLOUDBOX", 27, "Subscriptions"), ("GYM CLUB", 28, "Fitness")]:
        _paid(w, label, {"WATER CO": "40.00", "STREAMLY": "9.99", "CLOUDBOX": "4.50", "GYM CLUB": "25.00"}[label],
              days, category)                                # last cycle's payment gives the category
    groups = _groups(_plan(w))
    bills = groups["Rent & bills"]
    status = {(i["label"], i["status"]): i for i in bills["items"]}
    rent = status[("LANDLORD RENT", "paid")]
    assert rent["date"] == (TODAY - timedelta(days=5)).isoformat() and rent["transaction_id"]
    assert ("LANDLORD RENT", "coming") not in status       # one instalment this cycle, already paid
    assert status[("WATER CO", "not_seen")]["date"] == (TODAY - timedelta(days=10)).isoformat()
    assert status[("WATER CO", "not_seen")]["commitment_id"] == str(water)
    assert D(bills["total"]) == D("990.00")
    subs = groups["Subscriptions"]
    assert {(i["label"], i["status"], i["date"]) for i in subs["items"]} == {
        ("STREAMLY", "coming", TODAY.isoformat()), ("CLOUDBOX", "coming", (TODAY + timedelta(days=3)).isoformat())}
    assert subs["count"] == 2 and D(subs["total"]) == D("14.49")
    assert D(groups["Fitness"]["total"]) == D("25.00")


def test_commitments_hold_no_card_repayments_planned_items_one_offs_or_later_bills(w):
    annual = _rule(w, "ANNUAL CLUB", "120", "expense", 200, cadence="every_n_months")

    def yearly():
        w.db.get(CommitmentRule, annual).interval_months = 12
        w.db.commit()
    w.as_user(yearly)
    _paid(w, "PHONE SHOP", "999.00", 2, "Shopping")          # a one-off purchase
    p = _plan(w)
    labels = {i["label"] for i in _items(p)}
    assert not {"ANNUAL CLUB", "PHONE SHOP", "Sofa", "Card"} & labels
    assert labels == {"LANDLORD RENT"}


def test_a_bill_paid_today_is_paid_and_one_due_today_unpaid_is_coming(w):
    _rule(w, "ENERGY CO", "70", "expense", 0)
    _rule(w, "FIBRE CO", "30", "expense", 0)
    _paid(w, "ENERGY CO", "70.00", 0, "Utilities")
    items = {i["label"]: i["status"] for i in _items(_plan(w))}
    assert items["ENERGY CO"] == "paid" and items["FIBRE CO"] == "coming"


def test_a_holding_linked_commitment_is_savings(w):
    isa = _rule(w, "ISA SAVER", "1", "expense", 4)
    w.db.add(CommitmentLink(user_id=w.user.id, commitment_id=isa, asset_id=uuid.uuid4(), role="contribution",
                            commitment_created=False, created_on=TODAY))
    w.db.commit()
    savings = _groups(_plan(w))["Savings"]
    assert [(i["label"], i["status"], D(i["amount"])) for i in savings["items"]] == [("ISA SAVER", "coming", D("1"))]


def test_a_budgeted_commitment_counts_once_inside_its_budget(w):
    p = _plan(w)
    eating = next(i for i in p["budgets"]["items"] if i["category"] == "Eating out")
    paid = [c for c in eating["commitments"] if c["status"] == "paid"]
    assert [D(c["amount"]) for c in paid] == [D("16.00")] * 3 and all(c["transaction_id"] for c in paid)
    assert D(eating["coming_up"]) == sum(D(c["amount"]) for c in eating["commitments"] if c["status"] == "due")
    assert D(eating["other_purchases"]) == D(eating["spent"]) - D("48.00")
    assert KIT not in {i["label"] for i in _items(p)}


@pytest.mark.parametrize("limit", [500, 3000])
def test_moving_rent_into_a_budget_never_raises_left_over(w, limit):
    before = D(_plan(w)["left_over"])
    assert w.create("Rent", limit).status_code == 201
    after = _plan(w)
    assert D(after["left_over"]) <= before
    assert "Rent & bills" not in _groups(after)


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
def test_a_pending_claude_change_never_raises_left_over(held, change):
    def figures():
        p = held.client.get(f"{API}/plan", headers=_bearer(held.web)).json()
        return D(p["left_over"]), D(p["money_in"]["total"]), D(p["commitments"]["total"])
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


# --- Security -------------------------------------------------------------------

def test_another_users_rows_never_appear(w, client, db_session):
    other = World(client, db_session, email="plan-other@example.com")
    other.history()
    _rule(other, "OTHER USERS GYM", "45", "expense", 3)
    assert "OTHER USERS GYM" not in str(_plan(w))


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
    assert "Eating out" not in caplog.text and "MEAL KIT" not in caplog.text and "330.50" not in caplog.text


# --- Held income (sec on #305) --------------------------------------------------

def _held_income_world(client, db_session, status, amount):
    """A £500 income from PAYER LTD, `status` and `amount` as the rule
    stands; a credit of `amount` already landed 3 days ago."""
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


def _money_in_and_left_over(w):
    p = _plan(w)
    return D(p["money_in"]["total"]), D(p["left_over"])


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


@pytest.mark.parametrize("status, amount, change", [
    ("suggested", "500.00", {"status": "confirmed"}),   # an unkept confirm
    ("confirmed", "1000.00", {"amount": "1000.00"}),     # an unkept raise
])
def test_an_unkept_claude_change_never_counts_a_received_income(client, db_session, status, amount, change):
    w = _held_income_world(client, db_session, status, amount)
    before = _money_in_and_left_over(w)
    _claude(w).claude_update(w.payer, **change)
    assert _money_in_and_left_over(w) == before


def test_an_unkept_claude_relabel_never_lets_another_payers_credit_count(client, db_session):
    """The matcher keys on the label too, so a relabel is held like a raise."""
    w = _held_income_world(client, db_session, "confirmed", "50.00")  # PAYER LTD's credit is too small
    w.as_user(lambda: _tx(db_session, w.current, "500.00", TODAY - timedelta(days=2), ttype="credit",
                          merchant="OTHER CO"))
    before = _money_in_and_left_over(w)
    _claude(w).claude_update(w.payer, label="OTHER CO")
    assert _money_in_and_left_over(w) == before
