"""The commitment_links migration (ADR-002 section 7; sec on #203).

- The loan backfill is idempotent, skips a link whose commitment belongs to
  someone else, and logs counts only.
- Downgrade with foreign keys on, after the user linked a holding and then
  deleted the linked commitment and the holding (#180's order), then upgrade.

The migration's own functions run here through alembic's Operations, so the
tested code is the shipped code.
"""
import importlib.util
import logging
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, text

from app.models import CommitmentLink, CommitmentRule
from tests.integration.test_commitment_links import Links
from tests.integration.test_linked_commitment_guards import API, _bearer

_MIGRATION = next((Path(__file__).resolve().parents[2] / "migrations" / "versions").glob("*_commitment_links.py"))
_spec = importlib.util.spec_from_file_location("commitment_links_migration", _MIGRATION)
migration = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(migration)


def _run(db, step):
    with Operations.context(MigrationContext.configure(db.connection())):
        step()
    db.commit()
    db.expire_all()


@pytest.fixture
def links(client, db_session):
    return Links(client, db_session, email="links-migration@example.com")


def _forget_loan_rows(db):
    """The state before the migration: loan links only in the column."""
    db.execute(text("DELETE FROM commitment_links WHERE liability_id IS NOT NULL"))
    db.commit()


def _loan_rows(db):
    return {(r.liability_id, r.commitment_id, r.commitment_created)
            for r in db.query(CommitmentLink).filter(CommitmentLink.liability_id.isnot(None))}


def _backfill_lines(caplog):
    return [r.getMessage() for r in caplog.records if "Backfilling commitment_links" in r.getMessage()]


def test_the_backfill_gives_each_linked_loan_one_row_and_logs_counts(links, db_session, caplog):
    linked = links.loan()
    links.loan(lender="Irregular", opted_out=True, payment=None)  # no link
    expected = _loan_rows(db_session)
    _forget_loan_rows(db_session)

    caplog.set_level(logging.INFO)
    _run(db_session, migration.backfill)

    assert _loan_rows(db_session) == expected
    assert _backfill_lines(caplog) == ["Backfilling commitment_links for loans: linked=1 inserted=1"]
    assert linked["id"] not in caplog.text and linked["id"].replace("-", "") not in caplog.text


def test_running_the_backfill_again_inserts_nothing(links, db_session, caplog):
    links.loan()
    _forget_loan_rows(db_session)
    _run(db_session, migration.backfill)
    before = _loan_rows(db_session)
    caplog.set_level(logging.INFO)
    _run(db_session, migration.backfill)
    assert _loan_rows(db_session) == before
    assert _backfill_lines(caplog) == ["Backfilling commitment_links for loans: linked=1 inserted=0"]


def test_a_link_to_another_users_commitment_is_skipped(links, client, db_session, caplog):
    other = Links(client, db_session, email="links-migration-other@example.com")
    foreign_bill = other.commitment(label="Other DD", amount="200.00")
    loan = links.loan()
    _forget_loan_rows(db_session)
    db_session.execute(text("UPDATE liabilities SET linked_commitment_id = :c WHERE id = :l"),
                       {"c": foreign_bill.hex, "l": loan["id"].replace("-", "")})
    db_session.commit()
    caplog.set_level(logging.INFO)
    _run(db_session, migration.backfill)
    assert _loan_rows(db_session) == set()
    assert _backfill_lines(caplog) == ["Backfilling commitment_links for loans: linked=1 inserted=0"]


def test_downgrade_with_foreign_keys_on_after_the_user_deleted_what_was_linked(links, db_session):
    loan = links.loan()
    asset_id = links.asset()
    bill = links.contribution(asset_id)
    db_session.commit()
    connection = db_session.connection()
    connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    try:
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1  # the control is on
        # The user deletes the linked commitment and the holding.
        db_session.execute(text("DELETE FROM commitment_rules WHERE id = :c"), {"c": bill.hex})
        assert links.client.delete(f"{API}/assets/{asset_id}", headers=_bearer(links.web)).status_code == 200
        assert db_session.query(CommitmentLink).filter(CommitmentLink.asset_id.isnot(None)).count() == 0

        _run(db_session, migration.downgrade)
        assert "commitment_links" not in inspect(db_session.connection()).get_table_names()
        # The loan still works on its Sprint 10 column.
        loan_bill = links.loan_bill(loan["id"])
        assert db_session.query(CommitmentRule.id).filter(CommitmentRule.id == loan_bill).scalar() == loan_bill

        _run(db_session, migration.upgrade)
        assert {r[1] for r in _loan_rows(db_session)} == {loan_bill}
    finally:
        db_session.rollback()
        db_session.connection().exec_driver_sql("PRAGMA foreign_keys=OFF")
