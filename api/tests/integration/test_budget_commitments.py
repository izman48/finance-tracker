"""Commitments inside their budget category (T-24-3a; sec's T-24-3 criteria).

A commitment's payment counts in its category's budget when that category
has an active budget, only once it is paid. Its instalments still to come
this cycle are `coming_up`: taken from the held scheduled outflows the
forecast uses, never added to `spent`, `over_by` or the status. With no
budget on its category it stays under "Not counted here" as before.
Synthetic merchants and amounts only.
"""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.models import CommitmentRule
from tests.clock import TODAY
from tests.integration.test_budgets_api import World
from tests.integration.test_oauth import _bearer
from tests.integration.test_transactions_endpoint import _tx

KIT = "MEAL KIT CO"


def _weekly(w, label=KIT, amount="16.00", category="Eating out", paid_days_ago=(5, 12, 19), next_in=2):
    """A weekly commitment and its payments (category as the bank gave it)."""
    def make():
        for days in paid_days_ago:
            _tx(w.db, w.current, amount, TODAY - timedelta(days=days), merchant=label, category=category)
        rule = CommitmentRule(user_id=w.user.id, direction="expense", label=label, amount=Decimal(amount),
                              cadence="weekly", next_date=TODAY + timedelta(days=next_in),
                              source="manual", status="confirmed")
        w.db.add(rule)
        w.db.commit()
        return rule.id
    return w.as_user(make)


def _budgets(w) -> dict:
    return w.client.get("/api/v1/budgets", headers=_bearer(w.web)).json()


def _row(w, category="Eating out"):
    body = _budgets(w)
    return body, next(b for b in body["budgets"] if b["category"] == category)


def _due(first: date, end: date, step=7) -> list[date]:
    out, d = [], first
    while d <= end:
        out.append(d)
        d += timedelta(days=step)
    return out


@pytest.fixture
def w(client, db_session):
    world = World(client, db_session)
    world.history()  # Eating out £40 this cycle; rent £950 (category Rent), next due in 5 days
    return world


def test_paid_instalments_count_and_the_rest_are_coming_up(w):
    kit = _weekly(w)
    w.create("Eating out", 150)
    body, row = _row(w)
    end = date.fromisoformat(body["cycle"]["end"])
    due = _due(TODAY + timedelta(days=2), end)
    assert Decimal(row["spent"]) == Decimal("88.00")  # £40 purchases + 3 x £16 paid
    coming = row["coming_up"]
    assert Decimal(coming["amount"]) == Decimal("16.00") * len(due)
    assert (coming["commitment_count"], coming["instalment_count"]) == (1, len(due))
    assert [(i["commitment_id"], i["label"], i["due_date"], Decimal(i["amount"])) for i in coming["items"]] == [
        (str(kit), KIT, d.isoformat(), Decimal("16.00")) for d in due]
    # Coming up is a hint: spent, over_by and status are as if it weren't there.
    assert Decimal(row["over_by"]) == 0 and row["status"] != "over"
    assert Decimal(body["not_counted"]["commitments"]) == Decimal("950.00")  # rent: no budget


def test_with_no_budget_on_its_category_a_commitment_stays_not_counted(w):
    _weekly(w)
    w.create("Groceries", 300)
    body, row = _row(w, "Groceries")
    assert Decimal(body["not_counted"]["commitments"]) == Decimal("998.00")  # rent + 3 x £16, as today
    assert Decimal(row["coming_up"]["amount"]) == 0 and row["coming_up"]["items"] == []
    assert Decimal(body["other_spending"]) == Decimal("160.00")  # Eating out £40 + Shopping £120, no kit


def test_a_paused_budget_counts_no_commitment(w):
    _weekly(w)
    budget_id = w.create("Eating out", 150).json()["id"]
    w.patch(budget_id, paused=True)
    body, row = _row(w)
    assert Decimal(row["spent"]) == Decimal("40.00") and row["coming_up"]["items"] == []
    assert Decimal(body["not_counted"]["commitments"]) == Decimal("998.00")


def test_over_by_payday_adds_coming_up_but_over_by_does_not(w):
    _weekly(w)
    w.create("Eating out", 90)
    _, row = _row(w)
    coming = Decimal(row["coming_up"]["amount"])
    assert Decimal(row["over_by"]) == 0
    assert Decimal(row["over_by_payday"]) == max(Decimal(0), Decimal("88.00") + coming - 90)


def test_spent_exactly_at_the_limit_is_budget_used(w):
    _weekly(w)
    w.create("Eating out", 88)
    _, row = _row(w)
    assert row["status"] == "budget_used"
    w.create("Groceries", 300)
    assert _row(w, "Groceries")[1]["status"] != "budget_used"


def test_a_due_date_after_payday_or_a_zero_amount_rule_adds_nothing(w):
    """B-34: a key-only £0 rule's payments count in the budget, and it
    invents nothing coming up; a bill due after payday isn't coming up."""
    _weekly(w, label="VEG BOX", amount="0.00", paid_days_ago=(3,))
    w.as_user(lambda: _tx(w.db, w.current, "9.00", TODAY - timedelta(days=3), merchant="VEG BOX",
                          category="Eating out"))
    _weekly(w, label="SUPPER CLUB", amount="30.00", paid_days_ago=(), next_in=45)
    w.create("Eating out", 150)
    _, row = _row(w)
    assert Decimal(row["spent"]) == Decimal("49.00")  # £40 + the £9 VEG BOX payment
    assert row["coming_up"]["items"] == []


def test_items_are_capped_at_five_and_counted_in_full(w):
    for n in range(3):
        _weekly(w, label=f"LUNCH CLUB {chr(65 + n)}", amount="5.00", paid_days_ago=(4,), next_in=1)
    w.create("Eating out", 150)
    body, row = _row(w)
    end = date.fromisoformat(body["cycle"]["end"])
    due = _due(TODAY + timedelta(days=1), end)
    coming = row["coming_up"]
    assert (coming["commitment_count"], coming["instalment_count"]) == (3, 3 * len(due))
    assert len(coming["items"]) == min(5, 3 * len(due))
    assert Decimal(coming["amount"]) == Decimal("5.00") * 3 * len(due)
    assert [i["due_date"] for i in coming["items"]] == sorted(i["due_date"] for i in coming["items"])


def test_another_users_commitments_never_appear(client, db_session):
    a = World(client, db_session, email="a@example.com")
    a.history()
    b = World(client, db_session, email="b@example.com")
    b.history()
    _weekly(b)
    mine = _weekly(a, amount="7.00")
    a.create("Eating out", 150)
    _, row = _row(a)
    assert {i["commitment_id"] for i in row["coming_up"]["items"]} == {str(mine)}
    assert Decimal(row["spent"]) == Decimal("61.00")  # £40 + 3 x £7


def test_a_budget_can_be_set_on_a_category_that_is_mostly_commitments(w):
    """The covered-category block is lifted; safe to spend and the forecast
    don't move when it is."""
    def figures():
        s = w.client.get("/api/v1/analytics/summary", headers=_bearer(w.web)).json()
        f = w.client.get("/api/v1/analytics/forecast", headers=_bearer(w.web)).json()
        return s["safe_to_spend"], s["savable"], f["end_balance"], f["min_balance"]
    before = figures()
    assert w.create("Rent", 1000).status_code == 201
    _, row = _row(w, "Rent")
    assert Decimal(row["spent"]) == Decimal("950.00")
    assert Decimal(row["coming_up"]["amount"]) == Decimal("950.00")
    assert figures() == before


# --- the held view: coming up is what the forecast schedules (sec) -----------

@pytest.fixture
def bill(client, db_session):
    """Salary in 10 days (payday), a £300 phone bill due in 5, paid last
    month under category Phone, and a £400 Phone budget."""
    from tests.integration.test_no_claude_raise import World as BillWorld
    from tests.integration.test_transactions_endpoint import _account

    world = BillWorld(client, db_session, email="coming-up@example.com")
    world.as_user(lambda: _tx(db_session, _account(db_session, world.user.id, name="Current", balance="900"),
                              "300.00", TODAY - timedelta(days=25), merchant="Phone bill", category="Phone"))
    r = client.post("/api/v1/budgets", json={"category": "Phone", "limit_pounds": 400}, headers=_bearer(world.web))
    assert r.status_code == 201, r.text
    return world


def _forecast_bill(w) -> list[tuple[str, Decimal]]:
    f = w.client.get("/api/v1/analytics/forecast", headers=_bearer(w.web)).json()
    end = _budgets(w)["cycle"]["end"]
    return [(p["date"], -Decimal(str(e["amount"]))) for p in f["timeline"] for e in p["events"]
            if e.get("commitment_id") == str(w.bill) and p["date"] <= end]


def _coming(w) -> list[tuple[str, Decimal]]:
    _, row = _row(w, "Phone")
    return [(i["due_date"], Decimal(i["amount"])) for i in row["coming_up"]["items"]]


def test_coming_up_is_the_forecasts_instalments(bill):
    assert _coming(bill) == _forecast_bill(bill) == [((TODAY + timedelta(days=5)).isoformat(), Decimal("300.00"))]


@pytest.mark.parametrize("change", ["cut", "dismiss", "raise"])
def test_a_pending_claude_change_never_lowers_coming_up(bill, change):
    before = _coming(bill)
    if change == "dismiss":
        bill.claude_dismiss(bill.bill)
    else:
        bill.claude_update(bill.bill, amount="100.00" if change == "cut" else "350.00")
    held = _coming(bill)
    assert held == _forecast_bill(bill)
    assert sum(a for _, a in held) >= sum(a for _, a in before)


def test_a_bill_claude_confirms_without_a_keep_moves_no_spending_out(client, db_session, bill):
    """B-26 not made worse: in a budgeted category a commitment's payment
    counts either way, so Claude confirming one hides nothing."""
    def suggested():
        from tests.integration.test_transactions_endpoint import _account
        _tx(db_session, _account(db_session, bill.user.id, name="Second", balance="10"), "45.00",
            TODAY - timedelta(days=2), merchant="TOP UP CO", category="Phone")
        rule = CommitmentRule(user_id=bill.user.id, direction="expense", label="TOP UP CO", amount=Decimal("45"),
                              cadence="monthly", next_date=TODAY + timedelta(days=28), source="detected",
                              status="suggested")
        db_session.add(rule)
        db_session.commit()
        return rule.id
    rule_id = bill.as_user(suggested)
    spent = _row(bill, "Phone")[1]["spent"]
    bill.claude_update(rule_id, status="confirmed")
    assert _row(bill, "Phone")[1]["spent"] == spent == "45.00"


def test_a_bill_linked_to_a_loan_or_holding_adds_nothing_coming_up(bill, db_session):
    """B-34: a linked rule's payments are key-only matches; nothing is
    invented for it, though the forecast still schedules it."""
    import uuid

    from app.models import CommitmentLink

    db_session.add(CommitmentLink(user_id=bill.user.id, commitment_id=bill.bill, asset_id=uuid.uuid4(),
                                  role="contribution", commitment_created=False, created_on=TODAY))
    db_session.commit()
    assert _coming(bill) == [] and _forecast_bill(bill) != []


def test_a_bill_the_forecast_drops_for_its_card_repayment_is_not_coming_up(bill, db_session):
    """sec: a card-tied bill the larger card repayment replaces (`_card_ties`)."""
    from app.models import Account, AccountSetting, BankConnection

    def card_tie():
        conn = BankConnection(user_id=bill.user.id, provider_id="ob-amex", provider_name="AMEX",
                              access_token="t", refresh_token="r")
        db_session.add(conn)
        db_session.flush()
        card = Account(user_id=bill.user.id, bank_connection_id=conn.id, external_id="amex-coming-up",
                       provider_name="AMEX", account_type="CREDIT_CARD", display_name="Card",
                       current_balance=Decimal("1500.00"))
        db_session.add(card)
        db_session.flush()
        db_session.add(AccountSetting(user_id=bill.user.id, account_id=card.id, role="credit",
                                      repayment_strategy="full_balance", repayment_cadence="monthly",
                                      repayment_day=(TODAY + timedelta(days=7)).day))  # after the bill, before payday
        rule = db_session.get(CommitmentRule, bill.bill)
        rule.card_account_id, rule.card_link_source = card.id, "user"
        db_session.commit()
    bill.as_user(card_tie)
    assert _forecast_bill(bill) == [] and _coming(bill) == []


def test_suggest_measures_a_commitment_the_way_the_budget_counts_it(w):
    """eng-b on #294: Suggest and Past cycles must agree on a cycle's spend,
    so a category's paid commitments are in its suggested figures too."""
    def last_cycles():
        rows = w.suggest().json()["suggestions"]
        return [Decimal(c["spent"]) for c in next(s for s in rows if s["category"] == "Eating out")["last_cycles"]]
    before = last_cycles()
    _weekly(w, amount="5.00", paid_days_ago=(26, 33, 40))  # three instalments in the last complete cycle
    after = last_cycles()
    assert after[-1] == before[-1] + Decimal("15.00")
    assert after[:-1] == before[:-1]
