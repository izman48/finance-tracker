"""The card_plans migration (T-12-5a; sec all-tickets rule, #180's order).

Upgrade, add a plan, delete its card with foreign keys on (the plan stays,
its card link set to null), then downgrade and upgrade again. The
migration's own functions run here through alembic's Operations.
"""
import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, text

from tests.integration.test_card_plans_api import World

_MIGRATION = next((Path(__file__).resolve().parents[2] / "migrations" / "versions").glob("*_card_plans.py"))
_spec = importlib.util.spec_from_file_location("card_plans_migration", _MIGRATION)
migration = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(migration)


def _run(db, step):
    with Operations.context(MigrationContext.configure(db.connection())):
        step()
    db.commit()


def test_downgrade_with_foreign_keys_on_after_the_card_was_deleted(client, db_session):
    world = World(client, db_session, email="plans-migration@example.com")
    assert world.plan().status_code == 201
    connection = db_session.connection()
    connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    try:
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1  # the control is on
        db_session.execute(text("DELETE FROM account_settings WHERE account_id = :a"), {"a": world.card_id.hex})
        db_session.execute(text("DELETE FROM accounts WHERE id = :a"), {"a": world.card_id.hex})
        db_session.commit()
        assert db_session.execute(text("SELECT card_account_id FROM card_plans")).scalar() is None
        _run(db_session, migration.downgrade)
        assert "card_plans" not in inspect(db_session.connection()).get_table_names()
        _run(db_session, migration.upgrade)
        assert "card_plans" in inspect(db_session.connection()).get_table_names()
    finally:
        db_session.rollback()
        db_session.connection().exec_driver_sql("PRAGMA foreign_keys=OFF")


def test_one_head():
    assert migration.down_revision == "c3e5a7b9d1f4"
