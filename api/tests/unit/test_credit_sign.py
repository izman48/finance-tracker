"""Credit-card owed uses one sign across providers (T-07-3, bug 1).

Providers report a card balance with different signs: Amex and Barclaycard
report money owed as a positive number, Monzo as a negative one. Raw balances
are stored as the provider sent them (DEK-encrypted, so never migrated) and
normalised at read time by exactly one function, `credit_owed`, which every
consumer calls. Positive = the user owes the card; negative = the card owes
the user (overpaid or refunded).
"""
import logging
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from app.models import Account, AccountSetting, User
from app.services import analytics_service as svc
from app.services.analytics.net_worth import net_worth_position
from app.services.balance_sign import credit_owed


def _acc(provider, raw, atype="CREDIT_CARD", name="Card"):
    return Account(
        provider_name=provider, account_type=atype, display_name=name,
        current_balance=None if raw is None else Decimal(raw),
    )


class TestCreditOwed:
    @pytest.mark.parametrize(
        "provider, raw, owed",
        [
            ("AMEX", "600.00", "600.00"),
            ("American Express", "600.00", "600.00"),
            ("BARCLAYCARD", "200.10", "200.10"),
            ("BARCLAYS", "200.10", "200.10"),
            ("MONZO", "-400.00", "400.00"),
            ("Monzo", "-0.10", "0.10"),
        ],
    )
    def test_money_owed_is_positive_for_every_provider(self, provider, raw, owed):
        assert credit_owed(_acc(provider, raw)) == Decimal(owed)

    @pytest.mark.parametrize("provider, raw", [("AMEX", "-50.00"), ("MONZO", "50.00")])
    def test_a_card_in_credit_is_negative_owed(self, provider, raw):
        assert credit_owed(_acc(provider, raw)) == Decimal("-50.00")

    def test_no_balance_is_zero(self):
        assert credit_owed(_acc("AMEX", None)) == Decimal(0)

    def test_result_is_exact_decimal(self):
        owed = credit_owed(_acc("MONZO", "-0.30"))
        assert isinstance(owed, Decimal) and owed == Decimal("0.30")

    def test_unknown_provider_is_not_flipped_and_logs_provider_only(self, caplog):
        caplog.set_level(logging.WARNING, logger="app.services.balance_sign")
        acc = _acc("NEWBANK", "-123.45", name="Secret Card Name")
        assert credit_owed(acc) == Decimal("-123.45")
        assert "NEWBANK" in caplog.text
        assert "123.45" not in caplog.text
        assert "Secret Card Name" not in caplog.text

    def test_unknown_provider_positive_raw_is_also_left_alone(self):
        assert credit_owed(_acc("NEWBANK", "80.00")) == Decimal("80.00")


# --- consumers: one fixture, every surface ---------------------------------- #

def _user(db):
    u = User(email=f"cs-{datetime.now().timestamp()}@e.com", hashed_password="x")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _account(db, user, provider, raw, atype="CREDIT_CARD", name=None):
    a = Account(
        user_id=user.id, bank_connection_id=user.id,
        external_id=f"ext-{provider}-{datetime.now().timestamp()}",
        provider_name=provider, account_type=atype, display_name=name or provider,
        current_balance=Decimal(raw),
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    if atype == "CREDIT_CARD":
        db.add(AccountSetting(
            user_id=user.id, account_id=a.id, role="credit",
            repayment_cadence="monthly", repayment_day=_due_day(),
            repayment_strategy="full_balance",
        ))
        db.commit()
    return a


def _due_day():
    """A day a few days ahead, so the repayment lands inside every window."""
    return min((svc._today() + timedelta(days=3)).day, 28)


def _seed(db, amex="600.00", monzo="-400.00", barclays="200.00"):
    user = _user(db)
    _account(db, user, "BARCLAYS", "1000.00", atype="TRANSACTION", name="Current")
    _account(db, user, "AMEX", amex)
    _account(db, user, "MONZO", monzo)
    _account(db, user, "BARCLAYCARD", barclays)
    return user


def _repayments(db, user):
    today = svc._today()
    return svc.repayment_events(db, user, today, today + timedelta(days=40))


class TestGoldenInDebt:
    """Cards in debt: the same numbers as before this change (no double flip).
    These pass on main too, which is the point."""

    def test_summary(self, db_session):
        user = _seed(db_session)
        s = svc.get_summary(db_session, user)
        assert s["credit_owed"] == Decimal("1200.00")
        assert s["net_worth"] == Decimal("-200.00")

    def test_repayment_events(self, db_session):
        user = _seed(db_session)
        amounts = sorted(r["amount"] for r in _repayments(db_session, user))
        assert amounts == [Decimal("200.00"), Decimal("400.00"), Decimal("600.00")]

    def test_forecast_repayments(self, db_session):
        user = _seed(db_session)
        f = svc.get_forecast(db_session, user, horizon="40")
        repaid = sum(
            (e["amount"] for day in f["timeline"] for e in day["events"] if e["kind"] == "repayment"),
            Decimal(0),
        )
        assert repaid == Decimal("-1200.00")
        assert f["start_balance"] == Decimal("1000.00")

    def test_net_worth_now(self, db_session):
        user = _seed(db_session)
        assert net_worth_position(db_session, user)["bank"] == Decimal("-200.00")


class TestCardInCredit:
    """An overpaid card: the bank owes the user. abs() used to turn this into debt."""

    def test_amex_overpaid(self, db_session):
        user = _seed(db_session, amex="-50.00", monzo="-400.00", barclays="200.00")
        s = svc.get_summary(db_session, user)
        assert s["credit_owed"] == Decimal("550.00")
        assert s["net_worth"] == Decimal("450.00")
        assert net_worth_position(db_session, user)["bank"] == Decimal("450.00")
        labels = {r["label"] for r in _repayments(db_session, user)}
        assert labels == {"MONZO", "BARCLAYCARD"}

    def test_monzo_overpaid(self, db_session):
        user = _seed(db_session, amex="600.00", monzo="50.00", barclays="200.00")
        s = svc.get_summary(db_session, user)
        assert s["credit_owed"] == Decimal("750.00")
        assert s["net_worth"] == Decimal("250.00")
        labels = {r["label"] for r in _repayments(db_session, user)}
        assert labels == {"AMEX", "BARCLAYCARD"}


class TestSummaryAccounts:
    def test_each_credit_account_carries_positive_credit_owed(self, db_session):
        user = _seed(db_session)
        rows = {a["provider_name"]: a for a in svc.get_summary(db_session, user)["accounts"]}
        assert rows["AMEX"]["credit_owed"] == Decimal("600.00")
        assert rows["MONZO"]["credit_owed"] == Decimal("400.00")
        assert rows["BARCLAYCARD"]["credit_owed"] == Decimal("200.00")
        assert rows["BARCLAYS"]["credit_owed"] is None
        # Raw balance is still reported untouched.
        assert rows["MONZO"]["current_balance"] == Decimal("-400.00")


class TestSyncIsIdempotent:
    """The next sync after deploy stores the provider's raw value again, so
    reading it gives the same owed figure: there is no write-time flip that a
    second pass could double."""

    def test_syncing_twice_gives_the_same_owed(self, db_session, monkeypatch):
        import asyncio

        from app.models import BankConnection
        from app.services.truelayer import TrueLayerService

        user = _user(db_session)
        conn = BankConnection(
            user_id=user.id, provider_id="ob-monzo", provider_name="MONZO",
            access_token="t", refresh_token="r",
        )
        db_session.add(conn)
        db_session.commit()

        async def accounts(self, token):
            return [{"account_id": "monzo-card-1", "display_name": "Card", "account_type": "CREDIT_CARD"}]

        async def cards(self, token):
            return []

        async def balance(self, token, account_id):
            return {"current": Decimal("-400.00"), "available": Decimal("-400.00")}

        monkeypatch.setattr(TrueLayerService, "get_accounts", accounts)
        monkeypatch.setattr(TrueLayerService, "get_cards", cards)
        monkeypatch.setattr(TrueLayerService, "get_account_balance", balance)

        service = TrueLayerService()
        owed = []
        for _ in range(2):
            (acc,) = asyncio.run(service.sync_accounts(conn, db_session, skip_token_refresh=True))
            db_session.refresh(acc)
            assert acc.current_balance == Decimal("-400.00")  # stored raw
            owed.append(credit_owed(acc))
        assert owed == [Decimal("400.00"), Decimal("400.00")]
        assert svc.get_summary(db_session, user)["credit_owed"] == Decimal("400.00")
