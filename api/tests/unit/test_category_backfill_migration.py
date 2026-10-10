"""The backfill that removes raw provider types from stored categories (T-08-1).

~2,900 synced rows hold a TrueLayer transaction type ("PURCHASE",
"DIRECT_DEBIT", "CREDIT"…) as their category. The migration maps them the
same way the sync path now does, but only on rows the user has not
categorised by hand. It first copies (id, old category) of every row it
changes into a backup table, and downgrade() restores from that table.

A category relabel must never move money: the golden test runs the summary,
forecast, spending and trend before and after and expects identical numbers.

The migration's own upgrade()/downgrade() run here through alembic's
Operations against the test database, so the tested code is the shipped code.
"""
import importlib.util
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, text

from app.models import Account, AccountSetting, CommitmentRule, CommitmentStatus, Transaction, User
from app.services import analytics_service as svc

_MIGRATION = next(
    (Path(__file__).resolve().parents[2] / "migrations" / "versions").glob("*_map_raw_provider_categories.py")
)
_spec = importlib.util.spec_from_file_location("map_raw_provider_categories", _MIGRATION)
migration = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(migration)

BACKUP = migration.BACKUP_TABLE


@pytest.fixture(autouse=True)
def _drop_backup_table(db_session):
    """The backup table is not in the models' metadata, so the shared
    db_session teardown would leave it behind for the next test."""
    yield
    db_session.rollback()
    db_session.execute(text(f"DROP TABLE IF EXISTS {BACKUP}"))
    db_session.commit()


def _run(db, step):
    """Run the migration's upgrade or downgrade on the session's connection."""
    with Operations.context(MigrationContext.configure(db.connection())):
        step()
    db.commit()
    db.expire_all()


def _upgrade(db):
    _run(db, migration.upgrade)


def _downgrade(db):
    _run(db, migration.downgrade)


# --- fixture --------------------------------------------------------------

def _user(db):
    u = User(email=f"bf-{datetime.now().timestamp()}@e.com", hashed_password="x")
    db.add(u)
    db.commit()
    return u


def _account(db, user, atype, balance, name, role, provider="Test"):
    a = Account(
        user_id=user.id, bank_connection_id=user.id,
        external_id=f"ext-{name}-{datetime.now().timestamp()}",
        provider_name=provider, account_type=atype, display_name=name,
        current_balance=Decimal(balance),
    )
    db.add(a)
    db.commit()
    db.add(AccountSetting(user_id=user.id, account_id=a.id, role=role))
    db.commit()
    return a


def _tx(db, account, tx_type, amount, days_ago, text_, category, locked=False):
    t = Transaction(
        account_id=account.id,
        external_id=f"tx-{text_}-{amount}-{datetime.now().timestamp()}",
        transaction_type=tx_type, amount=Decimal(amount), currency="GBP",
        description=text_, merchant_name=text_, category=category,
        category_locked=locked,
        transaction_date=datetime.now(timezone.utc) - timedelta(days=days_ago),
    )
    db.add(t)
    db.commit()
    return t


def _seed(db):
    """A small, production-shaped mix: salary, purchases, bills, a paired
    transfer to savings, an unpaired TRANSFER, a card and its repayment, rule
    categories, hand-set categories and a confirmed bill and payday."""
    user = _user(db)
    cur = _account(db, user, "TRANSACTION", "2400", "Current", "spending")
    sav = _account(db, user, "SAVINGS", "5000", "Saver", "savings")
    card = _account(db, user, "CREDIT_CARD", "300", "Card", "credit")
    for days in (3, 33):
        _tx(db, cur, "credit", "2100", days, "Employer", "CREDIT")
        _tx(db, cur, "debit", "54.20", days, "Tesco", "PURCHASE")
        _tx(db, cur, "debit", "80", days, "Energy co", "DIRECT_DEBIT")
        _tx(db, cur, "debit", "950", days, "Landlord", "STANDING_ORDER")
        _tx(db, cur, "debit", "200", days, "To saver", "TRANSFER")
        _tx(db, sav, "credit", "200", days, "To saver", "TRANSFER")
        _tx(db, cur, "debit", "4170", days, "Flywire", "TRANSFER")
        _tx(db, cur, "debit", "120", days, "AMEX PAYMENT", "BILL_PAYMENT")
        _tx(db, card, "credit", "120", days, "PAYMENT RECEIVED", "CREDIT")
        _tx(db, card, "debit", "35.50", days, "Pizza place", "PURCHASE")
        _tx(db, cur, "debit", "20", days, "Cash machine", "ATM")
        _tx(db, cur, "credit", "1.10", days, "Interest paid", "INTEREST")
        _tx(db, cur, "debit", "12.80", days, "Pret", "Eating out")
        _tx(db, cur, "debit", "5", days, "Mystery", "SOMETHING_NEW")
        _tx(db, cur, "debit", "9.99", days, "Streaming", "PURCHASE", locked=True)
    db.add(CommitmentRule(
        user_id=user.id, direction="expense", label="Energy co", amount=Decimal("80"),
        cadence="monthly", next_date=svc._today() + timedelta(days=5),
        status=CommitmentStatus.CONFIRMED.value,
    ))
    db.add(CommitmentRule(
        user_id=user.id, direction="income", label="Employer", amount=Decimal("2100"),
        cadence="monthly", next_date=svc._today() + timedelta(days=27),
        status=CommitmentStatus.CONFIRMED.value, is_payday=True,
    ))
    db.commit()
    return user


def _categories(db, user):
    rows = db.query(Transaction).join(Account).filter(Account.user_id == user.id).all()
    return {(t.description, t.transaction_type, t.category_locked, t.category) for t in rows}


def _raw_left(db, user):
    return {
        c for (_d, _t, locked, c) in _categories(db, user)
        if not locked and c in migration.RAW_TYPES
    }


# --- the backfill ---------------------------------------------------------

class TestBackfill:
    def test_no_raw_type_remains_on_unlocked_rows(self, db_session):
        user = _seed(db_session)
        assert _raw_left(db_session, user)  # precondition: the bug is present
        _upgrade(db_session)
        assert _raw_left(db_session, user) == set()

    def test_maps_like_the_sync_path(self, db_session):
        user = _seed(db_session)
        _upgrade(db_session)
        got = {(d, c) for (d, _t, _l, c) in _categories(db_session, user)}
        assert got == {
            ("Employer", "Income"), ("Interest paid", "Income"),
            ("PAYMENT RECEIVED", "Income"),
            ("To saver", "Transfers"), ("Flywire", "Transfers"),
            ("Tesco", None), ("Energy co", None), ("Landlord", None),
            ("AMEX PAYMENT", None), ("Pizza place", None), ("Cash machine", None),
            ("Pret", "Eating out"),          # a rule/user category: untouched
            ("Mystery", "SOMETHING_NEW"),    # not a known provider type: untouched
            ("Streaming", "PURCHASE"),       # hand-set (locked): untouched
        }

    def test_income_only_from_the_transaction_type_column(self, db_session):
        """A debit the provider labelled CREDIT is not income."""
        user = _seed(db_session)
        cur = db_session.query(Account).filter(Account.user_id == user.id).first()
        _tx(db_session, cur, "debit", "15", 1, "Odd debit", "CREDIT")
        _upgrade(db_session)
        odd = [c for (d, _t, _l, c) in _categories(db_session, user) if d == "Odd debit"]
        assert odd == [None]

    def test_backup_holds_the_old_category_of_every_changed_row(self, db_session):
        user = _seed(db_session)
        before = {
            str(t.id): t.category
            for t in db_session.query(Transaction).join(Account).filter(Account.user_id == user.id)
        }
        _upgrade(db_session)
        after = {
            str(t.id): t.category
            for t in db_session.query(Transaction).join(Account).filter(Account.user_id == user.id)
        }
        changed = {k for k in before if before[k] != after[k]}
        backup = migration.backup_rows(db_session.connection())
        assert set(backup) == changed
        assert all(backup[k] == before[k] for k in changed)

    def test_running_the_backfill_again_changes_nothing(self, db_session):
        user = _seed(db_session)
        _upgrade(db_session)
        snapshot = _categories(db_session, user)
        assert migration.backfill(db_session.connection()) == 0
        db_session.commit()
        db_session.expire_all()
        assert _categories(db_session, user) == snapshot

    def test_down_restores_and_up_again_matches(self, db_session):
        user = _seed(db_session)
        original = _categories(db_session, user)
        _upgrade(db_session)
        migrated = _categories(db_session, user)
        _downgrade(db_session)
        assert _categories(db_session, user) == original
        assert BACKUP not in inspect(db_session.connection()).get_table_names()
        _upgrade(db_session)
        assert _categories(db_session, user) == migrated

    def test_downgrade_keeps_a_category_the_user_set_after_the_upgrade(self, db_session):
        user = _seed(db_session)
        _upgrade(db_session)
        tesco = (
            db_session.query(Transaction).join(Account)
            .filter(Account.user_id == user.id).all()
        )
        tesco = next(t for t in tesco if t.description == "Tesco")
        tesco.category, tesco.category_locked = "Groceries", True
        db_session.commit()
        _downgrade(db_session)
        rows = [c for (d, _t, locked, c) in _categories(db_session, user) if d == "Tesco" and locked]
        assert rows == ["Groceries"]


    def test_downgrade_keeps_a_rule_category_set_after_the_upgrade(self, db_session):
        """Only rows still holding the backfilled value are restored."""
        user = _seed(db_session)
        _upgrade(db_session)
        rows = db_session.query(Transaction).join(Account).filter(Account.user_id == user.id).all()
        for t in rows:
            if t.description == "Tesco":
                t.category = "Groceries"  # e.g. a rule pack added later; still unlocked
        db_session.commit()
        _downgrade(db_session)
        tesco = {c for (d, _t, _l, c) in _categories(db_session, user) if d == "Tesco"}
        assert tesco == {"Groceries"}


class TestSameMappingAsSync:
    def test_the_raw_type_lists_agree(self):
        from app.services.categorization import PROVIDER_TRANSACTION_TYPES

        assert migration.RAW_TYPES == PROVIDER_TRANSACTION_TYPES

    @pytest.mark.parametrize("tx_type", ["credit", "debit"])
    def test_every_raw_type_maps_as_category_from_provider_does(self, db_session, tx_type):
        from app.services.categorization import category_from_provider

        user = _user(db_session)
        cur = _account(db_session, user, "TRANSACTION", "100", "Current", "spending")
        for raw in migration.RAW_TYPES:
            _tx(db_session, cur, tx_type, "1", 1, raw, raw)
        _upgrade(db_session)
        got = {d: c for (d, _t, _l, c) in _categories(db_session, user)}
        assert got == {raw: category_from_provider(raw, tx_type) for raw in migration.RAW_TYPES}


# --- golden: money is identical before and after --------------------------

def _without_categories(value):
    if isinstance(value, dict):
        return {k: _without_categories(v) for k, v in value.items() if k != "by_category"}
    if isinstance(value, list):
        return [_without_categories(v) for v in value]
    return value


def _money(db, user):
    today = svc._today()
    window = dict(period="custom", frm=today - timedelta(days=60), to=today)
    return _without_categories({
        "summary": svc.get_summary(db, user),
        "forecast": svc.get_forecast(db, user, horizon="30"),
        "money_out": svc.get_spending(db, user, **window),
        "money_out_hidden": svc.get_spending(
            db, user, hide_transfers=True, hide_card_payments=True, **window
        ),
        "purchases": svc.get_spending(db, user, lens="purchases", **window),
        "trend": svc.get_spending_trend(db, user, months=3),
    })


class TestGoldenTotals:
    def test_money_totals_are_identical_before_and_after(self, db_session):
        user = _seed(db_session)
        before = _money(db_session, user)
        assert before["summary"]["safe_to_spend"] > 0  # precondition: real figures
        assert before["money_out"]["total_spent"] > 0
        _upgrade(db_session)
        assert _money(db_session, user) == before

    def test_only_the_breakdown_changes(self, db_session):
        user = _seed(db_session)
        today = svc._today()
        window = dict(period="custom", frm=today - timedelta(days=60), to=today)
        _upgrade(db_session)
        cats = {c["category"] for c in svc.get_spending(db_session, user, **window)["by_category"]}
        assert not cats & (migration.RAW_TYPES - {"PURCHASE"})  # PURCHASE: only the locked row
        assert "Uncategorized" in cats
