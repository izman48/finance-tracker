"""T-08-18 (sec): relabelling a detected commitment in the app keeps its
match_key, as T-08-9 already does for Claude's edits.

sync_suggestions re-derives a *detected* rule's match_key from its label. A
user who renamed "NETFLIX.COM" to "Streaming" in the app got the key
rewritten: the payments stopped matching it (they leaked back into
spending) and the merchant was suggested again as a duplicate. The web
PATCH now marks a relabelled detected rule `manual`, whose key is left alone.
"""
import pytest

from app.models import CommitmentRule, User
from app.services import analytics_service as svc
from tests.integration.test_commitment_writes_api import API, World, _bearer, _monthly_debits, _rules, _sync


@pytest.fixture
def world(client, db_session):
    return World(client, db_session)


def _patch(world, rid, **body):
    return world.client.patch(f"{API}/analytics/commitments/{rid}", json=body, headers=_bearer(world.web))


def _detected(world):
    _monthly_debits(world, "NETFLIX.COM", "10.99")
    _sync(world)
    with world.as_user():
        rule = world.db.query(CommitmentRule).filter(CommitmentRule.user_id == world.user.id).one()
        assert rule.source == "detected"  # precondition
        return rule.id, rule.match_key


def test_renaming_in_the_app_keeps_the_key_and_is_not_re_suggested(world):
    rid, key = _detected(world)
    r = _patch(world, rid, label="Streaming", status="confirmed")
    assert r.status_code == 200, r.text
    assert r.json()["source"] == "manual"
    _sync(world)
    rule = world.rule(rid)
    assert rule.match_key == key  # not re-keyed from the new label
    assert _rules(world) == [("Streaming", "confirmed")]  # the merchant isn't suggested again
    with world.as_user():
        user = world.db.get(User, world.user.id)
        assert key in svc.commitment_match_keys(world.db, user)  # its payments still match it


def test_other_edits_leave_a_detected_commitment_detected(world):
    rid, _ = _detected(world)
    assert _patch(world, rid, amount="12.99", status="confirmed").status_code == 200
    assert world.rule(rid).source == "detected"


def test_sending_the_same_label_does_not_change_the_source(world):
    rid, _ = _detected(world)
    rule = world.rule(rid)
    assert _patch(world, rid, label=rule.label).status_code == 200
    assert world.rule(rid).source == "detected"


def test_a_manual_commitment_stays_manual(world):
    rid = world.commitment(label="Gym", source="manual")
    assert _patch(world, rid, label="Gym (PureGym)").json()["source"] == "manual"


def test_a_detected_rule_without_a_stored_key_keeps_matching_its_old_label(world):
    """eng-b's nit: a detected rule with match_key NULL (older data) falls
    back to its label's key once manual, so the rename freezes the old key."""
    rid, key = _detected(world)
    with world.as_user():
        world.db.query(CommitmentRule).filter(CommitmentRule.id == rid).update({"match_key": None})
        world.db.commit()
    old_label_key = svc.merchant_match_key(world.rule(rid).direction, world.rule(rid).label)
    assert _patch(world, rid, label="Streaming", status="confirmed").status_code == 200
    assert world.rule(rid).match_key == old_label_key
