"""Card statements API (T-10-1): manual add/edit/delete per card, amount still
due and unbilled spend.

Synthetic fixture (the repo is public): statement £5,000, current balance
£6,000, unbilled £1,000. Dates are relative to the run's today because a
statement date can't be in the future.
"""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.core import user_crypto
from app.models import AccountSetting, CardStatement, Transaction, User
from tests.clock import TODAY
from tests.integration.test_transactions_endpoint import _account, _dek_from_token

API = "/api/v1"
PASSWORD = "securepassword123"
STATEMENT_DATE = TODAY - timedelta(days=14)
DUE_DATE = TODAY + timedelta(days=10)
STATEMENT = {
    "statement_balance": "5000.00",
    "statement_date": STATEMENT_DATE.isoformat(),
    "due_date": DUE_DATE.isoformat(),
}


def _login(client, email):
    assert client.post(f"{API}/auth/register", json={"email": email, "password": PASSWORD}).status_code == 201
    res = client.post(f"{API}/auth/login", data={"username": email, "password": PASSWORD})
    assert res.status_code == 200
    return res.json()["access_token"]


class Person:
    """A user with a card (current balance £6,000) and a current account."""

    def __init__(self, client, db, email):
        self.client, self.db = client, db
        self.token = _login(client, email)
        self.headers = {"Authorization": f"Bearer {self.token}"}
        self.user_id = db.query(User).filter(User.email == email).one().id
        with self.key():
            self.card_id = _account(db, self.user_id, atype="CREDIT_CARD", name=f"{email} card", balance="6000").id
            self.other_card_id = _account(db, self.user_id, atype="CREDIT_CARD", name=f"{email} card 2").id
            self.current_id = _account(db, self.user_id, name=f"{email} current").id

    def key(self):
        person = self

        class _Key:
            def __enter__(self):
                self.ctx = user_crypto.current_dek.set(_dek_from_token(person.token))

            def __exit__(self, *exc):
                user_crypto.current_dek.reset(self.ctx)

        return _Key()

    def url(self, card_id=None, statement_id=None):
        base = f"{API}/analytics/accounts/{card_id or self.card_id}/statements"
        return f"{base}/{statement_id}" if statement_id else base

    def add(self, body=None, card_id=None):
        return self.client.post(self.url(card_id), json=body or STATEMENT, headers=self.headers)

    def get(self, card_id=None):
        return self.client.get(self.url(card_id), headers=self.headers)

    def card_payment(self, amount, days_ago=3):
        with self.key():
            when = TODAY - timedelta(days=days_ago)
            self.db.add(Transaction(
                account_id=self.card_id, external_id=f"tx-{uuid.uuid4()}", transaction_type="credit",
                amount=Decimal(amount), currency="GBP", description="PAYMENT RECEIVED - THANK YOU",
                transaction_date=datetime(when.year, when.month, when.day, 12, tzinfo=timezone.utc),
            ))
            self.db.commit()


@pytest.fixture
def alice(client, db_session):
    return Person(client, db_session, "alice@example.com")


@pytest.fixture
def bob(client, db_session):
    return Person(client, db_session, "bob@example.com")


def _rows(db):
    return sorted(map(tuple, db.execute(text("SELECT * FROM card_statements")).fetchall()), key=str)


# --- add and read -------------------------------------------------------------


def test_adding_a_statement_stores_it_per_card(alice):
    res = alice.add({**STATEMENT, "minimum_due": "150.00"})

    assert res.status_code == 201, res.text
    body = res.json()
    assert body["account_id"] == str(alice.card_id)
    assert Decimal(body["statement_balance"]) == Decimal("5000.00")
    assert Decimal(body["minimum_due"]) == Decimal("150.00")
    assert body["statement_date"] == STATEMENT_DATE.isoformat()
    assert body["due_date"] == DUE_DATE.isoformat()
    assert body["source"] == "manual"
    listed = alice.get().json()["statements"]
    assert [s["id"] for s in listed] == [body["id"]]
    assert alice.get(alice.other_card_id).json() == {"statements": [], "current": None}


def test_statement_money_is_encrypted_at_rest(alice, db_session):
    alice.add({**STATEMENT, "minimum_due": "150.00"})

    raw = db_session.execute(text("SELECT statement_balance, minimum_due FROM card_statements")).one()
    assert "5000" not in raw[0] and "150" not in raw[1]


def test_unbilled_spend_is_current_minus_outstanding_statement(alice):
    statement_id = alice.add().json()["id"]

    current = alice.get().json()["current"]

    assert current["statement_id"] == statement_id
    assert Decimal(current["amount_still_due"]) == Decimal("5000.00")
    assert Decimal(current["unbilled"]) == Decimal("1000.00")
    assert current["due_date"] == DUE_DATE.isoformat()
    assert current["paid"] is False


def test_payment_after_statement_reduces_amount_due(alice, db_session):
    alice.add()
    alice.card_payment("1000")

    current = alice.get().json()["current"]

    assert Decimal(current["payments_since_statement"]) == Decimal("1000")
    assert Decimal(current["amount_still_due"]) == Decimal("4000.00")


def test_a_statement_paid_in_full_shows_as_paid(alice):
    alice.add()
    alice.card_payment("5000")

    current = alice.get().json()["current"]

    assert Decimal(current["amount_still_due"]) == Decimal("0")
    assert current["paid"] is True


def test_the_latest_statement_is_the_current_one_and_the_list_is_newest_first(alice):
    older = {**STATEMENT, "statement_date": (STATEMENT_DATE - timedelta(days=31)).isoformat(),
             "due_date": (DUE_DATE - timedelta(days=31)).isoformat(), "statement_balance": "4200.00"}
    old_id = alice.add(older).json()["id"]
    new_id = alice.add().json()["id"]

    body = alice.get().json()

    assert [s["id"] for s in body["statements"]] == [new_id, old_id]
    assert body["current"]["statement_id"] == new_id


def test_the_statement_list_is_capped(alice, db_session):
    with alice.key():
        for i in range(30):
            d = STATEMENT_DATE - timedelta(days=31 * i)
            db_session.add(CardStatement(
                user_id=alice.user_id, account_id=alice.card_id, statement_date=d,
                due_date=d + timedelta(days=25), statement_balance=Decimal("100"), source="manual",
            ))
        db_session.commit()

    statements = alice.get().json()["statements"]

    assert len(statements) == 24
    assert statements[0]["statement_date"] == STATEMENT_DATE.isoformat()


def test_adding_a_statement_to_a_non_credit_account_is_422(alice, db_session):
    assert alice.add(card_id=alice.current_id).status_code == 422
    # A card the user moved to another role is not a credit account either.
    with alice.key():
        db_session.add(AccountSetting(user_id=alice.user_id, account_id=alice.other_card_id, role="excluded"))
        db_session.commit()
    assert alice.add(card_id=alice.other_card_id).status_code == 422
    assert _rows(db_session) == []


def test_a_duplicate_manual_statement_for_the_same_date_is_409_and_one_row(alice, db_session):
    assert alice.add().status_code == 201

    res = alice.add({**STATEMENT, "statement_balance": "5100.00"})

    assert res.status_code == 409
    assert len(_rows(db_session)) == 1
    assert Decimal(alice.get().json()["statements"][0]["statement_balance"]) == Decimal("5000.00")


# --- edit and delete -----------------------------------------------------------


def test_editing_a_statement_updates_it(alice):
    statement_id = alice.add().json()["id"]

    res = alice.client.patch(alice.url(statement_id=statement_id), json={"statement_balance": "5200.00"},
                             headers=alice.headers)

    assert res.status_code == 200, res.text
    assert Decimal(res.json()["statement_balance"]) == Decimal("5200.00")
    assert Decimal(alice.get().json()["current"]["amount_still_due"]) == Decimal("5200.00")


def test_an_edit_is_validated_against_the_stored_dates(alice, db_session):
    statement_id = alice.add().json()["id"]
    before = _rows(db_session)
    too_early = (STATEMENT_DATE - timedelta(days=1)).isoformat()

    res = alice.client.patch(alice.url(statement_id=statement_id), json={"due_date": too_early},
                             headers=alice.headers)

    assert res.status_code == 422
    db_session.expire_all()
    assert _rows(db_session) == before


def test_deleting_the_last_statement_puts_the_card_back_on_its_current_balance(alice):
    statement_id = alice.add().json()["id"]

    res = alice.client.delete(alice.url(statement_id=statement_id), headers=alice.headers)

    assert res.status_code == 200
    assert alice.get().json() == {"statements": [], "current": None}


def test_adding_a_statement_moves_no_figure(alice):
    """Statements are opt-in: until a strategy uses them (T-10-3) the summary
    and forecast are exactly what they were."""
    summary = alice.client.get(f"{API}/analytics/summary", headers=alice.headers).json()
    forecast = alice.client.get(f"{API}/analytics/forecast", headers=alice.headers).json()

    alice.add()

    assert alice.client.get(f"{API}/analytics/summary", headers=alice.headers).json() == summary
    assert alice.client.get(f"{API}/analytics/forecast", headers=alice.headers).json() == forecast


# --- input validation (S-5) and mass assignment (S-4) --------------------------


@pytest.mark.parametrize("change", [
    {"statement_balance": "0"},
    {"statement_balance": "-5000.00"},
    {"statement_balance": "1000000.01"},
    {"statement_balance": "5000.001"},
    {"statement_balance": "lots"},
    {"minimum_due": "0"},
    {"minimum_due": "5000.01"},
    {"statement_date": (TODAY + timedelta(days=1)).isoformat()},
    {"due_date": (STATEMENT_DATE - timedelta(days=1)).isoformat()},
    {"due_date": (STATEMENT_DATE + timedelta(days=61)).isoformat()},
    {"source": "provider"},
    {"user_id": "00000000-0000-0000-0000-000000000001"},
    {"amount_still_due": "0"},
    {"unbilled": "0"},
], ids=lambda c: next(iter(c)) + "=" + str(next(iter(c.values()))))
def test_invalid_statements_are_422_and_write_nothing(alice, db_session, change):
    res = alice.add({**STATEMENT, **change})

    assert res.status_code == 422, res.text
    assert _rows(db_session) == []


def test_the_limits_themselves_are_accepted(alice):
    res = alice.add({
        "statement_balance": "1000000.00", "minimum_due": "1000000.00",
        "statement_date": TODAY.isoformat(), "due_date": (TODAY + timedelta(days=60)).isoformat(),
    })
    assert res.status_code == 201, res.text


@pytest.mark.parametrize("field", ["source", "user_id", "account_id", "statement_date_x"])
def test_an_edit_cannot_set_fields_outside_the_allow_list(alice, db_session, field):
    statement_id = alice.add().json()["id"]
    before = _rows(db_session)

    res = alice.client.patch(alice.url(statement_id=statement_id), json={field: "provider"}, headers=alice.headers)

    assert res.status_code == 422
    db_session.expire_all()
    assert _rows(db_session) == before


# --- ownership (S-3) -------------------------------------------------------------


def test_another_users_card_is_404_on_read_and_add(alice, bob, db_session):
    assert alice.client.get(alice.url(bob.card_id), headers=alice.headers).status_code == 404
    assert alice.add(card_id=bob.card_id).status_code == 404
    assert alice.add(card_id=uuid.uuid4()).status_code == 404
    assert _rows(db_session) == []


def test_another_users_statement_under_my_card_is_404_and_untouched(alice, bob, db_session):
    bobs = bob.add().json()["id"]
    before = _rows(db_session)

    patched = alice.client.patch(alice.url(statement_id=bobs), json={"statement_balance": "1.00"},
                                 headers=alice.headers)
    deleted = alice.client.delete(alice.url(statement_id=bobs), headers=alice.headers)

    assert (patched.status_code, deleted.status_code) == (404, 404)
    db_session.expire_all()
    assert _rows(db_session) == before


def test_my_statement_under_my_other_card_is_404_and_untouched(alice, db_session):
    mine = alice.add().json()["id"]
    before = _rows(db_session)

    wrong_card = alice.url(card_id=alice.other_card_id, statement_id=mine)
    patched = alice.client.patch(wrong_card, json={"statement_balance": "1.00"}, headers=alice.headers)
    deleted = alice.client.delete(wrong_card, headers=alice.headers)
    unknown = alice.client.delete(alice.url(statement_id=uuid.uuid4()), headers=alice.headers)

    assert (patched.status_code, deleted.status_code, unknown.status_code) == (404, 404, 404)
    db_session.expire_all()
    assert _rows(db_session) == before


def test_statement_routes_need_a_web_session(client, alice):
    assert client.get(alice.url()).status_code == 401
    assert client.post(alice.url(), json=STATEMENT).status_code == 401


# --- account deletion (S-2b) -----------------------------------------------------


@pytest.fixture
def sqlite_foreign_keys(db_session):
    """The test SQLite doesn't enforce foreign keys, so the cascades that
    delete-account relies on never run unless switched on (known gap)."""
    db_session.commit()
    db_session.connection().exec_driver_sql("PRAGMA foreign_keys=ON")
    yield
    db_session.rollback()
    db_session.connection().exec_driver_sql("PRAGMA foreign_keys=OFF")


def test_delete_account_removes_the_users_statements_and_keeps_others(alice, bob, db_session, sqlite_foreign_keys):
    assert alice.add().status_code == 201
    assert bob.add().status_code == 201

    res = alice.client.post(f"{API}/auth/delete-account", json={"password": PASSWORD}, headers=alice.headers)

    assert res.status_code == 200, res.text
    db_session.expire_all()
    left = db_session.execute(text("SELECT user_id FROM card_statements")).scalars().all()
    assert [uuid.UUID(str(u)) for u in left] == [bob.user_id]
