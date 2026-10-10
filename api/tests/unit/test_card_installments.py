"""A card paid off in N installments produces N repayment events (T-07-5, bug 3).

The settings modal saves the installments strategy as cadence `every_n_months`
with interval 1 and an optional "First payment" date. With that date left
blank there is no anchor, and the cadence stepped from each due date + 1 day,
so the N installments landed on N consecutive days: effectively the whole
balance at once.
"""
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.models import (
    Account,
    AccountSetting,
    CommitmentRule,
    CommitmentStatus,
    RepaymentScheduleItem,
    User,
)
from app.schemas import AccountSettingUpdate
from app.services import analytics_service as svc
from app.services.analytics.repayments import _step_repayment


def _user(db):
    u = User(email=f"ci-{datetime.now().timestamp()}@e.com", hashed_password="x")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _account(db, user, atype, balance, name, provider="Test"):
    a = Account(
        user_id=user.id, bank_connection_id=user.id,
        external_id=f"ext-{name}-{datetime.now().timestamp()}",
        provider_name=provider, account_type=atype, display_name=name,
        current_balance=Decimal(balance),
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


def _flex(db, balance="900", installments=3, anchor=None, strategy="installments"):
    """A card configured the way the settings modal saves installments."""
    user = _user(db)
    current = _account(db, user, "TRANSACTION", "5000", "Current")
    card = _account(db, user, "CREDIT_CARD", balance, "Flex")
    db.add_all([
        AccountSetting(user_id=user.id, account_id=current.id, role="spending"),
        AccountSetting(
            user_id=user.id, account_id=card.id, role="credit",
            repayment_cadence="every_n_months", repayment_interval_months=1,
            repayment_anchor_date=anchor, repayment_strategy=strategy,
            repayment_installments=installments,
        ),
    ])
    db.commit()
    return user


def _repays(f):
    return [(p["date"], e["amount"]) for p in f["timeline"] for e in p["events"] if e["kind"] == "repayment"]


def _months_apart(a: date, b: date) -> int:
    return (b.year - a.year) * 12 + b.month - a.month


class TestInstallmentsWithoutFirstPaymentDate:
    def test_three_installments_a_month_apart(self, db_session):
        user = _flex(db_session, anchor=None)
        f = svc.get_forecast(db_session, user, horizon="120")
        repays = _repays(f)
        assert [amt for _, amt in repays] == [Decimal("-300.00")] * 3
        dates = [d for d, _ in repays]
        assert [_months_apart(dates[0], d) for d in dates] == [0, 1, 2]

    def test_with_a_first_payment_date_is_unchanged(self, db_session):
        anchor = svc._today() + timedelta(days=10)
        user = _flex(db_session, anchor=anchor)
        f = svc.get_forecast(db_session, user, horizon="120")
        dates = [d for d, _ in _repays(f)]
        assert dates[0] == anchor
        assert [_months_apart(anchor, d) for d in dates] == [0, 1, 2]

    def test_card_not_on_installments_is_unchanged(self, db_session):
        user = _flex(db_session, anchor=None, strategy="full_balance")
        f = svc.get_forecast(db_session, user, horizon="120")
        assert [amt for _, amt in _repays(f)] == [Decimal("-900")]

    def test_weekly_without_anchor_steps_a_week(self):
        s = AccountSetting(repayment_cadence="weekly")
        first = svc.next_repayment_date(s, date(2026, 10, 1))
        nxt = _step_repayment(s, first)
        assert (nxt - first).days == 7


class TestInstallmentAmounts:
    def test_uneven_balance_sums_to_the_penny(self, db_session):
        user = _flex(db_session, balance="100.00", anchor=None)
        f = svc.get_forecast(db_session, user, horizon="120")
        amounts = [-amt for _, amt in _repays(f)]
        assert len(amounts) == 3
        assert sum(amounts) == Decimal("100.00")
        assert amounts == [Decimal("33.33"), Decimal("33.33"), Decimal("33.34")]

    @pytest.mark.parametrize("bad", [0, -3, None, 10_000])
    def test_out_of_range_count_is_one_payment(self, db_session, bad):
        """A stored count outside 1-120 (bypassing the API) is treated as not
        split: one payment of the balance, never a crash or a long loop."""
        user = _flex(db_session, installments=bad, anchor=None)
        f = svc.get_forecast(db_session, user, horizon="120")
        assert [amt for _, amt in _repays(f)] == [Decimal("-900")]

    @pytest.mark.parametrize("bad", [0, -1, 121, 10_000])
    def test_settings_api_rejects_out_of_range_count(self, bad):
        with pytest.raises(ValidationError):
            AccountSettingUpdate(repayment_installments=bad)

    def test_zero_balance_makes_no_events(self, db_session):
        user = _flex(db_session, balance="0", anchor=None)
        f = svc.get_forecast(db_session, user, horizon="120")
        assert _repays(f) == []


class TestRepaymentInterval:
    """The every-N-months interval is bounded 1-24 at the API, and a stored
    value outside that (bypassing the API) falls back to the 3-month default,
    so a schedule can never step backwards and drop installments."""

    @pytest.mark.parametrize("bad", [0, -1, 25])
    def test_settings_schema_rejects_out_of_range_interval(self, bad):
        with pytest.raises(ValidationError):
            AccountSettingUpdate(repayment_interval_months=bad)

    @pytest.mark.parametrize("ok", [1, 24, None])
    def test_settings_schema_accepts_in_range_interval(self, ok):
        assert AccountSettingUpdate(repayment_interval_months=ok).repayment_interval_months == ok

    @pytest.mark.parametrize("anchor_in_days", [None, 5])
    @pytest.mark.parametrize("bad", [-2, 0, 10_000])
    def test_stored_out_of_range_interval_still_gives_n_future_dates(
        self, db_session, bad, anchor_in_days,
    ):
        anchor = svc._today() + timedelta(days=anchor_in_days) if anchor_in_days else None
        user = _flex(db_session, anchor=anchor)
        db_session.query(AccountSetting).filter(
            AccountSetting.repayment_strategy == "installments",
            AccountSetting.user_id == user.id,
        ).update({"repayment_interval_months": bad})
        db_session.commit()
        f = svc.get_forecast(db_session, user, horizon="365")
        dates = [d for d, _ in _repays(f)]
        assert len(dates) == 3
        assert dates == sorted(dates) and len(set(dates)) == 3
        assert [_months_apart(dates[0], d) for d in dates] == [0, 3, 6]  # the default


class TestScheduledStrategy:
    def test_card_with_nothing_owed_emits_no_listed_payments(self, db_session):
        """User-listed payments on a card that owes nothing would take money
        out of the forecast for a debt that no longer exists."""
        user = _user(db_session)
        _account(db_session, user, "TRANSACTION", "5000", "Current")
        card = _account(db_session, user, "CREDIT_CARD", "0", "Amex")
        db_session.add(AccountSetting(
            user_id=user.id, account_id=card.id, role="credit", repayment_strategy="scheduled",
        ))
        db_session.add(RepaymentScheduleItem(
            user_id=user.id, account_id=card.id,
            due_date=svc._today() + timedelta(days=5), amount=Decimal("200"),
        ))
        db_session.commit()
        f = svc.get_forecast(db_session, user, horizon="30")
        assert _repays(f) == []


# Raw balances for a card the bank owes £50 (overpaid or refunded): Amex
# reports owed as positive, Monzo as negative (app/services/balance_sign.py).
IN_CREDIT = [("Amex", "-50"), ("Monzo", "50")]


class TestCardInCredit:
    @pytest.mark.parametrize("provider,raw", IN_CREDIT)
    def test_installments_card_in_credit_makes_no_events(self, db_session, provider, raw):
        user = _user(db_session)
        _account(db_session, user, "TRANSACTION", "5000", "Current")
        card = _account(db_session, user, "CREDIT_CARD", raw, "Card", provider)
        db_session.add(AccountSetting(
            user_id=user.id, account_id=card.id, role="credit",
            repayment_cadence="every_n_months", repayment_interval_months=1,
            repayment_strategy="installments", repayment_installments=3,
        ))
        db_session.commit()
        f = svc.get_forecast(db_session, user, horizon="120")
        assert _repays(f) == []

    @pytest.mark.parametrize("provider,raw", IN_CREDIT)
    def test_scheduled_card_in_credit_makes_no_events(self, db_session, provider, raw):
        user = _user(db_session)
        _account(db_session, user, "TRANSACTION", "5000", "Current")
        card = _account(db_session, user, "CREDIT_CARD", raw, "Card", provider)
        db_session.add(AccountSetting(
            user_id=user.id, account_id=card.id, role="credit", repayment_strategy="scheduled",
        ))
        db_session.add(RepaymentScheduleItem(
            user_id=user.id, account_id=card.id,
            due_date=svc._today() + timedelta(days=5), amount=Decimal("200"),
        ))
        db_session.commit()
        f = svc.get_forecast(db_session, user, horizon="30")
        assert _repays(f) == []

    def test_monzo_card_owing_still_splits(self, db_session):
        """The owed side of the same sign rule: Monzo -900 raw = £900 owed."""
        user = _user(db_session)
        _account(db_session, user, "TRANSACTION", "5000", "Current")
        card = _account(db_session, user, "CREDIT_CARD", "-900", "Flex", "Monzo")
        db_session.add(AccountSetting(
            user_id=user.id, account_id=card.id, role="credit",
            repayment_cadence="every_n_months", repayment_interval_months=1,
            repayment_strategy="installments", repayment_installments=3,
        ))
        db_session.commit()
        f = svc.get_forecast(db_session, user, horizon="120")
        assert [amt for _, amt in _repays(f)] == [Decimal("-300.00")] * 3


class TestHorizon:
    def test_installments_past_the_horizon_are_left_out(self, db_session):
        anchor = svc._today() + timedelta(days=5)
        user = _flex(db_session, anchor=anchor)
        f = svc.get_forecast(db_session, user, horizon="30")
        assert _repays(f) == [(anchor, Decimal("-300.00"))]
        assert f["end_balance"] == Decimal("4700.00")  # 5000 - one installment


class TestDoubleCountFixed:
    def test_card_also_confirmed_as_a_commitment_counts_once_in_summary(self, db_session):
        """Was the pinned double-count trap (knowledge/nilu-engineering-lessons.md):
        a configured card that is also a confirmed commitment counted twice.
        Fixed in T-07-7; full coverage in test_card_repayment_once.py."""
        anchor = svc._today() + timedelta(days=3)
        user = _user(db_session)
        _account(db_session, user, "TRANSACTION", "5000", "Current")
        card = _account(db_session, user, "CREDIT_CARD", "-900", "Flex", "Monzo")
        db_session.add(AccountSetting(
            user_id=user.id, account_id=card.id, role="credit",
            repayment_cadence="every_n_months", repayment_interval_months=1,
            repayment_anchor_date=anchor, repayment_strategy="installments",
            repayment_installments=3,
        ))
        db_session.add(CommitmentRule(
            user_id=user.id, direction="expense", label="Monzo Flex", amount=Decimal("300"),
            cadence="monthly", next_date=anchor,
            status=CommitmentStatus.CONFIRMED.value,
        ))
        db_session.commit()
        s = svc.get_summary(db_session, user)
        # No payday configured -> 30-day window: one installment, counted once.
        assert s["committed_before_payday"] == Decimal("300.00")
