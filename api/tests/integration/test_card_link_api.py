"""Setting a commitment's card link explicitly (T-08-8).

The link goes through the shared ownership helper (T-08-2), so another
user's card is a 404 with nothing written (pinned in
test_account_ownership.py). A link set here is marked "user", so the
request-time linker never changes it, including an explicit "no card".
"""
from app.core import user_crypto
from app.models import CommitmentRule
from tests.integration.test_account_ownership import API, World


def _patch(world, body):
    return world.client.patch(f"{API}/analytics/commitments/{world.commitment_id}", json=body)


def _stored(world):
    world.db.expire_all()
    ctx = user_crypto.current_dek.set(world.dek_a)
    try:
        rule = world.db.get(CommitmentRule, world.commitment_id)
        return rule.card_account_id, rule.card_link_source
    finally:
        user_crypto.current_dek.reset(ctx)


def test_linking_to_an_own_card_is_stored_as_the_users_choice(client, db_session):
    world = World(client, db_session)
    res = _patch(world, {"card_account_id": str(world.a_card_id)})
    assert res.status_code == 200, res.text
    assert res.json()["card_account_id"] == str(world.a_card_id)
    assert _stored(world) == (world.a_card_id, "user")


def test_an_explicit_no_card_survives_the_linker(client, db_session):
    world = World(client, db_session)
    assert _patch(world, {"label": "AMEX", "card_account_id": None}).status_code == 200
    # Loading commitments runs sync_suggestions, which runs the linker.
    assert client.get(f"{API}/analytics/commitments").status_code == 200
    assert _stored(world) == (None, "user")


def test_other_edits_leave_the_link_alone(client, db_session):
    world = World(client, db_session)
    _patch(world, {"card_account_id": str(world.a_card_id)})
    assert _patch(world, {"amount": "45"}).status_code == 200
    assert _stored(world) == (world.a_card_id, "user")
