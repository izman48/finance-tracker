"""Deleting a planned item on the web is a soft delete (T-12-9b; sec T-12-9).

`DELETE /analytics/planned-items/{id}` hard-deleted the row, so a Claude
change on an item Claude had made lost its undo (the target was gone) and a
pending removal hold had nothing to hold. Now the web delete marks the item
deleted (`active = False`, `deleted_at`): it counts nowhere and stays
encrypted, Claude's pending removal of it stops holding (the user chose to
delete it), and undoing an earlier Claude change on it is a 409 that never
brings it back. Key-loss purge and delete-account still remove the row.
Synthetic figures only.
"""
from decimal import Decimal

from sqlalchemy import text

from app.models import PlannedItem
from app.services.key_loss_purge import purge_data_under_lost_key
from tests.integration.test_oauth import PASSWORD, _bearer
from tests.integration.test_planned_events_api import API, World
from tests.integration.test_planned_removal_hold import _added


def _web_delete(w, item_id, token=None):
    return w.client.delete(f"{API}/analytics/planned-items/{item_id}", headers=_bearer(token or w.web))


def _audit_id(w, tool):
    items = w.client.get(f"{API}/audit", headers=_bearer(w.web)).json()["items"]
    return next(i["id"] for i in items if i["tool"] == tool)


def _undo(w, audit_id):
    return w.client.post(f"{API}/audit/{audit_id}/undo", headers=_bearer(w.web))


def _row(w, item_id):
    w.db.expire_all()
    return w.db.execute(text("SELECT active, deleted_at, name FROM planned_items WHERE id = :i"),
                        {"i": item_id.replace("-", "")}).first()


def _listed(w):
    return [i["id"] for i in w.client.get(f"{API}/analytics/planned-items", headers=_bearer(w.web)).json()]


def _safe(w):
    return Decimal(w.summary()["safe_to_spend"])


def test_a_web_delete_keeps_the_row_but_it_counts_nowhere(client, db_session):
    w = World(client, db_session, email="soft-delete@example.com")
    item_id = _added(w)
    safe_before = _safe(w)
    assert _web_delete(w, item_id).status_code == 200
    active, deleted_at, name = _row(w, item_id)
    assert not active and deleted_at is not None
    assert name != "Car insurance"  # still encrypted at rest
    assert item_id not in _listed(w)
    assert _safe(w) - safe_before == Decimal("200.00")
    f = w.client.get(f"{API}/analytics/forecast?horizon=30", headers=_bearer(w.web)).json()
    assert not any(e["label"] == "Car insurance" for p in f["timeline"] for e in p["events"])


def test_undoing_claudes_add_after_a_web_delete_is_409_and_never_resurrects(client, db_session):
    w = World(client, db_session, email="soft-delete-undo@example.com")
    item_id = _added(w)
    _web_delete(w, item_id)
    assert _undo(w, _audit_id(w, "add_planned_event")).status_code == 409
    assert not _row(w, item_id)[0]


def test_a_web_delete_ends_claudes_pending_removal_hold_and_its_undo(client, db_session):
    w = World(client, db_session, email="soft-delete-hold@example.com")
    item_id = _added(w)
    safe_before = _safe(w)
    assert w.remove(item_id).status_code == 200
    assert _safe(w) == safe_before  # held until kept
    _web_delete(w, item_id)
    assert _safe(w) - safe_before == Decimal("200.00")  # the user deleted it: no hold
    assert _undo(w, _audit_id(w, "remove_planned_event")).status_code == 409
    assert not _row(w, item_id)[0]
    assert item_id not in _listed(w)


def test_another_users_or_an_unknown_item_is_404(client, db_session):
    w = World(client, db_session, email="soft-delete-owner@example.com")
    other = World(client, db_session, email="soft-delete-other@example.com")
    item_id = _added(w)
    assert _web_delete(other, item_id).status_code == 404
    assert _row(w, item_id)[0]
    assert _web_delete(w, "00000000-0000-0000-0000-000000000009").status_code == 404


def test_deleting_twice_is_404(client, db_session):
    w = World(client, db_session, email="soft-delete-twice@example.com")
    item_id = _added(w)
    assert _web_delete(w, item_id).status_code == 200
    assert _web_delete(w, item_id).status_code == 404


def test_key_loss_purge_removes_a_deleted_item(client, db_session):
    w = World(client, db_session, email="soft-delete-purge@example.com")
    item_id = _added(w)
    _web_delete(w, item_id)
    purge_data_under_lost_key(db_session, w.user.id)
    db_session.commit()
    assert _row(w, item_id) is None


def test_delete_account_removes_a_deleted_item(client, db_session):
    w = World(client, db_session, email="soft-delete-account@example.com")
    item_id = _added(w)
    _web_delete(w, item_id)
    db_session.commit()
    connection = db_session.connection()
    connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    try:
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1  # the control is on
        res = client.post(f"{API}/auth/delete-account", json={"password": PASSWORD}, headers=_bearer(w.web))
        assert res.status_code == 200, res.text
        assert db_session.query(PlannedItem).filter(PlannedItem.user_id == w.user.id).count() == 0
    finally:
        db_session.commit()
        db_session.connection().exec_driver_sql("PRAGMA foreign_keys=OFF")


def test_the_migration_downgrades_and_upgrades_with_foreign_keys_on(client, db_session):
    import importlib.util
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import inspect

    path = next((Path(__file__).resolve().parents[2] / "migrations" / "versions").glob("*_planned_item_soft_delete.py"))
    spec = importlib.util.spec_from_file_location("planned_soft_delete_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    def run(step):
        with Operations.context(MigrationContext.configure(db_session.connection())):
            step()
        db_session.commit()

    w = World(client, db_session, email="soft-delete-migration@example.com")
    item_id = _added(w)
    _web_delete(w, item_id)
    db_session.commit()
    connection = db_session.connection()
    connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    try:
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1  # the control is on
        run(migration.downgrade)
        columns = {c["name"] for c in inspect(db_session.connection()).get_columns("planned_items")}
        assert "deleted_at" not in columns
        # The deleted item stays inactive, so it still counts nowhere.
        assert db_session.execute(text("SELECT active FROM planned_items WHERE id = :i"),
                                  {"i": item_id.replace("-", "")}).scalar() in (0, False)
        run(migration.upgrade)
        columns = {c["name"] for c in inspect(db_session.connection()).get_columns("planned_items")}
        assert "deleted_at" in columns
    finally:
        db_session.rollback()
        db_session.connection().exec_driver_sql("PRAGMA foreign_keys=OFF")


def test_planning_a_transaction_again_after_a_web_delete_makes_a_fresh_item(client, db_session):
    # eng-b on #231: reusing the deleted row would make it active with
    # deleted_at still set (counted, but treated as deleted by holds and undo).
    from datetime import timedelta

    from tests.clock import TODAY
    from tests.integration.test_transactions_endpoint import _account, _tx
    w = World(client, db_session, email="soft-delete-replan@example.com")

    def purchase():
        acc = _account(db_session, w.user.id, name="Current", balance="2000")
        return str(_tx(db_session, acc, "600.00", TODAY - timedelta(days=2), merchant="Sofa Shop").id)
    tx_id = w.as_user(purchase)
    body = {"transaction_id": tx_id, "months": 6, "monthly_amount": "100.00",
            "start_date": (TODAY + timedelta(days=10)).isoformat()}
    first = w.client.post(f"{API}/analytics/planned/from-transaction", json=body, headers=_bearer(w.web))
    assert first.status_code == 201, first.text
    _web_delete(w, first.json()["id"])
    again = w.client.post(f"{API}/analytics/planned/from-transaction", json=body, headers=_bearer(w.web))
    assert again.status_code == 201, again.text
    assert again.json()["id"] != first.json()["id"]
    new_active, new_deleted, _ = _row(w, again.json()["id"])
    assert new_active and new_deleted is None
    old_active, old_deleted, _ = _row(w, first.json()["id"])
    assert not old_active and old_deleted is not None
    assert _listed(w) == [again.json()["id"]]


def test_claude_cannot_remove_an_item_the_user_deleted(client, db_session):
    w = World(client, db_session, email="soft-delete-claude@example.com")
    item_id = _added(w)
    _web_delete(w, item_id)
    assert w.remove(item_id).status_code == 404
