"""The one budget-spend counting function (T-09-1; concept sections 2 and 15.3).

Budget spend is the purchases lens: card purchases and cash purchases,
by category, inside one cycle. Excluded, and reported with their amounts
for the "Not counted here" list:
  - spending that matches a confirmed commitment (already in safe-to-spend);
  - transfers between the user's own accounts;
  - card payoffs (the purchases were counted when they were made).
Income and refunds are never netted. The same function feeds tracking,
History and the Cashflow projection, so it agrees with the Spending
screen's purchases lens. It reads the user's own transactions at request
time, bounded to the cycle.
"""
from datetime import timedelta
from decimal import Decimal

from app.core import user_crypto
from app.models import CommitmentRule, User
from app.services import analytics_service
from app.services.budget_spend import budget_spend
from tests.clock import TODAY
from tests.integration.test_oauth import _connect
from tests.integration.test_transactions_endpoint import _account, _dek_from_token, _tx

START = TODAY - timedelta(days=10)


class World:
    def __init__(self, client, db, email="budgets@example.com"):
        self.db = db
        web, _, _ = _connect(client, email=email)
        self.dek = _dek_from_token(web)
        self.user = db.query(User).filter(User.email == email).one()

    def as_user(self, fn):
        token = user_crypto.current_dek.set(self.dek)
        try:
            return fn()
        finally:
            user_crypto.current_dek.reset(token)

    def seed(self):
        def make():
            db, uid = self.db, self.user.id
            current = _account(db, uid, name="Current", balance="2000")
            card = _account(db, uid, atype="CREDIT_CARD", name="Card", balance="300")
            savings = _account(db, uid, atype="SAVINGS", name="Saver", balance="5000")
            day = TODAY - timedelta(days=2)
            _tx(db, current, "20.00", day, merchant="Pret", category="Eating out")         # counted (cash)
            _tx(db, card, "30.00", day, merchant="Tesco", category="Groceries")            # counted (credit)
            _tx(db, card, "10.00", day, ttype="credit", merchant="Tesco", category="Groceries")  # refund: not netted
            _tx(db, current, "950.00", day, merchant="LANDLORD RENT", category="Bills")    # commitment
            db.add(CommitmentRule(user_id=uid, direction="expense", label="LANDLORD RENT",
                                  amount=Decimal("950"), cadence="monthly", next_date=TODAY + timedelta(days=20),
                                  source="manual", status="confirmed"))
            _tx(db, current, "200.00", day, merchant="To saver", category="Savings")       # transfer, out
            _tx(db, savings, "200.00", day, ttype="credit", merchant="From current")       # transfer, in
            _tx(db, current, "100.00", day, merchant="AMEX PAYMENT", category="Bills")     # card payoff, out
            _tx(db, card, "100.00", day, ttype="credit", merchant="PAYMENT RECEIVED")      # card payoff, in
            _tx(db, current, "45.00", START - timedelta(days=1), merchant="Pret", category="Eating out")  # before the cycle
            db.commit()
        self.as_user(make)

    def spend(self, start=START, end=TODAY):
        return self.as_user(lambda: budget_spend(self.db, self.user, start, end))


def test_purchases_count_by_category_and_refunds_are_not_netted(client, db_session):
    w = World(client, db_session)
    w.seed()
    assert w.spend().by_category == {"Eating out": Decimal("20.00"), "Groceries": Decimal("30.00")}


def test_commitment_matched_spending_is_excluded_and_reported(client, db_session):
    w = World(client, db_session)
    w.seed()
    assert w.spend().excluded["commitments"] == Decimal("950.00")


def test_transfers_between_own_accounts_are_excluded_and_reported(client, db_session):
    w = World(client, db_session)
    w.seed()
    assert w.spend().excluded["transfers"] == Decimal("200.00")


def test_card_payoffs_are_excluded_and_reported(client, db_session):
    w = World(client, db_session)
    w.seed()
    assert w.spend().excluded["card_payoffs"] == Decimal("100.00")


def test_the_window_is_bounded_to_the_cycle(client, db_session):
    w = World(client, db_session)
    w.seed()
    assert w.spend(start=START - timedelta(days=1)).by_category["Eating out"] == Decimal("65.00")
    assert w.spend(start=TODAY - timedelta(days=1)).by_category == {}


def test_it_agrees_with_the_spending_screens_purchases_lens(client, db_session):
    """Three-sources rule: one rule, every surface."""
    w = World(client, db_session)
    w.seed()
    screen = w.as_user(lambda: analytics_service.get_spending(
        w.db, w.user, period="custom", frm=START, to=TODAY, lens="purchases", exclude_commitments=True,
    ))
    assert {c["category"]: c["total"] for c in screen["by_category"]} == w.spend().by_category


def test_another_users_spending_is_never_counted(client, db_session):
    a = World(client, db_session, email="a@example.com")
    a.seed()
    b = World(client, db_session, email="b@example.com")
    assert b.spend().by_category == {} and sum(b.spend().excluded.values()) == 0
