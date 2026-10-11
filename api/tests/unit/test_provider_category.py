"""No raw provider type is ever stored as a category (T-08-1, bug 7).

TrueLayer's `transaction_category` is a transaction *type* (CREDIT, DEBIT,
TRANSFER, STANDING_ORDER, PURCHASE…), not a spending category. Stored as-is it
filled the daily review with "PURCHASE" and "DIRECT_DEBIT". It is mapped on the
way in: TRANSFER -> Transfers, a credit of a known type -> Income, anything
else -> no category (shown as "Uncategorized"). Income is decided by the plain
`transaction_type` column, never by the category string alone.
"""
import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.models import Account, BankConnection, CategoryRule, Transaction, User
from app.services.categorization import category_from_provider
from app.services.truelayer import truelayer_service


class TestCategoryFromProvider:
    @pytest.mark.parametrize("raw", ["TRANSFER", "transfer", " Transfer "])
    @pytest.mark.parametrize("tx_type", ["credit", "debit"])
    def test_transfer_maps_to_transfers_either_way(self, raw, tx_type):
        assert category_from_provider(raw, tx_type) == "Transfers"

    @pytest.mark.parametrize("raw", ["CREDIT", "INTEREST", "DIVIDEND", "STANDING_ORDER", "OTHER", "CASHBACK"])
    def test_a_credit_of_a_known_type_is_income(self, raw):
        assert category_from_provider(raw, "credit") == "Income"

    @pytest.mark.parametrize("raw", [
        "DEBIT", "PURCHASE", "BILL_PAYMENT", "DIRECT_DEBIT", "STANDING_ORDER",
        "ATM", "FEE", "FEE_CHARGE", "INTEREST", "OTHER", "CREDIT", "CASH",
    ])
    def test_a_debit_is_never_income(self, raw):
        """Even a debit the provider labelled CREDIT: the column decides."""
        assert category_from_provider(raw, "debit") is None

    @pytest.mark.parametrize("tx_type", ["credit", "debit"])
    @pytest.mark.parametrize("raw", ["SOMETHING_NEW", "UNKNOWN", "", None])
    def test_unknown_or_missing_type_is_uncategorised(self, raw, tx_type):
        """Fail safe: an unknown type is never promoted to Income."""
        assert category_from_provider(raw, tx_type) is None

    def test_accepts_the_enum_as_well_as_its_value(self):
        from app.models.transaction import TransactionType

        assert category_from_provider("CREDIT", TransactionType.CREDIT) == "Income"
        assert category_from_provider("CREDIT", TransactionType.DEBIT) is None


# --- the sync path --------------------------------------------------------

def _seed_connection(db):
    user = User(email=f"pc-{datetime.now().timestamp()}@e.com", hashed_password="x")
    db.add(user)
    db.commit()
    conn = BankConnection(
        user_id=user.id, provider_id="ob-test", provider_name="TEST",
        access_token="access", refresh_token="refresh",
        token_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    db.add(conn)
    db.commit()
    acc = Account(
        user_id=user.id, bank_connection_id=conn.id, external_id=f"acc-{user.id}",
        provider_name="Test", account_type="TRANSACTION", display_name="Current",
        current_balance=Decimal("1000"),
    )
    db.add(acc)
    db.commit()
    return user, conn


def _tl_tx(n, tx_type, category, description="Payee"):
    return {
        "transaction_id": f"tl-{n}-{datetime.now().timestamp()}",
        "transaction_type": tx_type,
        "transaction_category": category,
        "amount": -10.0 if tx_type == "DEBIT" else 10.0,
        "currency": "GBP",
        "description": description,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _sync(db, conn, monkeypatch, tl_transactions):
    async def fake_get_transactions(*_args, **_kwargs):
        return tl_transactions

    monkeypatch.setattr(truelayer_service, "get_transactions", fake_get_transactions)
    asyncio.run(truelayer_service.sync_transactions(conn, db, skip_token_refresh=True))


def _stored(db, user):
    rows = db.query(Transaction).join(Account).filter(Account.user_id == user.id).all()
    return {t.description: t.category for t in rows}


class TestSyncStoresTheMappedCategory:
    def test_raw_types_never_reach_the_database(self, db_session, monkeypatch):
        user, conn = _seed_connection(db_session)
        _sync(db_session, conn, monkeypatch, [
            _tl_tx(1, "CREDIT", "CREDIT", "Salary"),
            _tl_tx(2, "DEBIT", "PURCHASE", "Shop"),
            _tl_tx(3, "DEBIT", "TRANSFER", "To savings"),
            _tl_tx(4, "DEBIT", "DIRECT_DEBIT", "Energy"),
            _tl_tx(5, "DEBIT", "BRAND_NEW_TYPE", "Mystery"),
        ])
        assert _stored(db_session, user) == {
            "Salary": "Income", "Shop": None, "To savings": "Transfers",
            "Energy": None, "Mystery": None,
        }

    def test_a_matching_rule_still_wins(self, db_session, monkeypatch):
        user, conn = _seed_connection(db_session)
        db_session.add(CategoryRule(
            user_id=user.id, pattern="Energy", match_type="exact",
            match_field="any", category="Bills", source="manual",
        ))
        db_session.commit()
        _sync(db_session, conn, monkeypatch, [_tl_tx(1, "DEBIT", "DIRECT_DEBIT", "Energy")])
        assert _stored(db_session, user) == {"Energy": "Bills"}
