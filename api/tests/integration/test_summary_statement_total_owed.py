"""Summary accounts carry the card's statement, and the summary carries one
server-computed `total_owed` (T-10-14a; ux S1/S2, sec S-6).

- Each credit account has `statement`: the current statement's balance, due
  date, paid and missing (due date passed, no newer one), from the same
  position the card statements route uses; null when none is entered. Other
  roles have no `statement` key at all.
- `total_owed` = what is owed on cards + the liabilities total, one function
  on the server, so no browser adds figures.
- Claude's `cashflow_summary` reads this route: its field set is pinned below
  (sec, 2026-10-15, option A), and `statement` carries no ids.

Synthetic fixture (public repo): card owed £6,000 with a £5,000 statement,
a £9,000 loan, a card in credit by £50.
"""
from datetime import timedelta
from decimal import Decimal

import pytest

from app.models import AccountSetting
from app.services.analytics.net_worth import total_owed
from tests.clock import TODAY
from tests.integration.test_card_statements_api import STATEMENT, Person
from tests.integration.test_net_worth_liabilities import LOAN, World
from tests.integration.test_oauth import READ, _bearer, _connect
from tests.integration.test_transactions_endpoint import _account

API = "/api/v1"


@pytest.fixture
def alice(client, db_session):
    return Person(client, db_session, "owed@example.com")


def _summary(person, token=None):
    res = person.client.get(f"{API}/analytics/summary", headers=_bearer(token or person.token))
    assert res.status_code == 200, res.text
    return res.json()


def _account_row(summary, account_id):
    return next(a for a in summary["accounts"] if a["id"] == str(account_id))


def test_a_card_with_a_statement_carries_it(alice):
    assert alice.add().status_code == 201
    card = _account_row(_summary(alice), alice.card_id)
    assert card["statement"] == {
        "statement_balance": "5000.00", "due_date": STATEMENT["due_date"], "paid": False, "missing": False,
    }


def test_the_statement_matches_the_card_statements_route(alice):
    alice.add()
    alice.card_payment("5000.00")
    route = alice.get().json()
    card = _account_row(_summary(alice), alice.card_id)
    assert card["statement"]["paid"] is route["current"]["paid"] is True
    assert card["statement"]["missing"] is route["missing_statement"] is False
    assert Decimal(card["statement"]["statement_balance"]) == Decimal(route["current"]["statement_balance"])


def test_a_statement_whose_due_date_passed_is_missing(alice):
    alice.add({
        "statement_balance": "5000.00",
        "statement_date": (TODAY - timedelta(days=40)).isoformat(),
        "due_date": (TODAY - timedelta(days=15)).isoformat(),
    })
    card = _account_row(_summary(alice), alice.card_id)
    assert card["statement"]["missing"] is True
    assert alice.get().json()["missing_statement"] is True


def test_the_latest_statement_is_the_one_shown(alice):
    alice.add({
        "statement_balance": "4000.00",
        "statement_date": (TODAY - timedelta(days=44)).isoformat(),
        "due_date": (TODAY - timedelta(days=20)).isoformat(),
    })
    alice.add()
    card = _account_row(_summary(alice), alice.card_id)
    assert card["statement"]["statement_balance"] == "5000.00"
    assert card["statement"]["missing"] is False


def test_a_card_without_a_statement_has_null_and_other_roles_have_no_key(alice):
    summary = _summary(alice)
    assert _account_row(summary, alice.card_id)["statement"] is None
    assert "statement" not in _account_row(summary, alice.current_id)


def test_a_card_switched_to_another_role_has_no_statement_key(alice, db_session):
    alice.add()
    with alice.key():
        db_session.add(AccountSetting(user_id=alice.user_id, account_id=alice.card_id, role="excluded"))
        db_session.commit()
    assert "statement" not in _account_row(_summary(alice), alice.card_id)


def test_another_users_statement_never_shows(alice, client, db_session):
    alice.add()
    bob = Person(client, db_session, "owed-bob@example.com")
    cards = [row for row in _summary(bob)["accounts"] if row["role"] == "credit"]
    assert len(cards) == 2
    for row in cards:
        assert "statement" in row and row["statement"] is None


def test_a_paid_statement_past_its_due_date_is_both_paid_and_missing(alice):
    alice.add({
        "statement_balance": "5000.00",
        "statement_date": (TODAY - timedelta(days=40)).isoformat(),
        "due_date": (TODAY - timedelta(days=15)).isoformat(),
    })
    alice.card_payment("5000.00", days_ago=20)
    card = _account_row(_summary(alice), alice.card_id)
    assert (card["statement"]["paid"], card["statement"]["missing"]) == (True, True)
    route = alice.get().json()
    assert (route["current"]["paid"], route["missing_statement"]) == (True, True)


# --------------------------------------------------------------------------- #
# total_owed (S2)
# --------------------------------------------------------------------------- #
def test_total_owed_is_cards_plus_liabilities(client, db_session):
    w = World(client, db_session, email="total@example.com")
    w.bank()
    w.as_user(lambda: _account(db_session, w.user.id, atype="CREDIT_CARD", name="Card", balance="6000"))
    assert w.add_liability().status_code == 201
    summary = w.get("/analytics/summary")
    assert summary["total_owed"] == "15000.00"
    assert Decimal(summary["total_owed"]) == Decimal(summary["credit_owed"]) + Decimal(summary["liabilities_total"])


def test_a_card_in_credit_does_not_lower_total_owed(client, db_session):
    w = World(client, db_session, email="incredit@example.com")
    w.as_user(lambda: _account(db_session, w.user.id, atype="CREDIT_CARD", name="Monzo card", balance="6000"))
    acc = w.as_user(lambda: _account(db_session, w.user.id, atype="CREDIT_CARD", name="Overpaid", balance="50"))
    acc.provider_name = "Monzo"  # Monzo reports owed as negative, so +£50 is in credit
    w.as_user(db_session.commit)
    summary = w.get("/analytics/summary")
    assert Decimal(summary["total_owed"]) == Decimal("6000.00")


def test_total_owed_is_zero_with_nothing_owed(client, db_session):
    w = World(client, db_session, email="nothing@example.com")
    w.bank()
    assert Decimal(w.get("/analytics/summary")["total_owed"]) == Decimal(0)


def test_total_owed_is_one_shared_function():
    assert total_owed(Decimal("6000.00"), Decimal("9000.00")) == Decimal("15000.00")


# --------------------------------------------------------------------------- #
# What Claude's cashflow_summary receives (sec option A, 2026-10-15)
# --------------------------------------------------------------------------- #
SUMMARY_KEYS = {
    "available_cash", "overdraft_cushion", "credit_owed", "savings_total", "assets_total",
    "liabilities_total", "total_owed", "net_worth", "committed_before_payday", "safe_to_spend",
    "savable", "savable_pending_keep_total", "safe_to_spend_pending_keep_total", "next_payday",
    "next_repayments", "accounts",
}
ACCOUNT_KEYS = {
    "id", "display_name", "provider_name", "account_type", "role", "current_balance", "credit_owed",
    "overdraft_limit", "repayment_cadence", "repayment_day", "repayment_interval_months",
    "repayment_anchor_date", "repayment_strategy", "repayment_fixed_amount", "repayment_installments",
    "pay_from_account_id", "instalment_card", "repayment_fix_needed",
}
STATEMENT_KEYS = {"statement_balance", "due_date", "paid", "missing"}


def test_claude_receives_exactly_these_fields(client, db_session):
    web, _, tokens = _connect(client, scopes=(READ,), email="claude-owed@example.com")
    w = World(client, db_session, email="claude-owed@example.com", token=web)
    card_id = w.as_user(lambda: _account(db_session, w.user.id, atype="CREDIT_CARD", name="Card", balance="6000").id)
    w.as_user(lambda: _account(db_session, w.user.id, name="Current", balance="1000"))
    res = client.post(f"{API}/analytics/accounts/{card_id}/statements", json=STATEMENT, headers=_bearer(web))
    assert res.status_code == 201
    assert client.post(f"{API}/liabilities", json=LOAN, headers=_bearer(web)).status_code == 201

    summary = w.get("/analytics/summary", token=tokens["access_token"])
    assert set(summary) == SUMMARY_KEYS
    rows = {row["role"]: row for row in summary["accounts"]}
    assert set(rows["credit"]) == ACCOUNT_KEYS | {"statement"}
    assert set(rows["credit"]["statement"]) == STATEMENT_KEYS  # no statement id, no source
    assert set(rows["spending"]) == ACCOUNT_KEYS
    assert summary["total_owed"] == "15000.00"
