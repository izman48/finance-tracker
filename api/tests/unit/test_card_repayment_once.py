"""Each card repayment is counted once (T-07-7).

A card's repayment comes from its repayment settings (`repayment_events`). If
the user also confirmed a commitment for the same payment ("AMEX", "MONZO
FLEX"), the summary and the forecast used to add both. A confirmed expense
commitment that names a specific card, when that card has a repayment set up,
is now left to the repayment events. Anything less certain is still counted:
over-stating what goes out is safe, hiding it is not.
"""
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from app.models import Account, AccountSetting, CommitmentRule, CommitmentStatus, User
from app.services import analytics_service as svc


def _user(db):
    u = User(email=f"ro-{datetime.now().timestamp()}@e.com", hashed_password="x")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _account(db, user, atype, balance, name, provider):
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


def _setup(db):
    user = _user(db)
    cur = _account(db, user, "TRANSACTION", "5000", "Current", "Monzo")
    db.add(AccountSetting(user_id=user.id, account_id=cur.id, role="spending"))
    db.commit()
    return user


def _monzo_flex(db, user, configured=True, raw="-900"):
    """Monzo reports owed as negative: -900 raw = £900 owed, 3 x £300."""
    card = _account(db, user, "CREDIT_CARD", raw, "Flex", "Monzo")
    db.add(AccountSetting(
        user_id=user.id, account_id=card.id, role="credit",
        repayment_cadence="every_n_months" if configured else None,
        repayment_interval_months=1,
        repayment_anchor_date=svc._today() + timedelta(days=3),
        repayment_strategy="installments", repayment_installments=3,
    ))
    db.commit()
    return card


def _amex(db, user, configured=True, balance="400", name="Gold"):
    card = _account(db, user, "CREDIT_CARD", balance, name, "American Express")
    db.add(AccountSetting(
        user_id=user.id, account_id=card.id, role="credit",
        repayment_cadence="monthly" if configured else None,
        repayment_day=(svc._today() + timedelta(days=4)).day,
        repayment_strategy="full_balance",
    ))
    db.commit()
    return card


def _commitment(db, user, label, amount, in_days=3, direction="expense"):
    db.add(CommitmentRule(
        user_id=user.id, direction=direction, label=label, amount=Decimal(amount),
        cadence="monthly", next_date=svc._today() + timedelta(days=in_days),
        status=CommitmentStatus.CONFIRMED.value,
    ))
    db.commit()


def _committed(db, user):
    return svc.get_summary(db, user)["committed_before_payday"]


def _forecast_events(db, user):
    f = svc.get_forecast(db, user, horizon="30")
    return [(e["kind"], e["label"], e["amount"]) for p in f["timeline"] for e in p["events"]]


class TestCountedOnce:
    def test_monzo_flex_commitment_and_configured_card_count_once(self, db_session):
        user = _setup(db_session)
        _monzo_flex(db_session, user)
        _commitment(db_session, user, "MONZO FLEX", "300")
        assert _committed(db_session, user) == Decimal("300.00")
        events = _forecast_events(db_session, user)
        assert [e for e in events if e[0] == "expense"] == []
        assert [e[2] for e in events if e[0] == "repayment"] == [Decimal("-300.00")]

    def test_truncated_amex_descriptor_counts_once(self, db_session):
        user = _setup(db_session)
        _amex(db_session, user)
        _commitment(db_session, user, "AMERICAN EXP 3773 PB945227708021965 FT", "400", in_days=4)
        assert _committed(db_session, user) == Decimal("400")
        assert [e[0] for e in _forecast_events(db_session, user)] == ["repayment"]

    def test_unrelated_commitments_are_untouched(self, db_session):
        user = _setup(db_session)
        _amex(db_session, user)
        _commitment(db_session, user, "Rent", "1200", in_days=2)
        _commitment(db_session, user, "Amex cashback", "5", in_days=20, direction="income")  # also payday
        assert _committed(db_session, user) == Decimal("1600")  # rent + amex repayment
        kinds = sorted(e[0] for e in _forecast_events(db_session, user))
        assert kinds == ["expense", "income", "repayment"]


class TestStillCountedWhenUnsure:
    def test_card_without_a_repayment_setup_keeps_its_commitment(self, db_session):
        user = _setup(db_session)
        _amex(db_session, user, configured=False)
        _commitment(db_session, user, "AMEX", "400")
        assert _committed(db_session, user) == Decimal("400")

    def test_commitment_naming_another_card_is_kept(self, db_session):
        user = _setup(db_session)
        _monzo_flex(db_session, user)
        _commitment(db_session, user, "BARCLAYCARD", "150")
        assert _committed(db_session, user) == Decimal("450.00")  # 300 + 150

    def test_generic_credit_card_commitment_is_kept(self, db_session):
        """Doesn't say which card: over-state rather than drop it."""
        user = _setup(db_session)
        _amex(db_session, user)
        _commitment(db_session, user, "CREDIT CARD PAYMENT", "400", in_days=4)
        assert _committed(db_session, user) == Decimal("800")


class TestOnlyTheCoveredPaymentsAreDropped:
    def test_commitment_after_the_last_repayment_still_counts(self, db_session):
        """Repayment events pay off today's balance once. A monthly Amex
        commitment after that date stands for future card spending, which the
        repayment model does not project, so it stays in the forecast."""
        user = _setup(db_session)
        _amex(db_session, user)
        _commitment(db_session, user, "AMEX", "400", in_days=4)
        f = svc.get_forecast(db_session, user, horizon="90")
        events = [(e["kind"], p["date"]) for p in f["timeline"] for e in p["events"]]
        repay_day = next(d for k, d in events if k == "repayment")
        expenses = [d for k, d in events if k == "expense"]
        assert len(expenses) == 2  # months 2 and 3 of the commitment
        assert all(d > repay_day for d in expenses)


class TestSurfacesAgree:
    def test_summary_and_forecast_count_the_same_outflow(self, db_session):
        user = _setup(db_session)
        _monzo_flex(db_session, user)
        _amex(db_session, user)
        _commitment(db_session, user, "MONZO FLEX", "300")
        _commitment(db_session, user, "AMERICAN EXP 3773", "400", in_days=4)
        _commitment(db_session, user, "Rent", "1200", in_days=2)
        _commitment(db_session, user, "Barclaycard", "150", in_days=5)  # no card set up
        s = svc.get_summary(db_session, user)
        # No payday configured: both windows end at today + 30, and nothing
        # falls on today (the summary includes today, the forecast starts after).
        f = svc.get_forecast(db_session, user, horizon="payday")
        outflow = -sum(
            (e["amount"] for p in f["timeline"] for e in p["events"] if e["amount"] < 0),
            Decimal(0),
        )
        assert s["committed_before_payday"] == outflow == Decimal("2050.00")  # 300+400+1200+150


class TestTheLargerOfTheTwoIsKept:
    """Per card, whichever is larger (the repayment of today's balance, or the
    confirmed commitment) is counted, so the de-dupe can never under-state."""

    def _both(self, db, user):
        s = svc.get_summary(db, user)["committed_before_payday"]
        f = svc.get_forecast(db, user, horizon="payday")
        outflow = -sum((e["amount"] for p in f["timeline"] for e in p["events"] if e["amount"] < 0), Decimal(0))
        return s, outflow, [e["kind"] for p in f["timeline"] for e in p["events"]]

    def test_commitment_larger_than_a_just_paid_balance_wins(self, db_session):
        user = _setup(db_session)
        _amex(db_session, user, balance="20")
        _commitment(db_session, user, "AMEX", "400", in_days=4)
        summary, forecast, kinds = self._both(db_session, user)
        assert summary == forecast == Decimal("400")
        assert kinds == ["expense"]

    def test_balance_larger_than_the_commitment_wins(self, db_session):
        user = _setup(db_session)
        _amex(db_session, user, balance="600")
        _commitment(db_session, user, "AMEX", "400", in_days=4)
        summary, forecast, kinds = self._both(db_session, user)
        assert summary == forecast == Decimal("600")
        assert kinds == ["repayment"]


def _summary_and_forecast(db, user):
    """committed_before_payday and the forecast's outflow over the same window
    (no payday configured: both end at today + 30)."""
    s = svc.get_summary(db, user)["committed_before_payday"]
    f = svc.get_forecast(db, user, horizon="payday")
    outflow = -sum((e["amount"] for p in f["timeline"] for e in p["events"] if e["amount"] < 0), Decimal(0))
    return s, outflow


class TestOnlyAClearRepaymentDescriptorIsCovered:
    def test_a_bill_paid_by_card_is_not_the_card_repayment(self, db_session):
        """'Gym (paid by Amex)' mentions the card but is not its repayment."""
        user = _setup(db_session)
        _amex(db_session, user, balance="600")
        _commitment(db_session, user, "Gym (paid by Amex)", "30", in_days=4)
        assert _summary_and_forecast(db_session, user) == (Decimal("630"), Decimal("630"))

    @pytest.mark.parametrize("label", ["CAMEX LTD", "AMEXCO SERVICES"])
    def test_descriptor_must_be_whole_words(self, db_session, label):
        """These contain 'amex' but are different payees."""
        user = _setup(db_session)
        _amex(db_session, user)
        _commitment(db_session, user, label, "250", in_days=4)
        assert _summary_and_forecast(db_session, user) == (Decimal("650"), Decimal("650"))

    def test_label_naming_two_cards_of_the_provider_is_not_covered(self, db_session):
        """Two Amex cards, only one with a repayment set up: an 'AMEX'
        commitment could be either, so it is still counted."""
        user = _setup(db_session)
        _amex(db_session, user)  # configured, £400 owed
        _amex(db_session, user, configured=False, balance="1200", name="Platinum")
        _commitment(db_session, user, "AMEX", "1200", in_days=4)
        assert _summary_and_forecast(db_session, user) == (Decimal("1600"), Decimal("1600"))

    def test_full_descriptor_and_untruncated_name_still_match(self, db_session):
        user = _setup(db_session)
        _amex(db_session, user)
        _commitment(db_session, user, "American Express DD", "400", in_days=4)
        assert _summary_and_forecast(db_session, user) == (Decimal("400"), Decimal("400"))

    def test_small_flex_balance_keeps_the_larger_commitment(self, db_session):
        user = _setup(db_session)
        _monzo_flex(db_session, user, raw="-25")  # £25 owed: 3 x 8.33/8.34
        _commitment(db_session, user, "MONZO FLEX", "300")
        assert _summary_and_forecast(db_session, user) == (Decimal("300"), Decimal("300"))
