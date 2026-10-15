"""The mortgage property migration (T-12-6b; sec all-tickets rule, #180).

The test schema comes from the models, so the column is first taken away
(foreign keys off, as the previous revision had it). Then, with foreign
keys on (asserted): upgrade, link a mortgage to a property, delete the
property (the link goes to null), downgrade and upgrade. The mortgage, its
bill and its commitment_links row survive every step. A batch rebuild of
`liabilities` would have cascaded the link rows away (it did, in the first
draft), so the migration uses plain ALTERs.
"""
import importlib.util
import uuid
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, text

from tests.integration.test_house_equity import _asset, _mortgage
from tests.integration.test_linked_commitment_guards import World

_MIGRATION = next((Path(__file__).resolve().parents[2] / "migrations" / "versions").glob("*_mortgage_property.py"))
_spec = importlib.util.spec_from_file_location("mortgage_property_migration", _MIGRATION)
migration = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(migration)


def _run(db, step):
    with Operations.context(MigrationContext.configure(db.connection())):
        step()
    db.commit()


def _columns(db):
    return {c["name"] for c in inspect(db.connection()).get_columns("liabilities")}


def _counts(db):
    return tuple(db.execute(text(f"SELECT count(*) FROM {t}")).scalar()
                 for t in ("liabilities", "commitment_links", "commitment_rules"))


def _as_the_previous_revision(db):
    """liabilities without the column, as the previous revision left it."""
    def drop():
        with migration.op.batch_alter_table("liabilities") as batch:
            batch.drop_index(migration._INDEX)
            batch.drop_column("property_asset_id")
    assert db.connection().exec_driver_sql("PRAGMA foreign_keys").scalar() == 0
    _run(db, drop)


def test_down_and_up_with_foreign_keys_on_after_the_property_was_deleted(client, db_session):
    world = World(client, db_session, email="mortgage-migration@example.com")
    _as_the_previous_revision(db_session)
    connection = db_session.connection()
    connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    try:
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
        _run(db_session, migration.upgrade)
        house = _asset(world)
        assert _mortgage(world, property_asset_id=house).status_code == 201
        db_session.execute(text("DELETE FROM asset_valuations WHERE asset_id = :a"), {"a": uuid.UUID(house).hex})
        db_session.execute(text("DELETE FROM assets WHERE id = :a"), {"a": uuid.UUID(house).hex})
        db_session.commit()
        assert db_session.execute(text("SELECT property_asset_id FROM liabilities")).scalar() is None
        before = _counts(db_session)
        assert before == (1, 1, 1)
        _run(db_session, migration.downgrade)
        assert "property_asset_id" not in _columns(db_session)
        assert _counts(db_session) == before
        _run(db_session, migration.upgrade)
        assert "property_asset_id" in _columns(db_session)
        assert _counts(db_session) == before
        fk = [f for f in inspect(db_session.connection()).get_foreign_keys("liabilities")
              if f["constrained_columns"] == ["property_asset_id"]]
        assert fk and fk[0]["referred_table"] == "assets"
        schema = db_session.execute(text("SELECT sql FROM sqlite_master WHERE name = 'liabilities'")).scalar()
        assert "REFERENCES assets (id) ON DELETE SET NULL" in schema
    finally:
        db_session.rollback()
        db_session.connection().exec_driver_sql("PRAGMA foreign_keys=OFF")
