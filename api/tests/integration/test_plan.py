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
from tests.integration.test_budget_commitments import KIT, _weekly
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


def test_money_in_lists_income_credits_the_user_chose_and_leaves_out_defaults_transfers_and_refunds(w):
    """sec on #307: the provider files every credit as Income, so only a
    category the user chose (by hand, or by one of his own rules) counts."""
    def credits():
        from app.models import CategoryRule, RulePack
        own, shared = RulePack(user_id=w.user.id, name="Mine"), RulePack(user_id=w.user.id, name="Shared",
                                                                          imported_from="Someone's pack")
        w.db.add_all([own, shared])
        w.db.flush()
        for pattern, pack, source in [("SISTER", own, "manual"), ("PARTNER", shared, "imported")]:
            w.db.add(CategoryRule(user_id=w.user.id, pack_id=pack.id, pattern=pattern, match_type="contains",
                                  match_field="any", category="Income", source=source))
        for merchant, category, locked in [
            ("AUNT GIFT", "Income", True),          # set by hand: counts, labelled by description
            ("SISTER RENT", "Income", False),       # a rule in a pack he owns says Income: counts
            ("PARTNER PAY", "Income", False),       # only an imported pack's rule says so
            ("SHOP CO", "Income", False),           # the provider's default: a refund in disguise
            ("SHOP REFUND", "Income", True),        # a refund
            ("FROM MY SAVINGS", "Transfers", True),  # a transfer
        ]:
            tx = _tx(w.db, w.current, "75.00", TODAY - timedelta(days=3), ttype="credit", merchant=merchant,
                     category=category)
            tx.category_locked = locked
        moved = _tx(w.db, w.current, "60.00", TODAY - timedelta(days=2), ttype="credit", merchant="MOVED IN",
                    category="Income")
        moved.category_locked, moved.counts_as_override = True, "transfer"   # the user marked it a transfer
        w.db.commit()
    w.as_user(credits)
    labels = [i["label"] for i in _plan(w)["money_in"]["items"]]
    assert sorted(labels) == ["AUNT GIFT", "SISTER RENT", "Salary"]


def test_an_income_credit_that_is_a_confirmed_income_counts_once(w):
    """eng-a on #307: the salary credit categorised Income is listed once, and
    an income paid early (before its due date) is not also still expected."""
    _rule(w, "Side job", "120", "income", 2)

    def categorise():
        from app.models import Transaction
        for tx in w.db.query(Transaction).filter(Transaction.transaction_type == "credit").all():
            tx.category, tx.category_locked = "Income", True     # the salary credit
        early = _tx(w.db, w.current, "120.00", TODAY, ttype="credit", merchant="Side job", category="Income")
        early.category_locked = True                             # paid early
        w.db.commit()
    w.as_user(categorise)
    m = _plan(w)["money_in"]
    assert [i["label"] for i in m["items"]].count("Salary") == 1
    assert [i["label"] for i in m["items"]].count("Side job") == 1
    assert D(m["total"]) == D("2620.00")


def test_an_income_paid_in_two_credits_counts_each_once(w):
    """A payer splitting one income ("MUM AND DAD RENT" + "... GIFT"): both
    credits are that income, categorised Income or not."""
    def make():
        rule = CommitmentRule(user_id=w.user.id, direction="income", label="MUM AND DAD", amount=D("300"),
                              cadence="monthly", next_date=TODAY - timedelta(days=3), source="manual", status="confirmed")
        w.db.add(rule)
        w.db.commit()
        rule.created_at = rule.created_at - timedelta(days=60)
        for merchant, amount in [("MUM AND DAD RENT", "200.00"), ("MUM AND DAD GIFT", "100.00")]:
            tx = _tx(w.db, w.current, amount, TODAY - timedelta(days=3), ttype="credit", merchant=merchant,
                     category="Income")
            tx.category_locked = True
        w.db.commit()
    w.as_user(make)
    m = _plan(w)["money_in"]
    assert D(m["total"]) == D("2800.00")


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


def test_a_late_payment_for_last_cycle_does_not_take_this_cycles_instalment(w):
    """sec on #307: due 25 days ago, paid 18 days ago (this cycle): this
    cycle's instalment, due in 5 days, is still coming."""
    _rule(w, "WATER CO", "40", "expense", 5)
    _paid(w, "WATER CO", "40.00", 18, "Utilities")
    water = [(i["status"], i["date"]) for i in _items(_plan(w)) if i["label"] == "WATER CO"]
    assert water == [("paid", (TODAY - timedelta(days=18)).isoformat()), ("coming", (TODAY + timedelta(days=5)).isoformat())]


def test_each_payment_lands_in_exactly_one_of_commitments_or_a_budget(w):
    """sec on #307: a payment goes by its own category, as budget spend
    counts it. A veg box (latest payment Groceries, so its category is the
    budgeted Groceries) paid once as Shopping: that payment is a commitment."""
    _weekly(w, label="VEG BOX", amount="10.00", category="Groceries", paid_days_ago=(3,), next_in=4)
    _paid(w, "VEG BOX", "10.00", 10, "Shopping")
    p = _plan(w)
    veg = [(i["status"], i["date"]) for i in _items(p) if i["label"] == "VEG BOX"]
    assert veg == [("paid", (TODAY - timedelta(days=10)).isoformat())]  # its coming ones are in Groceries
    groceries = next(b for b in p["budgets"]["items"] if b["category"] == "Groceries")
    assert [(c["status"], c["date"]) for c in groceries["commitments"] if c["label"] == "VEG BOX"][0] == (
        "paid", (TODAY - timedelta(days=3)).isoformat())
    paid_ids = [i["transaction_id"] for i in _items(p) if i["status"] == "paid"] + [
        c["transaction_id"] for b in p["budgets"]["items"] for c in b["commitments"] if c["status"] == "paid"]
    assert len(paid_ids) == len(set(paid_ids))
    nc = w.get().json()["not_counted"]
    assert sum(D(i["amount"]) for i in _items(p) if i["status"] == "paid") == D(nc["commitments"]) + D(
        nc["commitments_no_category"])


def test_a_holding_linked_commitment_is_savings_and_a_contribution_filed_as_a_transfer_pays_it(w):
    isa = _rule(w, "ISA SAVER", "1", "expense", 4)
    pension = _rule(w, "PENSION CO", "50", "expense", -2)
    for cid in (isa, pension):
        w.db.add(CommitmentLink(user_id=w.user.id, commitment_id=cid, asset_id=uuid.uuid4(), role="contribution",
                                commitment_created=False, created_on=TODAY))
    w.db.commit()
    _paid(w, "PENSION CO", "50.00", 1, "Transfers")
    savings = _groups(_plan(w))["Savings"]
    assert [(i["label"], i["status"], D(i["amount"])) for i in savings["items"]] == [
        ("PENSION CO", "paid", D("50")), ("ISA SAVER", "coming", D("1"))]


def test_a_bill_tied_to_a_card_is_the_card_repayment_and_stays_out(w):
    """eng-a on #307: a "DD to card" commitment tied to a card with a
    repayment config is that card's repayment, so not a commitment here."""
    from app.models import Account
    tied = _rule(w, "CARD DIRECT DEBIT", "200", "expense", 3)

    def tie():
        card = w.db.query(Account).filter_by(user_id=w.user.id, account_type="CREDIT_CARD").one()
        rule = w.db.get(CommitmentRule, tied)
        rule.card_account_id, rule.card_link_source = card.id, "user"
        w.db.commit()
    w.as_user(tie)
    assert "CARD DIRECT DEBIT" not in {i["label"] for i in _items(_plan(w))}


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
