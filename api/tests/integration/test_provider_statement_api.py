"""Manual and provider statements side by side (T-10-2, ux A3, sec b).

Manual wins for the same period. Editing a provider statement writes the
user's own (manual) statement for that period; the provider row is left for
sync. When both exist and differ, the API says so, and "use this statement"
picks one by id. Synthetic fixture: statement £5,000, current £6,000.
"""
import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.models import CardStatement
from tests.integration.test_card_statements_api import DUE_DATE, STATEMENT, STATEMENT_DATE, Person


@pytest.fixture
def alice(client, db_session):
    return Person(client, db_session, "alice@example.com")


@pytest.fixture
def bob(client, db_session):
    return Person(client, db_session, "bob@example.com")


def _provider(person, db, balance="5000.00", card_id=None):
    with person.key():
        row = CardStatement(
            user_id=person.user_id, account_id=card_id or person.card_id, statement_date=STATEMENT_DATE,
            due_date=DUE_DATE, statement_balance=Decimal(balance), source="provider",
        )
        db.add(row)
        db.commit()
        return str(row.id)


def _rows(db):
    return sorted(map(tuple, db.execute(text("SELECT * FROM card_statements")).fetchall()), key=str)


def _use(person, statement_id, card_id=None):
    return person.client.put(f"{person.url(card_id, statement_id)}/in-use", headers=person.headers)


def test_editing_a_provider_statement_saves_a_manual_one_for_that_period(alice, db_session):
    provider_id = _provider(alice, db_session)

    res = alice.client.patch(alice.url(statement_id=provider_id), json={"statement_balance": "4900.00"},
                             headers=alice.headers)

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["source"] == "manual" and body["id"] != provider_id
    assert Decimal(body["statement_balance"]) == Decimal("4900.00")
    assert body["statement_date"] == STATEMENT_DATE.isoformat()
    with alice.key():
        provider = db_session.get(CardStatement, uuid.UUID(provider_id))
        db_session.refresh(provider)
        assert provider.statement_balance == Decimal("5000.00")  # left for sync
    assert alice.get().json()["current"]["statement_id"] == body["id"]


def test_editing_a_provider_statement_again_updates_the_same_manual_row(alice, db_session):
    provider_id = _provider(alice, db_session)
    alice.add()  # a manual one for the same period already exists

    res = alice.client.patch(alice.url(statement_id=provider_id), json={"statement_balance": "4800.00"},
                             headers=alice.headers)

    assert res.status_code == 200
    manual = [s for s in alice.get().json()["statements"] if s["source"] == "manual"]
    assert len(manual) == 1 and Decimal(manual[0]["statement_balance"]) == Decimal("4800.00")


def test_a_provider_statement_cannot_be_deleted(alice, db_session):
    provider_id = _provider(alice, db_session)
    before = _rows(db_session)

    res = alice.client.delete(alice.url(statement_id=provider_id), headers=alice.headers)

    assert res.status_code == 409
    assert _rows(db_session) == before


def test_both_are_returned_with_a_conflict_when_they_differ(alice, db_session):
    provider_id = _provider(alice, db_session, balance="4990.00")
    manual_id = alice.add().json()["id"]

    body = alice.get().json()

    assert {s["id"] for s in body["statements"]} == {provider_id, manual_id}
    assert body["current"]["statement_id"] == manual_id  # manual wins
    assert body["conflict"] is True


def test_no_conflict_when_they_agree_or_only_one_exists(alice, db_session):
    _provider(alice, db_session)
    assert alice.get().json()["conflict"] is False
    alice.add(STATEMENT)  # same figures
    assert alice.get().json()["conflict"] is False


def test_using_the_provider_statement_replaces_the_manual_one_for_that_period(alice, db_session):
    provider_id = _provider(alice, db_session, balance="4990.00")
    alice.add()

    res = _use(alice, provider_id)

    assert res.status_code == 200, res.text
    body = alice.get().json()
    assert body["current"]["statement_id"] == provider_id
    assert body["conflict"] is False
    assert [s["source"] for s in body["statements"]] == ["provider"]


def test_using_the_manual_statement_keeps_both_and_changes_nothing(alice, db_session):
    _provider(alice, db_session, balance="4990.00")
    manual_id = alice.add().json()["id"]
    before = _rows(db_session)

    res = _use(alice, manual_id)

    assert res.status_code == 200
    assert _rows(db_session) == before
    assert alice.get().json()["current"]["statement_id"] == manual_id


def test_use_checks_the_statement_belongs_to_this_card_and_user(alice, bob, db_session):
    bobs = _provider(bob, db_session)
    mine_other_card = _provider(alice, db_session, card_id=alice.other_card_id)
    alice.add()
    before = _rows(db_session)

    assert _use(alice, bobs).status_code == 404
    assert _use(alice, mine_other_card).status_code == 404
    assert _use(alice, uuid.uuid4()).status_code == 404
    assert _use(alice, mine_other_card, card_id=bob.card_id).status_code == 404
    assert _rows(db_session) == before


def test_a_provider_statement_for_an_older_period_is_not_a_conflict(alice, db_session):
    with alice.key():
        db_session.add(CardStatement(
            user_id=alice.user_id, account_id=alice.card_id, statement_date=STATEMENT_DATE - timedelta(days=31),
            due_date=DUE_DATE - timedelta(days=31), statement_balance=Decimal("1.00"), source="provider",
        ))
        db_session.commit()
    alice.add()

    assert alice.get().json()["conflict"] is False
