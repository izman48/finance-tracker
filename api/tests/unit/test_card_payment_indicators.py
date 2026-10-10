"""Card-settlement indicators must not swallow ordinary debit-card purchases.

UK banks describe a debit-card purchase as "CARD PAYMENT TO <MERCHANT> ON
<DATE>". The bare phrase "card payment" used to be a settlement indicator, so
every such purchase was read as paying a credit card off: it vanished from the
purchases lens, the trend and the list. Real settlements name the card
("AMEX", "BARCLAYCARD", "CREDIT CARD PAYMENT"), and those must still match.
"""
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.models import Account, AccountRole, Transaction, User
from app.services import analytics_service as svc
from app.services.analytics.common import is_card_payment_descriptor, is_card_settlement

PURCHASE = "CARD PAYMENT TO TESCO STORES ON 01 OCT"

SETTLEMENTS = [
    "AMEX PAYMENT",
    "AMERICAN EXP 1234 PB000000000000001 FT",  # truncated by the bank
    "BARCLAYCARD",
    "CREDIT CARD PAYMENT",
]


def _user(db):
    u = User(email=f"cp-{datetime.now().timestamp()}@example.com", hashed_password="x")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _current_account(db, user):
    a = Account(
        user_id=user.id, bank_connection_id=user.id,
        external_id=f"ext-cur-{datetime.now().timestamp()}",
        provider_name="Test", account_type="TRANSACTION", display_name="Current",
        current_balance=Decimal("1000"),
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


def _debit(db, account, amount, description, counts_as=None):
    t = Transaction(
        account_id=account.id,
        external_id=f"tx-{description}-{datetime.now().timestamp()}",
        transaction_type="debit", amount=Decimal(str(amount)), currency="GBP",
        # TrueLayer often leaves merchant_name null, so the description alone
        # has to carry the classification.
        description=description, merchant_name=None,
        transaction_date=datetime.combine(svc._today(), datetime.min.time(), tzinfo=timezone.utc),
        counts_as_override=counts_as,
        counts_as_locked=counts_as is not None,
    )
    db.add(t)
    db.commit()
    return t


def _spending(db, user, **kw):
    today = svc._today()
    return svc.get_spending(db, user, period="custom", frm=today, to=today, **kw)


def _roles(account):
    return {account.id: svc.default_role(account)}


class TestDebitCardPurchaseCountsAsSpending:
    def test_included_in_purchases_lens(self, db_session):
        user = _user(db_session)
        acc = _current_account(db_session, user)
        _debit(db_session, acc, "42.10", PURCHASE)

        p = _spending(db_session, user, lens="purchases")
        assert p["total_spent"] == Decimal("42.10")
        assert p["paid_from_cash"] == Decimal("42.10")

    def test_counted_in_spending_trend(self, db_session):
        user = _user(db_session)
        acc = _current_account(db_session, user)
        _debit(db_session, acc, "42.10", PURCHASE)

        t = svc.get_spending_trend(db_session, user, months=1)
        assert t["months"][-1]["total"] == Decimal("42.10")

    def test_has_no_noise_label(self, db_session):
        user = _user(db_session)
        acc = _current_account(db_session, user)
        tx = _debit(db_session, acc, "42.10", PURCHASE)

        assert svc.classify_noise([tx], _roles(acc)).get(tx.id) is None

    def test_money_out_attributes_it_to_other_not_card_repayments(self, db_session):
        user = _user(db_session)
        acc = _current_account(db_session, user)
        _debit(db_session, acc, "42.10", PURCHASE)

        c = _spending(db_session, user, lens="money_out")["composition"]
        assert c["card_repayments"] == Decimal("0")
        assert c["other"] == Decimal("42.10")

    def test_is_not_a_card_settlement(self):
        tx = SimpleNamespace(description=PURCHASE, merchant_name=None, transaction_type="debit")
        assert is_card_settlement(tx, AccountRole.SPENDING) is False


@pytest.mark.parametrize("description", SETTLEMENTS)
class TestRealSettlementsStillMatch:
    def test_excluded_from_purchases_and_trend(self, db_session, description):
        user = _user(db_session)
        acc = _current_account(db_session, user)
        _debit(db_session, acc, "200", description)

        assert _spending(db_session, user, lens="purchases")["total_spent"] == Decimal("0")
        assert svc.get_spending_trend(db_session, user, months=1)["months"][-1]["total"] == Decimal("0")

    def test_labelled_card_payment(self, db_session, description):
        user = _user(db_session)
        acc = _current_account(db_session, user)
        tx = _debit(db_session, acc, "200", description)

        assert svc.classify_noise([tx], _roles(acc))[tx.id] == "card_payment"

    def test_money_out_attributes_it_to_card_repayments(self, db_session, description):
        user = _user(db_session)
        acc = _current_account(db_session, user)
        _debit(db_session, acc, "200", description)

        c = _spending(db_session, user, lens="money_out")["composition"]
        assert c["card_repayments"] == Decimal("200")

    def test_is_a_card_settlement(self, description):
        tx = SimpleNamespace(description=description, merchant_name=None, transaction_type="debit")
        assert is_card_settlement(tx, AccountRole.SPENDING) is True


class TestOverrideBeatsIndicators:
    def test_spending_override_on_an_indicator_match_counts_as_spending(self, db_session):
        user = _user(db_session)
        acc = _current_account(db_session, user)
        tx = _debit(db_session, acc, "200", "AMEX PAYMENT", counts_as="spending")

        assert _spending(db_session, user, lens="purchases")["total_spent"] == Decimal("200")
        assert tx.id not in svc.classify_noise([tx], _roles(acc))

    def test_card_payment_override_on_a_purchase_excludes_it(self, db_session):
        user = _user(db_session)
        acc = _current_account(db_session, user)
        tx = _debit(db_session, acc, "42.10", PURCHASE, counts_as="card_payment")

        assert _spending(db_session, user, lens="purchases")["total_spent"] == Decimal("0")
        assert svc.classify_noise([tx], _roles(acc))[tx.id] == "card_payment"


class TestSingleIndicatorHelper:
    """The one text predicate every consumer shares, so they can never disagree."""

    @pytest.mark.parametrize("description", SETTLEMENTS)
    def test_matches_settlement_descriptors(self, description):
        assert is_card_payment_descriptor(SimpleNamespace(description=description, merchant_name=None))

    def test_matches_on_merchant_name_too(self):
        assert is_card_payment_descriptor(SimpleNamespace(description="PAYMENT", merchant_name="Barclaycard"))

    def test_does_not_match_a_debit_card_purchase(self):
        assert not is_card_payment_descriptor(SimpleNamespace(description=PURCHASE, merchant_name="Tesco"))

    def test_tolerates_missing_text(self):
        assert not is_card_payment_descriptor(SimpleNamespace(description=None, merchant_name=None))
