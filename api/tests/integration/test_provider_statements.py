"""Provider statements from the card balance response (T-10-2).

TrueLayer's card balance carries `last_statement_balance`,
`last_statement_date`, `payment_due` and `payment_due_date`. nilu already
fetches that response on every sync, so no new call is made. A manual
statement always wins; a bad or missing value stores nothing and sync
carries on. Synthetic fixture: statement £5,000, current £6,000.
"""
import asyncio
import logging
from datetime import timedelta
from decimal import Decimal

import pytest

from app.models import Account, BankConnection, CardStatement, User
from app.services.analytics.statements import current_statement
from app.services.truelayer import TrueLayerService
from tests.clock import TODAY

STATEMENT_DATE = TODAY - timedelta(days=14)
DUE = TODAY + timedelta(days=10)
CARD_ID = "card-ext-7d1e"


def _stamp(day) -> str:
    return f"{day.isoformat()}T00:00:00+00:00"


def _balance(**override):
    body = {
        "current": Decimal("6000.00"), "available": Decimal("1000.00"),
        "last_statement_balance": 5000.00, "last_statement_date": _stamp(STATEMENT_DATE),
        "payment_due": 150.00, "payment_due_date": _stamp(DUE),
    }
    body.update(override)
    return {k: v for k, v in body.items() if v is not None}


class Bank:
    def __init__(self, db, monkeypatch, provider_name="Test Bank", provider_id="ob-testbank"):
        self.db = db
        self.user = User(email="statements@example.com", hashed_password="x")
        db.add(self.user)
        db.commit()
        self.conn = BankConnection(
            user_id=self.user.id, provider_id=provider_id, provider_name=provider_name,
            access_token="t", refresh_token="r",
        )
        db.add(self.conn)
        db.commit()
        self.response = _balance()
        self.balance_calls = 0

        async def accounts(_self, token):
            return []

        async def cards(_self, token):
            return [{"account_id": CARD_ID, "display_name": "Test Card", "account_type": "CREDIT_CARD"}]

        async def balance(_self, token, account_id):
            self.balance_calls += 1
            return self.response

        monkeypatch.setattr(TrueLayerService, "get_accounts", accounts)
        monkeypatch.setattr(TrueLayerService, "get_cards", cards)
        monkeypatch.setattr(TrueLayerService, "get_account_balance", balance)

    def sync(self):
        (account,) = asyncio.run(TrueLayerService().sync_accounts(self.conn, self.db, skip_token_refresh=True))
        return account

    def rows(self, source=None):
        q = self.db.query(CardStatement).filter(CardStatement.user_id == self.user.id)
        if source:
            q = q.filter(CardStatement.source == source)
        return q.all()


@pytest.fixture
def bank(db_session, monkeypatch):
    return Bank(db_session, monkeypatch)


def test_a_provider_statement_is_stored_from_the_card_balance_response(bank):
    bank.sync()

    (row,) = bank.rows()
    assert (row.source, row.statement_date, row.due_date) == ("provider", STATEMENT_DATE, DUE)
    assert (row.statement_balance, row.minimum_due) == (Decimal("5000.00"), Decimal("150.00"))
    assert bank.balance_calls == 1  # the same call that fetches the balance


def test_three_syncs_give_one_row_with_the_latest_values(bank):
    bank.sync()
    bank.sync()
    bank.response = _balance(last_statement_balance=5100.00)
    bank.sync()

    (row,) = bank.rows()
    assert row.statement_balance == Decimal("5100.00")


def test_a_new_statement_period_adds_a_row_and_becomes_current(bank):
    bank.sync()
    later = STATEMENT_DATE + timedelta(days=1)
    bank.response = _balance(last_statement_date=_stamp(later), last_statement_balance=4000.00)
    bank.sync()

    assert len(bank.rows()) == 2
    assert current_statement(bank.rows()).statement_date == later


def test_a_response_without_statement_fields_stores_nothing_and_sync_carries_on(bank):
    bank.response = {"current": Decimal("6000.00"), "available": Decimal("1000.00")}

    account = bank.sync()

    assert bank.rows() == []
    assert account.current_balance == Decimal("6000.00")


def test_a_later_response_without_the_fields_never_deletes_or_zeroes_the_stored_one(bank):
    bank.sync()
    bank.response = {"current": Decimal("6200.00")}
    bank.sync()

    (row,) = bank.rows()
    assert row.statement_balance == Decimal("5000.00")


@pytest.mark.parametrize("override", [
    {"last_statement_balance": "lots"},
    {"last_statement_balance": None},
    {"last_statement_balance": 0},
    {"last_statement_balance": 1000000.01},
    {"last_statement_date": None},
    {"last_statement_date": "not a date"},
    {"last_statement_date": _stamp(TODAY + timedelta(days=1))},
    {"payment_due_date": None},
    {"payment_due_date": _stamp(STATEMENT_DATE - timedelta(days=1))},
    {"payment_due_date": _stamp(STATEMENT_DATE + timedelta(days=61))},
], ids=lambda o: next(iter(o)) + "=" + str(next(iter(o.values()))))
def test_a_bad_value_stores_nothing_for_that_period_and_sync_carries_on(bank, override):
    bank.response = _balance(**override)

    account = bank.sync()

    assert bank.rows() == []
    assert account.current_balance == Decimal("6000.00")


@pytest.mark.parametrize("payment_due", ["many", 5000.01, None])
def test_a_bad_or_missing_minimum_keeps_the_statement_without_it(bank, payment_due):
    bank.response = _balance(payment_due=payment_due)

    bank.sync()

    (row,) = bank.rows()
    assert row.minimum_due is None and row.statement_balance == Decimal("5000.00")


@pytest.mark.parametrize("provider_name, raw, stored", [
    ("MONZO", -5000.00, Decimal("5000.00")),        # owed is negative on Monzo
    ("AMERICAN EXPRESS", 5000.00, Decimal("5000.00")),
    ("Test Bank", -5000.00, Decimal("5000.00")),    # unverified sign: abs(), never hidden
])
def test_the_statement_sign_goes_through_balance_sign(db_session, monkeypatch, provider_name, raw, stored):
    bank = Bank(db_session, monkeypatch, provider_name=provider_name)
    bank.response = _balance(last_statement_balance=raw)

    bank.sync()

    assert bank.rows()[0].statement_balance == stored


def test_monzo_card_in_credit_at_statement_stores_nothing(db_session, monkeypatch):
    bank = Bank(db_session, monkeypatch, provider_name="MONZO")
    bank.response = _balance(last_statement_balance=25.00)  # Monzo positive = in credit

    bank.sync()

    assert bank.rows() == []


def test_manual_statement_overrides_provider_for_same_period(bank, db_session):
    account = bank.sync()
    db_session.query(CardStatement).delete()
    manual = CardStatement(
        user_id=bank.user.id, account_id=account.id, statement_date=STATEMENT_DATE, due_date=DUE,
        statement_balance=Decimal("4900.00"), source="manual",
    )
    db_session.add(manual)
    db_session.commit()

    bank.sync()
    bank.sync()

    db_session.refresh(manual)
    assert manual.statement_balance == Decimal("4900.00")  # a provider write never changes a manual row
    assert len(bank.rows("provider")) == 1
    assert current_statement(bank.rows()) is manual


def test_a_failure_storing_the_statement_never_stops_the_sync(bank, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("injected")

    monkeypatch.setattr("app.services.truelayer.store_provider_statement", boom)

    account = bank.sync()

    assert account.current_balance == Decimal("6000.00")


def test_logs_hold_no_statement_values_dates_or_ids(bank, caplog, monkeypatch):
    caplog.set_level(logging.DEBUG)
    bank.sync()
    monkeypatch.setattr("app.services.truelayer.store_provider_statement",
                        lambda *a, **k: (_ for _ in ()).throw(ValueError("5000.00 secret")))
    bank.sync()

    text = caplog.text
    assert "card statement fields" in text.lower()  # the coverage line ran (precondition)
    account_id = str(bank.db.query(Account.id).filter(Account.user_id == bank.user.id).scalar())
    for secret in ("5000", "150", STATEMENT_DATE.isoformat(), DUE.isoformat(), CARD_ID, account_id,
                   str(bank.user.id), str(bank.conn.id), "secret"):
        assert secret not in text, secret


def test_the_coverage_line_reports_field_presence_per_provider_id(bank, caplog):
    caplog.set_level(logging.INFO)
    bank.response = _balance(payment_due=None)

    bank.sync()

    (line,) = [r.getMessage() for r in caplog.records if "card statement fields" in r.getMessage().lower()]
    assert line == ("Card statement fields from ob-testbank: last_statement_balance=True "
                    "last_statement_date=True payment_due=False payment_due_date=True")
