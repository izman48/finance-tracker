"""The undo record's size cap (T-16-3).

An applied rule edit stores one record per transaction it recategorises
(`audit_entries.side_effects`, for undo). Claude's edit is capped at 5,000
such transactions, server-side: a preview over the cap says `over_cap` with
the real count; an apply over it is a 409 with fixed text pointing to the
Rules page, and nothing is kept, not the rule, the categories, the audit
row or the idempotency key. The web Rules page is not capped (no undo record).
"""
import json
import uuid

import pytest
from sqlalchemy import text

from app.models import AuditEntry, WriteIdempotency
from app.routers.rule_writes import RECATEGORISE_CAP
from tests.integration.test_oauth import _bearer
from tests.integration.test_rule_writes_api import API, World

OVER_CAP = "This change would recategorise more than 5,000 transactions. Make it on the Rules page."


def _world(client, db_session, n: int) -> tuple[World, str]:
    """n transactions no rule matches yet, and a rule Claude will widen to all of them."""
    w = World(client, db_session, email=f"cap-{n}@example.com")
    w.transactions([(f"SHOP {i}", 1) for i in range(n)])
    return w, w.rule(pattern="NOTHING MATCHES", category="Groceries")


def test_the_cap_is_5000():
    assert RECATEGORISE_CAP == 5000


def test_a_preview_over_the_cap_says_so_with_the_count(client, db_session):
    w, rule_id = _world(client, db_session, RECATEGORISE_CAP + 1)
    r = w.update(rule_id, pattern="SHOP")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["over_cap"] is True
    assert body["transactions_recategorized"] == RECATEGORISE_CAP + 1
    assert w.count(AuditEntry) == 0


def test_an_apply_over_the_cap_is_refused_and_keeps_nothing(client, db_session):
    w, rule_id = _world(client, db_session, RECATEGORISE_CAP + 1)
    before = w.categories()
    r = w.update(rule_id, pattern="SHOP", idempotency_key="cap-retry-key-1", dry_run=False)
    assert r.status_code == 409
    assert r.json()["detail"] == OVER_CAP
    assert w.listed(rule_id)["pattern"] == "NOTHING MATCHES"
    assert w.categories() == before
    assert w.count(AuditEntry) == 0
    assert w.count(WriteIdempotency) == 0

    # The key went with it: a narrowed retry under the same key is new, and applies.
    narrowed = w.update(rule_id, pattern="SHOP 1", idempotency_key="cap-retry-key-1", dry_run=False)
    assert narrowed.status_code == 200, narrowed.text
    assert narrowed.json()["over_cap"] is False
    assert 0 < narrowed.json()["transactions_recategorized"] <= RECATEGORISE_CAP
    assert w.count(AuditEntry) == 1


def test_an_apply_at_the_cap_is_stored_and_undoable(client, db_session):
    w, rule_id = _world(client, db_session, RECATEGORISE_CAP)
    preview = w.update(rule_id, pattern="SHOP")
    assert preview.json()["over_cap"] is False
    r = w.update(rule_id, pattern="SHOP", dry_run=False)
    assert r.status_code == 200, r.text
    assert r.json()["transactions_recategorized"] == RECATEGORISE_CAP
    assert set(w.categories().values()) == {"Groceries"}
    assert w.undo(r.json()["audit_id"]).status_code == 200
    assert set(w.categories().values()) == {None}


def test_the_web_rules_page_is_not_capped(client, db_session):
    """The user acts directly there, and it keeps no undo record."""
    w, rule_id = _world(client, db_session, RECATEGORISE_CAP + 1)
    r = w.client.patch(f"{API}/rules/{rule_id}", json={"pattern": "SHOP"}, headers=_bearer(w.web))
    assert r.status_code == 200, r.text
    assert w.client.post(f"{API}/rules/apply", headers=_bearer(w.web)).status_code == 200
    assert set(w.categories().values()) == {"Groceries"}


@pytest.fixture
def w(client, db_session):
    return World(client, db_session)


def test_a_full_record_is_under_2mb_once_encrypted(w):
    """sec: 5,000 records of a 36-char id and two 100-char categories, the
    largest record the cap allows, stay under 2 MB as stored ciphertext."""
    record = [{"id": str(uuid.uuid4()), "before": "b" * 100, "after": "a" * 100} for _ in range(RECATEGORISE_CAP)]

    def store():
        w.db.add(AuditEntry(user_id=w.user.id, kind="write", tool="update_rule", target_kind="rule",
                            target_id=uuid.uuid4(), target_label="x", changes="[]",
                            side_effects=json.dumps(record)))
        w.db.commit()
    w.as_user(store)
    stored = w.db.execute(text("SELECT side_effects FROM audit_entries")).scalar_one()
    assert len(json.dumps(record)) > 1_000_000  # it is the full-size record
    assert '"before"' not in stored and "b" * 100 not in stored  # ciphertext, not the JSON
    assert len(stored) < 2 * 1024 * 1024
