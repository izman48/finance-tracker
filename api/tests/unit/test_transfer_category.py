"""TRANSFER-category transactions are not purchases (T-07-2, bug 6).

TrueLayer tags a Faster Payment out (e.g. a Flywire tuition payment) with
transaction_category TRANSFER. It has no visible incoming leg, so pair
detection misses it, and the purchases lens counted it as spending. One shared
predicate (`_effective_transfers`) decides what is a transfer for the
purchases lens, the drill-down, the trend and the list's excluded_reason, and
the user's explicit counts_as override beats the category.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.models import Account, Transaction, User
from app.services import analytics_service as svc


def _user(db):
    u = User(email=f"tc-{datetime.now().timestamp()}@e.com", hashed_password="x")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _account(db, user, atype="TRANSACTION", name="Cur"):
    a = Account(
        user_id=user.id, bank_connection_id=user.id,
        external_id=f"ext-{name}-{datetime.now().timestamp()}",
        provider_name="Test", account_type=atype, display_name=name,
        current_balance=Decimal("1000"),
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


def _tx(db, account, amount, when, merchant, category=None, counts_as=None):
    t = Transaction(
        account_id=account.id,
        external_id=f"tx-{merchant}-{amount}-{datetime.now().timestamp()}",
        transaction_type="debit", amount=Decimal(str(amount)), currency="GBP",
        description=merchant, merchant_name=merchant, category=category,
        transaction_date=datetime.combine(when, datetime.min.time(), tzinfo=timezone.utc),
        counts_as_override=counts_as, counts_as_locked=counts_as is not None,
    )
    db.add(t)
    db.commit()
    return t


def _user_txns(db, user):
    return db.query(Transaction).join(Account).filter(Account.user_id == user.id).all()


def _purchases(db, user):
    today = svc._today()
    return svc.get_spending(
        db, user, period="custom", frm=today - timedelta(days=10), to=today,
        lens="purchases",
    )


def _seed(db, flywire_counts_as=None):
    user = _user(db)
    acc = _account(db, user)
    # Today: inside both the 10-day purchases window and the trend's current
    # calendar month on any day (today - n days falls into last month on the 1st).
    d = svc._today()
    _tx(db, acc, "54.20", d, "Tesco", category="PURCHASE")
    _tx(db, acc, "12.80", d, "Pret", category="Eating out")
    _tx(db, acc, "4170.00", d, "Flywire", category="TRANSFER", counts_as=flywire_counts_as)
    return user


class TestTransferCategoryLeavesPurchases:
    def test_transfer_category_is_excluded_from_total_and_items(self, db_session):
        user = _seed(db_session)
        p = _purchases(db_session, user)
        assert p["total_spent"] == Decimal("67.00")
        assert all(m["merchant"] != "Flywire" for m in p["top_merchants"])
        assert all(c["category"] != "TRANSFER" for c in p["by_category"])

    def test_non_transfer_purchases_are_unchanged(self, db_session):
        user = _seed(db_session)
        p = _purchases(db_session, user)
        assert {m["merchant"]: m["total"] for m in p["top_merchants"]} == {
            "Tesco": Decimal("54.20"), "Pret": Decimal("12.80"),
        }
        assert p["paid_from_cash"] == Decimal("67.00")

    def test_category_match_ignores_case(self, db_session):
        user = _user(db_session)
        acc = _account(db_session, user)
        _tx(db_session, acc, "100", svc._today() - timedelta(days=1), "Wise", category="Transfer")
        assert _purchases(db_session, user)["total_spent"] == Decimal("0")

    def test_plural_category_counts_but_a_longer_name_does_not(self, db_session):
        """'Transfers' (a user/rule category) is a transfer; 'Transfer fee' is a
        real cost and must stay spending, so this is an exact match, not a
        substring."""
        user = _user(db_session)
        acc = _account(db_session, user)
        d = svc._today()
        _tx(db_session, acc, "100", d, "Wise", category="Transfers")
        _tx(db_session, acc, "2.50", d, "Wise fee", category="Transfer fee")
        assert _purchases(db_session, user)["total_spent"] == Decimal("2.50")

    def test_drill_down_excludes_it_too(self, db_session):
        user = _seed(db_session)
        today = svc._today()
        rows = svc.spending_transactions(
            db_session, user, period="custom", frm=today - timedelta(days=10), to=today,
        )
        assert sorted(r["merchant"] for r in rows) == ["Pret", "Tesco"]

    def test_trend_applies_the_same_exclusion(self, db_session):
        user = _seed(db_session)
        p = _purchases(db_session, user)
        trend = svc.get_spending_trend(db_session, user, months=1)
        assert trend["months"][-1]["total"] == p["total_spent"] == Decimal("67.00")

    def test_list_labels_it_internal_transfer(self, db_session):
        user = _seed(db_session)
        accounts, settings = svc._load(db_session, user)
        roles = svc.resolve_roles(accounts, settings)
        txns = _user_txns(db_session, user)
        reasons = svc.classify_noise(txns, roles)
        labelled = {t.merchant_name: reasons.get(t.id) for t in txns}
        assert labelled == {"Tesco": None, "Pret": None, "Flywire": "internal_transfer"}


class TestUserOverrideWins:
    def test_counts_as_spending_beats_transfer_category(self, db_session):
        user = _seed(db_session, flywire_counts_as="spending")
        p = _purchases(db_session, user)
        assert p["total_spent"] == Decimal("4237.00")
        trend = svc.get_spending_trend(db_session, user, months=1)
        assert trend["months"][-1]["total"] == Decimal("4237.00")

    def test_counts_as_spending_clears_the_list_label(self, db_session):
        user = _seed(db_session, flywire_counts_as="spending")
        accounts, settings = svc._load(db_session, user)
        roles = svc.resolve_roles(accounts, settings)
        txns = _user_txns(db_session, user)
        reasons = svc.classify_noise(txns, roles)
        assert all(reasons.get(t.id) is None for t in txns)
