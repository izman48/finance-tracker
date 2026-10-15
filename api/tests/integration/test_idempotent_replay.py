"""A retry of an applied Claude write replays its result (T-12-9c; sec T-12-9).

`pause_budget`, `resume_budget`, `remove_budget` and `remove_planned_event`
checked the target before `run_write` looked at the idempotency key, so a
retry of one that had applied (a dropped response, a client retry) got 422
("already paused") or 404 ("not found") instead of the stored result. Now
the key is looked at first: the same key with the same request returns the
stored result and writes nothing (row counts unchanged); the same key with a
different request is a 409. Keys stay unique per user in the database.
Synthetic figures only.
"""
import pytest

from app.models import AuditEntry, BudgetChange, WriteIdempotency
from tests.integration.test_budget_writes_api import World
from tests.integration.test_planned_events_api import World as PlanWorld
from tests.integration.test_planned_removal_hold import _added


@pytest.fixture
def w(client, db_session):
    world = World(client, db_session, email="replay@example.com")
    world.history()
    return world


def _counts(w):
    w.db.expire_all()
    return (w.count(AuditEntry), w.count(BudgetChange), w.count(WriteIdempotency))


def _budget(w, category="Eating out", limit=150):
    r = w.create(category, limit)
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.mark.parametrize("action,setup", [("pause", None), ("resume", "pause"), ("remove", None)])
def test_a_retry_of_an_applied_budget_action_replays_its_result(w, action, setup):
    budget_id = _budget(w)
    if setup:
        assert w.claude(setup, budget_id, dry_run=False).status_code == 200
    first = w.claude(action, budget_id, dry_run=False, idempotency_key=f"replay-{action}-0001")
    assert first.status_code == 200, first.text
    counts = _counts(w)
    again = w.claude(action, budget_id, dry_run=False, idempotency_key=f"replay-{action}-0001")
    assert again.status_code == 200, again.text
    assert again.json()["audit_id"] == first.json()["audit_id"]
    assert again.json()["changes"] == first.json()["changes"]
    assert again.json()["effect"] == first.json()["effect"]
    assert _counts(w) == counts  # nothing written again


def test_the_same_key_for_a_different_request_is_409(w):
    a, b = _budget(w, "Eating out"), _budget(w, "Groceries")
    assert w.claude("pause", a, dry_run=False, idempotency_key="replay-other-0001").status_code == 200
    counts = _counts(w)
    assert w.claude("pause", b, dry_run=False, idempotency_key="replay-other-0001").status_code == 409
    assert w.claude("resume", a, dry_run=False, idempotency_key="replay-other-0001").status_code == 409
    assert _counts(w) == counts


def test_a_new_key_on_an_already_paused_budget_is_still_refused(w):
    budget_id = _budget(w)
    w.claude("pause", budget_id, dry_run=False)
    assert w.claude("pause", budget_id, dry_run=False, idempotency_key="replay-fresh-0001").status_code == 422


def test_another_users_key_never_replays_for_me(w, client, db_session):
    budget_id = _budget(w)
    assert w.claude("pause", budget_id, dry_run=False, idempotency_key="replay-shared-0001").status_code == 200
    other = World(client, db_session, email="replay-other@example.com")
    other.history()
    their_budget = _budget(other)
    r = other.claude("pause", their_budget, dry_run=False, idempotency_key="replay-shared-0001")
    assert r.status_code == 200 and r.json()["target_id"] == their_budget


def test_a_retry_of_an_applied_planned_removal_replays_its_result(client, db_session):
    pw = PlanWorld(client, db_session, email="replay-plan@example.com")
    item_id = _added(pw)
    first = pw.client.post(f"/api/v1/planning/planned-events/{item_id}/remove",
                           json={"dry_run": False, "idempotency_key": "replay-rm-0001"},
                           headers={"Authorization": f"Bearer {pw.mcp}"})
    assert first.status_code == 200, first.text
    before = db_session.query(AuditEntry).count()
    again = pw.client.post(f"/api/v1/planning/planned-events/{item_id}/remove",
                           json={"dry_run": False, "idempotency_key": "replay-rm-0001"},
                           headers={"Authorization": f"Bearer {pw.mcp}"})
    assert again.status_code == 200, again.text
    assert again.json()["audit_id"] == first.json()["audit_id"]
    assert db_session.query(AuditEntry).count() == before


def test_bob_sending_alices_exact_request_gets_404_and_nothing_replays(w, client, db_session):
    # Replay runs before the ownership check, so keys must be scoped per user.
    budget_id = _budget(w)
    first = w.claude("pause", budget_id, dry_run=False, idempotency_key="replay-alice-0001")
    assert first.status_code == 200
    bob = World(client, db_session, email="replay-bob@example.com")
    counts = _counts(w)
    r = bob.claude("pause", budget_id, dry_run=False, idempotency_key="replay-alice-0001")
    assert r.status_code == 404
    assert "audit_id" not in r.json()
    assert _counts(w) == counts


def test_an_expired_key_is_not_replayed(w, db_session):
    # Past the idempotency TTL a key is forgotten (as run_write treats it):
    # the action is checked again, so an already paused budget is a 422.
    from datetime import datetime, timedelta, timezone
    budget_id = _budget(w)
    w.claude("pause", budget_id, dry_run=False, idempotency_key="replay-old-0001")
    db_session.query(WriteIdempotency).filter(WriteIdempotency.key == "replay-old-0001").update(
        {WriteIdempotency.created_at: datetime.now(timezone.utc) - timedelta(days=3)})
    db_session.commit()
    assert w.claude("pause", budget_id, dry_run=False, idempotency_key="replay-old-0001").status_code == 422
