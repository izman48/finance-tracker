"""Unit tests for the nudge engine (cash drag + FSCS exposure)."""
from datetime import datetime
from decimal import Decimal

from app.models import Account, User
from app.services import analytics_service as svc
from app.services.reference import uk_reference as ref


def _user(db):
    u = User(email=f"nudge-{datetime.now().timestamp()}@example.com", hashed_password="x")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _account(db, user, balance, atype="TRANSACTION", provider="Test Bank", name="Acc"):
    a = Account(
        user_id=user.id,
        bank_connection_id=user.id,  # FK not enforced in sqlite test
        external_id=f"ext-{name}-{datetime.now().timestamp()}",
        provider_name=provider,
        account_type=atype,
        display_name=name,
        current_balance=Decimal(str(balance)),
    )
    db.add(a)
    db.commit()
    return a


class TestCashDrag:
    def test_savings_balance_sizes_the_nudge(self, db_session):
        user = _user(db_session)
        _account(db_session, user, 12000, atype="SAVINGS", name="Saver")
        nudges = svc.get_nudges(db_session, user)
        drag = [n for n in nudges if n["id"] == "cash_drag"]
        assert len(drag) == 1
        expected = (Decimal("12000") * ref.BEST_EASY_ACCESS_RATE_PCT / 100).quantize(Decimal("1"))
        assert f"£{expected:,.0f}" in drag[0]["body"]
        # The as-of date must be visible (stale-rate honesty).
        assert f"{ref.BEST_EASY_ACCESS_AS_OF:%-d %b %Y}" in drag[0]["body"]

    def test_small_balances_stay_quiet(self, db_session):
        user = _user(db_session)
        _account(db_session, user, 300, atype="SAVINGS", name="Saver")
        assert all(n["id"] != "cash_drag" for n in svc.get_nudges(db_session, user))

    def test_spending_accounts_do_not_count_as_idle(self, db_session):
        user = _user(db_session)
        _account(db_session, user, 50000, atype="TRANSACTION", name="Current")
        assert all(n["id"] != "cash_drag" for n in svc.get_nudges(db_session, user))


class TestFscsExposure:
    def test_over_limit_at_one_provider_is_flagged(self, db_session):
        user = _user(db_session)
        _account(db_session, user, 90000, atype="SAVINGS", provider="Acorn Bank", name="Saver")
        nudges = [n for n in svc.get_nudges(db_session, user) if n["id"].startswith("fscs")]
        assert len(nudges) == 1
        assert "£5,000" in nudges[0]["body"]  # 90k − 85k

    def test_brands_sharing_a_licence_are_grouped(self, db_session):
        user = _user(db_session)
        _account(db_session, user, 50000, atype="SAVINGS", provider="Halifax", name="A")
        _account(db_session, user, 45000, atype="SAVINGS", provider="Bank of Scotland", name="B")
        nudges = [n for n in svc.get_nudges(db_session, user) if n["id"].startswith("fscs")]
        assert len(nudges) == 1  # 95k on one licence, not two safe 50k/45k pots
        assert "£10,000" in nudges[0]["body"]  # 95k − 85k

    def test_under_limit_is_quiet_and_negatives_do_not_offset(self, db_session):
        user = _user(db_session)
        _account(db_session, user, 84000, atype="SAVINGS", provider="Acorn Bank", name="Saver")
        # An overdrawn current account at the same brand must not push it over.
        _account(db_session, user, -2000, atype="TRANSACTION", provider="Acorn Bank", name="Cur")
        assert all(not n["id"].startswith("fscs") for n in svc.get_nudges(db_session, user))
