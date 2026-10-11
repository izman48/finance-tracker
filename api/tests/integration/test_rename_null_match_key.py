"""A detected commitment with no stored match_key (older rows) keeps
matching its payments when renamed, in the app or by Claude.

A rename makes a detected rule manual (T-08-9, T-08-18), and a manual rule
without a key falls back to its *label's* key, so the new name would stop
its payments matching. The rename stores the old label's key first.
"""
import pytest

from app.services import analytics_service as svc
from tests.integration.test_commitment_writes_api import API, World, _bearer

OLD_KEY = "expense:netflix"


@pytest.fixture
def world(client, db_session):
    return World(client, db_session)


def _keyless_detected(world):
    return world.commitment(label="Netflix", source="detected", match_key=None)


def test_a_web_rename_stores_the_old_labels_key(world):
    rid = _keyless_detected(world)
    res = world.client.patch(f"{API}/analytics/commitments/{rid}", json={"label": "Streaming"},
                             headers=_bearer(world.web))
    assert res.status_code == 200, res.text
    rule = world.rule(rid)
    assert (rule.source, rule.match_key) == ("manual", OLD_KEY)


def test_a_merchant_set_in_the_same_web_edit_wins(world):
    rid = _keyless_detected(world)
    world.client.patch(f"{API}/analytics/commitments/{rid}", json={"label": "Streaming", "match_merchant": "NFLX"},
                       headers=_bearer(world.web))
    assert world.rule(rid).match_key == svc.merchant_match_key("expense", "NFLX")


def test_claudes_rename_stores_the_old_labels_key_and_undo_restores_it(world):
    rid = _keyless_detected(world)
    res = world.update(rid, label="Streaming", dry_run=False)
    assert res.status_code == 200, res.text
    rule = world.rule(rid)
    assert (rule.source, rule.match_key) == ("manual", OLD_KEY)

    undo = world.client.post(f"{API}/audit/{res.json()['audit_id']}/undo", headers=_bearer(world.web))
    assert undo.status_code == 200, undo.text
    rule = world.rule(rid)
    assert (rule.label, rule.source, rule.match_key) == ("Netflix", "detected", None)


def test_a_stored_key_is_left_alone(world):
    rid = world.commitment(label="Netflix", source="detected", match_key="expense:netflix.com")
    assert world.update(rid, label="Streaming", dry_run=False).status_code == 200
    assert world.rule(rid).match_key == "expense:netflix.com"


def test_claudes_rename_of_a_keyless_manual_commitment_keeps_what_it_matched(world):
    """sec on #127: a manual rule with no key matches by its label, so Claude
    renaming "Gym" to "Amazon" would quietly start matching Amazon payments."""
    rid = world.commitment(label="Gym", source="manual", match_key=None)
    assert world.update(rid, label="Amazon", dry_run=False).status_code == 200
    rule = world.rule(rid)
    assert (rule.source, rule.match_key) == ("manual", "expense:gym")
