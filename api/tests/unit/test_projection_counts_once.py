"""Wealth projections count a card repayment commitment once (T-08-12).

The projection's surplus is commitment income - commitment bills - average
purchases. Purchases on a card are already in that average, and repaying the
card is net-worth-neutral (cash down, debt down). So a confirmed commitment
that is the card's repayment ("AMEX" £400) must not also be subtracted as a
bill. That was the double count left open by PR 91.

Which commitment is "the card's repayment" is decided by the same rule the
summary and forecast use (`card_repayment_rules`, behind
`scheduled_outflows`). Anything less certain stays a bill: when we can't tell,
an outgoing is kept.
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from app.models import Account, AccountSetting, CommitmentRule, CommitmentStatus, Transaction, User
from app.services import analytics_service as svc

MONTHS = 24


def _user(db):
    u = User(email=f"pc1-{datetime.now().timestamp()}@e.com", hashed_password="x")
    db.add(u)
    db.commit()
    return u


def _account(db, user, atype, balance, name, provider, role):
    a = Account(
        user_id=user.id, bank_connection_id=user.id,
        external_id=f"ext-{name}-{datetime.now().timestamp()}",
        provider_name=provider, account_type=atype, display_name=name,
        current_balance=Decimal(balance),
    )
    db.add(a)
    db.commit()
    db.add(AccountSetting(user_id=user.id, account_id=a.id, role=role))
    db.commit()
    return a


def _amex(db, user, configured=True, name="Gold"):
    card = _account(db, user, "CREDIT_CARD", "400", name, "American Express", "credit")
    s = db.query(AccountSetting).filter(AccountSetting.account_id == card.id).one()
    if configured:
        s.repayment_cadence = "monthly"
        s.repayment_day = (svc._today() + timedelta(days=4)).day
        s.repayment_strategy = "full_balance"
    db.commit()
    return card


def _commitment(db, user, label, amount, direction="expense"):
    db.add(CommitmentRule(
        user_id=user.id, direction=direction, label=label, amount=Decimal(amount),
        cadence="monthly", next_date=svc._today() + timedelta(days=4),
        status=CommitmentStatus.CONFIRMED.value,
    ))
    db.commit()


def _card_purchases(db, card, amount):
    """`amount` of card purchases in each of the last two complete months."""
    today = svc._today()
    last_m = date(today.year, today.month, 1) - timedelta(days=1)
    prev_m = date(last_m.year, last_m.month, 1) - timedelta(days=1)
    for d in (last_m.replace(day=10), prev_m.replace(day=10)):
        db.add(Transaction(
            account_id=card.id, external_id=f"cp-{d}-{datetime.now().timestamp()}",
            transaction_type="debit", amount=Decimal(amount), currency="GBP",
            description="Shop", merchant_name="Shop",
            transaction_date=datetime.combine(d, datetime.min.time(), tzinfo=timezone.utc),
        ))
    db.commit()


def _setup(db):
    user = _user(db)
    _account(db, user, "TRANSACTION", "5000", "Current", "Monzo", "spending")
    _commitment(db, user, "Employer", "2000", direction="income")
    return user


def _bills(db, user):
    return svc.derived_contribution(db, user)["bills_monthly"]


def _surplus(db, user):
    """Monthly surplus before the spending leg, so only commitments show."""
    return svc.monthly_surplus_series(db, user, MONTHS, Decimal(0))


class TestCardRepaymentCommitmentCountsOnce:
    def test_amex_commitment_is_not_a_bill_on_top_of_card_purchases(self, db_session):
        user = _setup(db_session)
        card = _amex(db_session, user)
        _card_purchases(db_session, card, "400")
        _commitment(db_session, user, "AMEX", "400")

        assert _bills(db_session, user) == Decimal("0.00")
        assert set(_surplus(db_session, user)) == {Decimal("2000")}
        # The card spend is still counted, once, through the purchases average.
        assert svc.derived_contribution(db_session, user)["avg_spending_monthly"] > 0

    def test_projection_contribution_counts_the_card_once(self, db_session):
        user = _setup(db_session)
        card = _amex(db_session, user)
        _card_purchases(db_session, card, "400")
        _commitment(db_session, user, "AMEX", "400")

        basis = svc.net_worth_projection(db_session, user, annual_growth_pct=Decimal("0"))["contribution_basis"]
        assert basis["contribution"] == Decimal("2000.00") - basis["avg_spending_monthly"]


class TestAnythingLessCertainStaysABill:
    """Ambiguous debt: keep the outgoing (fail safe)."""

    def test_label_not_starting_with_the_card_descriptor(self, db_session):
        user = _setup(db_session)
        _amex(db_session, user)
        _commitment(db_session, user, "DD to Amex", "400")
        assert _bills(db_session, user) == Decimal("400.00")

    def test_two_cards_of_the_same_provider(self, db_session):
        user = _setup(db_session)
        _amex(db_session, user, name="Gold")
        _amex(db_session, user, name="Platinum")
        _commitment(db_session, user, "AMEX", "400")
        assert _bills(db_session, user) == Decimal("400.00")

    def test_card_without_a_repayment_config(self, db_session):
        user = _setup(db_session)
        _amex(db_session, user, configured=False)
        _commitment(db_session, user, "AMEX", "400")
        assert _bills(db_session, user) == Decimal("400.00")
        assert set(_surplus(db_session, user)) == {Decimal("1600")}

    def test_unrelated_bills_are_untouched(self, db_session):
        user = _setup(db_session)
        _amex(db_session, user)
        _commitment(db_session, user, "AMEX", "400")
        _commitment(db_session, user, "Rent", "950")
        assert _bills(db_session, user) == Decimal("950.00")


class TestIncomeIsCountedOnce:
    def test_a_card_named_income_is_still_income(self, db_session):
        """Cashback paid by the card provider is income, not a repayment."""
        user = _setup(db_session)
        _amex(db_session, user)
        _commitment(db_session, user, "AMEX CASHBACK", "25", direction="income")
        d = svc.derived_contribution(db_session, user)
        assert d["income_monthly"] == Decimal("2025.00")
        assert set(_surplus(db_session, user)) == {Decimal("2025")}
