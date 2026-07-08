"""Unit tests for manual assets and net-worth history reconstruction."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from app.models import Account, Asset, AssetValuation, Transaction, User
from app.services import analytics_service as svc


def _user(db):
    u = User(email=f"nw-{datetime.now().timestamp()}@example.com", hashed_password="x")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _account(db, user, balance, atype="TRANSACTION", name="Main"):
    a = Account(
        user_id=user.id,
        bank_connection_id=user.id,  # FK not enforced in sqlite test
        external_id=f"ext-{name}-{datetime.now().timestamp()}",
        provider_name="Test",
        account_type=atype,
        display_name=name,
        current_balance=Decimal(balance),
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


def _tx(db, account, amount, when, ttype="debit"):
    t = Transaction(
        account_id=account.id,
        external_id=f"tx-{account.id}-{when.isoformat()}-{ttype}-{amount}",
        transaction_type=ttype,
        amount=Decimal(str(amount)),
        currency="GBP",
        description="t",
        merchant_name="t",
        transaction_date=datetime.combine(when, datetime.min.time(), tzinfo=timezone.utc),
    )
    db.add(t)
    db.commit()
    return t


def _asset(db, user, name, values: dict[date, str]):
    a = Asset(user_id=user.id, name=name, asset_type="isa")
    db.add(a)
    db.flush()
    for valued_at, value in values.items():
        db.add(AssetValuation(asset_id=a.id, value=Decimal(value), valued_at=valued_at))
    db.commit()
    return a


class TestAssetsTotal:
    def test_latest_valuation_wins(self, db_session):
        user = _user(db_session)
        _asset(db_session, user, "S&S ISA", {
            date.today() - timedelta(days=60): "5000",
            date.today(): "6000",
        })
        assert svc.assets_total(db_session, user) == Decimal("6000")

    def test_as_of_uses_step_function(self, db_session):
        user = _user(db_session)
        _asset(db_session, user, "S&S ISA", {
            date.today() - timedelta(days=60): "5000",
            date.today(): "6000",
        })
        as_of = date.today() - timedelta(days=30)
        assert svc.assets_total(db_session, user, as_of=as_of) == Decimal("5000")

    def test_before_first_valuation_counts_zero(self, db_session):
        user = _user(db_session)
        _asset(db_session, user, "S&S ISA", {date.today(): "6000"})
        assert svc.assets_total(db_session, user, as_of=date.today() - timedelta(days=10)) == Decimal("0")

    def test_liability_negative_valuation_subtracts(self, db_session):
        """A liability is stored as a negative valuation and reduces the total."""
        user = _user(db_session)
        _asset(db_session, user, "S&S ISA", {date.today(): "6000"})
        loan = Asset(user_id=user.id, name="Car loan", asset_type="loan")
        db_session.add(loan)
        db_session.flush()
        db_session.add(AssetValuation(asset_id=loan.id, value=Decimal("-6800"), valued_at=date.today()))
        db_session.commit()
        assert svc.assets_total(db_session, user) == Decimal("-800")  # 6000 − 6800


class TestNetWorthHistory:
    def test_bank_balance_reconstruction(self, db_session):
        user = _user(db_session)
        acc = _account(db_session, user, 1000)
        # Recent activity: spent 100, received 200 (both inside this month).
        _tx(db_session, acc, 100, date.today() - timedelta(days=1), ttype="debit")
        _tx(db_session, acc, 200, date.today() - timedelta(days=2), ttype="credit")

        history = svc.net_worth_history(db_session, user, months=1)
        today_point = history[-1]
        month_end = history[0]

        assert today_point["net_worth"] == Decimal("1000")
        # Before both transactions: 1000 - (200 - 100) = 900
        assert month_end["net_worth"] == Decimal("900")

    def test_credit_account_subtracts_owed(self, db_session):
        user = _user(db_session)
        _account(db_session, user, 1000, name="Cur")
        card = _account(db_session, user, 250, atype="CREDIT_CARD", name="Card")
        # Spent 50 on the card yesterday: owed before = 200.
        _tx(db_session, card, 50, date.today() - timedelta(days=1), ttype="debit")

        history = svc.net_worth_history(db_session, user, months=1)
        assert history[-1]["net_worth"] == Decimal("750")  # 1000 - 250
        assert history[0]["net_worth"] == Decimal("800")  # 1000 - 200

    def test_assets_included_stepwise(self, db_session):
        user = _user(db_session)
        _account(db_session, user, 100)
        # Use the code's own "today" (UTC) so the newest valuation is dated on
        # the same day the history's final point is computed for — otherwise a
        # local/UTC date-boundary drops it and the assertion flakes.
        today = svc._today()
        _asset(db_session, user, "ISA", {
            today - timedelta(days=400): "5000",
            today: "7000",
        })
        history = svc.net_worth_history(db_session, user, months=2)
        assert history[-1]["net_worth"] == Decimal("7100")
        assert history[0]["net_worth"] == Decimal("5100")
