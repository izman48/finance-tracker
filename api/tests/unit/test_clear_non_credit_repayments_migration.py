"""The migration that clears repayment settings on non-credit accounts (T-10-4b).

The old settings form sent repayment defaults for every role, so current and
savings accounts carry repayment fields. Nothing reads them (repayments only
come from credit accounts), so clearing them must move no figure. Rules (sec):
- only plaintext `account_settings` columns; never encrypted columns, never
  `repayment_schedule_items`;
- only rows whose stored role is `spending` or `savings`; `credit` and
  `excluded` rows are left alone (a parked card keeps its plan);
- the old values go to a backup table first, and the downgrade restores them;
- idempotent; logs counts only, never ids.

The migration's own functions run here through alembic's Operations, so the
tested code is the shipped code.
"""
import importlib.util
import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import uuid

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text

from app.models import Account, AccountSetting, BankConnection, RepaymentScheduleItem, Transaction, User
from app.services import analytics_service as svc
from tests.clock import TODAY

_MIGRATION = next(
    (Path(__file__).resolve().parents[2] / "migrations" / "versions").glob("*_clear_non_credit_repayments.py")
)
_spec = importlib.util.spec_from_file_location("clear_non_credit_repayments", _MIGRATION)
migration = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(migration)

BACKUP = migration.BACKUP_TABLE
SMELL = dict(  # what the old form saved on every account
    repayment_cadence="end_of_month", repayment_strategy="fixed", repayment_installments=3,
    repayment_day=28, repayment_interval_months=1, repayment_anchor_date=date(2026, 9, 1),
    repayment_fixed_amount=Decimal("150.00"),
)


@pytest.fixture(autouse=True)
def _drop_backup_table(db_session):
    """The backup table isn't in the models' metadata, so the shared teardown
    would leave it behind."""
    yield
    db_session.rollback()
    db_session.execute(text(f"DROP TABLE IF EXISTS {BACKUP}"))
    db_session.commit()


def _run(db, step):
    with Operations.context(MigrationContext.configure(db.connection())):
        step()
    db.commit()
    db.expire_all()


def _account(db, user, atype, balance, name, role, **setting):
    conn = BankConnection(user_id=user.id, provider_id="test", provider_name="Test Bank")
    db.add(conn)
    db.commit()
    acc = Account(
        user_id=user.id, bank_connection_id=conn.id, external_id=f"ext-{uuid.uuid4()}",
        provider_name="Test Bank", account_type=atype, display_name=name, current_balance=Decimal(balance),
    )
    db.add(acc)
    db.commit()
    db.add(AccountSetting(user_id=user.id, account_id=acc.id, role=role, **setting))
    db.commit()
    return acc


class World:
    def __init__(self, db):
        self.db = db
        self.user = User(email=f"mig-{uuid.uuid4()}@example.com", hashed_password="x")
        db.add(self.user)
        db.commit()
        self.current = _account(db, self.user, "TRANSACTION", "2400", "Current", "spending", **SMELL)
        self.saver = _account(db, self.user, "SAVINGS", "5000", "Saver", "savings", **SMELL)
        self.card = _account(
            db, self.user, "CREDIT_CARD", "6000", "Card", "credit", repayment_cadence="monthly",
            repayment_day=(TODAY + timedelta(days=5)).day, repayment_strategy="full_balance",
            pay_from_account_id=self.current.id,
        )
        self.parked = _account(db, self.user, "CREDIT_CARD", "300", "Parked card", "excluded", **SMELL)
        self.scheduled = _account(db, self.user, "CREDIT_CARD", "900", "Plan card", "credit",
                                  repayment_strategy="scheduled")
        db.add(RepaymentScheduleItem(user_id=self.user.id, account_id=self.current.id,
                                     due_date=TODAY + timedelta(days=9), amount=Decimal("20")))
        db.add(Transaction(
            account_id=self.current.id, external_id=f"tx-{uuid.uuid4()}", transaction_type="debit",
            amount=Decimal("54.20"), description="Grocer", transaction_date=datetime.now(timezone.utc) - timedelta(days=3),
        ))
        db.commit()

    def setting(self, account):
        return self.db.query(AccountSetting).filter(AccountSetting.account_id == account.id).one()

    def figures(self):
        # Every money figure; `accounts` only echoes the settings being cleared.
        summary = {k: v for k, v in svc.get_summary(self.db, self.user).items() if k != "accounts"}
        forecast = svc.get_forecast(self.db, self.user, horizon="90")
        projection = svc.net_worth_projection(self.db, self.user)
        return summary, forecast, projection


def _raw_settings(db):
    return sorted(map(tuple, db.execute(text("SELECT * FROM account_settings")).fetchall()), key=str)


def test_non_credit_account_has_no_repayment_plan(db_session):
    w = World(db_session)

    _run(db_session, migration.upgrade)

    for account in (w.current, w.saver):
        s = w.setting(account)
        assert (s.repayment_cadence, s.repayment_interval_months, s.repayment_day, s.repayment_anchor_date,
                s.repayment_fixed_amount, s.repayment_installments, s.pay_from_account_id) == (None,) * 7
        assert s.repayment_strategy == "full_balance" and s.instalment_card is False


def test_credit_and_excluded_rows_are_left_alone(db_session):
    w = World(db_session)
    before = {a: w.setting(a).__dict__.copy() for a in (w.card, w.parked, w.scheduled)}

    _run(db_session, migration.upgrade)

    for account, old in before.items():
        s = w.setting(account)
        for column in ("role", *migration.REPAYMENT_COLUMNS):
            assert getattr(s, column) == old[column], (account.display_name, column)


def test_scheduled_repayments_are_never_deleted(db_session):
    World(db_session)
    _run(db_session, migration.upgrade)
    assert db_session.query(RepaymentScheduleItem).count() == 1


def test_no_figure_moves(db_session):
    w = World(db_session)
    before = w.figures()

    _run(db_session, migration.upgrade)

    assert w.figures() == before


def test_running_it_again_changes_nothing(db_session):
    World(db_session)
    _run(db_session, migration.upgrade)
    after_first = _raw_settings(db_session)
    backup_rows = db_session.execute(text(f"SELECT count(*) FROM {BACKUP}")).scalar()

    changed = migration.clear(db_session.connection())
    db_session.commit()

    assert changed == 0
    assert _raw_settings(db_session) == after_first
    assert db_session.execute(text(f"SELECT count(*) FROM {BACKUP}")).scalar() == backup_rows == 2


def test_downgrade_restores_the_old_values(db_session):
    World(db_session)
    before = _raw_settings(db_session)

    _run(db_session, migration.upgrade)
    assert _raw_settings(db_session) != before
    _run(db_session, migration.downgrade)

    assert _raw_settings(db_session) == before
    assert db_session.execute(
        text("SELECT count(*) FROM sqlite_master WHERE name = :t"), {"t": BACKUP}
    ).scalar() == 0


def test_downgrade_keeps_settings_the_user_changed_since(db_session):
    w = World(db_session)
    _run(db_session, migration.upgrade)
    s = w.setting(w.current)
    s.role = "credit"  # e.g. the user re-set the account and configured it again
    s.repayment_cadence = "monthly"
    db_session.commit()

    _run(db_session, migration.downgrade)

    s = w.setting(w.current)
    assert (s.role, s.repayment_cadence, s.repayment_strategy) == ("credit", "monthly", "full_balance")


def test_it_logs_counts_only(db_session, caplog):
    w = World(db_session)
    w.setting(w.scheduled).repayment_cadence = "fortnightly"  # a credit row with an unknown cadence
    db_session.commit()
    caplog.set_level(logging.INFO)

    _run(db_session, migration.upgrade)

    (line,) = [r.getMessage() for r in caplog.records if "repayment settings" in r.getMessage()]
    assert line == ("Clearing repayment settings on non-credit accounts: matched=2 changed=2 "
                    "non_enum_rows=1 credit_rows_with_unknown_cadence_or_strategy=1")
    for account in (w.current, w.saver, w.card, w.scheduled):
        assert str(account.id) not in caplog.text and account.id.hex not in caplog.text
