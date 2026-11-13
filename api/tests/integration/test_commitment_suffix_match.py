"""A payment matches its commitment once bank suffixes are ignored, and only
when the amount is close (T-25-1). Synthetic payees and amounts (public repo).

Shapes seen on real accounts: rent set up from a faster payment ("... FT")
and then paid by standing order ("... STO"); a direct debit set up from its
first collection ("... FIRST DDR PAYMENT DDR"); a weekly card payment whose
date phrase changes; a merchant that bills a subscription and a phone under
one descriptor; a refund from that merchant; an income paid by bank giro
credit. Each consumer of the one matcher sees the same answer.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.core import user_crypto
from app.models import Account, CommitmentRule, User
from app.services.analytics.common import _d
from app.services import plan as plan_service
from app.services.analytics.late_income import income_payments, late_incomes
from app.services.budget_spend import budget_spend
from tests.clock import TODAY
from tests.integration.test_transactions_endpoint import _account, _dek_from_token, _login, _register, _tx

EMAIL = "suffix@example.com"
START = TODAY - timedelta(days=10)
RENT_SETUP = "ACME LETTINGS RENT 12HIGHSTREE FT"
LOAN_SETUP = "LENDCO BANK UUID-55500011122 FIRST DDR PAYMENT DDR"
STORE = "STREAMCO.COM/UK LONDON"


def _days(n):
    return TODAY - timedelta(days=n)


class World:
    def __init__(self, client, db):
        self.db, self.client = db, client
        _register(client, email=EMAIL)
        self.token = _login(client, email=EMAIL)
        self.dek = _dek_from_token(self.token)
        self.user = db.query(User).filter(User.email == EMAIL).one()
        self.ids = self.as_user(self._seed)

    def as_user(self, fn):
        token = user_crypto.current_dek.set(self.dek)
        try:
            return fn()
        finally:
            user_crypto.current_dek.reset(token)

    def _rule(self, label, amount, key, direction="expense", cadence="monthly"):
        rule = CommitmentRule(
            user_id=self.user.id, direction=direction, label=label, amount=Decimal(amount), match_key=key,
            cadence=cadence, next_date=TODAY + timedelta(days=20), source="manual", status="confirmed",
        )
        self.db.add(rule)
        return rule

    def _seed(self):
        db, uid = self.db, self.user.id
        current = _account(db, uid, name="Current", balance="5000")
        rules = {
            "rent": self._rule(RENT_SETUP, "1500.00", f"expense:{RENT_SETUP.lower()}"),
            "loan": self._rule(LOAN_SETUP, "42.50", f"expense:{LOAN_SETUP.lower()}"),
            "box": self._rule("VEG BOX ON 04 OCT CPM", "30.00", "expense:veg box cpm", cadence="weekly"),
            "sub": self._rule(STORE, "9.99", "expense:streamco com/uk london"),
            "lodger": self._rule("SMITH J RENT BGC", "800.00", "income:smith j rent bgc", direction="income"),
        }
        db.flush()
        # The rules predate their payments, as real ones do (lateness skips
        # an income created after its expected date).
        db.execute(text("UPDATE commitment_rules SET created_at = :t WHERE user_id = :u"),
                   {"t": datetime.now(timezone.utc) - timedelta(days=60), "u": uid.hex})
        txs = {
            "rent": _tx(db, current, "1500.00", _days(1), merchant="ACME LETTINGS RENT 12HIGHSTREE STO",
                        category="Rent"),
            "loan": _tx(db, current, "42.50", _days(3), merchant="LENDCO BANK UUID-55500011122 DDR",
                        category="Bills"),
            "box": _tx(db, current, "30.87", _days(2), merchant="VEG BOX ON 11 NOV CPM", category="Groceries"),
            "sub": _tx(db, current, "9.99", _days(4), merchant=STORE, category="Entertainment"),
            "phone": _tx(db, current, "1499.00", _days(5), merchant=STORE, category="Shopping"),
            "refund": _tx(db, current, "4.99", _days(2), ttype="credit", merchant=STORE, category="Shopping"),
            "lodger": _tx(db, current, "800.00", _days(1), ttype="credit", merchant="SMITH J RENT",
                          category="Income"),
        }
        db.commit()
        return {"rules": {k: r.id for k, r in rules.items()}, "txs": {k: t.id for k, t in txs.items()}}

    def paid_this_cycle(self):
        user = self.db.get(User, self.user.id)
        def paid():
            rules = self.db.query(CommitmentRule).filter_by(user_id=user.id, direction="expense").all()
            ledger = plan_service._ledger(self.db, user, START, TODAY)
            payments = plan_service._payments(self.db, user, ledger, rules, {r.id: r for r in rules}, set())
            return {tx.id: rule_id for rule_id, txs in payments.items() for tx in txs}
        return self.as_user(paid)


@pytest.fixture
def world(client, db_session):
    return World(client, db_session)


def test_plan_pays_each_bill_with_its_own_payment_and_never_the_phone(world):
    """Plan's paid list: rent (STO vs FT), the loan (DDR vs FIRST DDR
    PAYMENT DDR), the weekly box (a different date, 87p more) and the
    subscription itself are paid; the phone and the refund are not."""
    txs, rules = world.ids["txs"], world.ids["rules"]
    assert world.paid_this_cycle() == {txs[name]: rules[name] for name in ("rent", "loan", "box", "sub")}


def test_budgets_count_the_phone_as_spending_and_the_bills_as_commitments(world):
    user = world.db.get(User, world.user.id)
    spend = world.as_user(lambda: budget_spend(world.db, user, START, TODAY))
    assert spend.by_category.get("Shopping") == Decimal("1499.00")
    assert "Rent" not in spend.by_category and "Bills" not in spend.by_category
    counted = {tx.id for tx in spend.counted_commitments}
    assert world.ids["txs"]["phone"] not in counted


def test_an_income_whose_key_ends_in_bgc_is_received_from_a_credit_without_it(world):
    user = world.db.get(User, world.user.id)
    lodger = world.ids["rules"]["lodger"]
    paid = world.as_user(lambda: income_payments(world.db, user, TODAY))
    assert [c.id for c in paid.get(lodger, [])] == [world.ids["txs"]["lodger"]]
    assert lodger not in world.as_user(lambda: late_incomes(world.db, user, TODAY + timedelta(days=5)))


def _mark_recurring(world, amount, description):
    def add():
        account = world.db.query(Account).filter_by(user_id=world.user.id).first()
        return _tx(world.db, account, amount, _days(0), merchant=description).id
    tx_id = world.as_user(add)
    res = world.client.post("/api/v1/analytics/commitments/from-transaction", json={"transaction_id": str(tx_id)},
                            headers={"Authorization": f"Bearer {world.token}"})
    assert res.status_code in (200, 201), res.text


def _rules_named(world, prefix):
    def read():
        rules = world.db.query(CommitmentRule).filter_by(user_id=world.user.id).all()
        return sorted(_d(r.amount) for r in rules if r.label.startswith(prefix))
    return world.as_user(read)


def test_marking_a_small_payment_recurring_never_rewrites_a_confirmed_bill_on_its_key(world):
    """sec on #308: a GBP 40 "... STO" to the letting agent is not the rent."""
    _mark_recurring(world, "40.00", "ACME LETTINGS RENT 12HIGHSTREE STO")
    assert _rules_named(world, "ACME LETTINGS") == [Decimal("40.00"), Decimal("1500.00")]


def test_marking_a_payment_of_the_same_bill_recurring_updates_it(world):
    _mark_recurring(world, "1510.00", "ACME LETTINGS RENT 12HIGHSTREE STO")
    assert _rules_named(world, "ACME LETTINGS") == [Decimal("1510.00")]
