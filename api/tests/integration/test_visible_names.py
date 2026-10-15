"""Names that become labels Claude reads are visible text (sec-1 on #245,
T-12-12): a lender (its repayment commitment), an asset name (its linked
contribution) and a card-plan name (its instalment row) refuse hidden and
control characters with 422, as commitment labels do. Synthetic."""
import pytest

from tests.integration.test_card_plans_api import world  # noqa: F401 (fixture)
from tests.integration.test_liabilities_api import alice  # noqa: F401 (fixture)
from tests.integration.test_oauth import _bearer

API = "/api/v1"
HIDDEN = ["Lender\u202eA", "Lender\x00", "Lender\u200b", "   "]


@pytest.mark.parametrize("lender", HIDDEN)
def test_a_lender_with_hidden_characters_is_422(alice, lender):  # noqa: F811
    assert alice.create(lender=lender).status_code == 422
    assert alice.list().json() == []


def test_a_lender_rename_with_hidden_characters_is_422(alice):  # noqa: F811
    lid = alice.create().json()["id"]
    assert alice.patch(lid, lender="Lender\u202eB").status_code == 422


@pytest.mark.parametrize("name", HIDDEN)
def test_an_asset_name_with_hidden_characters_is_422(alice, name):  # noqa: F811
    res = alice.client.post(f"{API}/assets", json={"name": name, "asset_type": "isa", "value": "100.00"},
                            headers=_bearer(alice.token))
    assert res.status_code == 422, res.text


def test_an_asset_rename_with_hidden_characters_is_422(alice):  # noqa: F811
    aid = alice.client.post(f"{API}/assets", json={"name": "Sample ISA", "asset_type": "isa", "value": "100.00"},
                            headers=_bearer(alice.token)).json()["id"]
    res = alice.client.patch(f"{API}/assets/{aid}", json={"name": "ISA\u202e"}, headers=_bearer(alice.token))
    assert res.status_code == 422, res.text


@pytest.mark.parametrize("name", HIDDEN)
def test_a_card_plan_name_with_hidden_characters_is_422(world, name):  # noqa: F811
    assert world.plan(name=name).status_code == 422


# --- a name stored before this check still allows other edits (sec-1 on #249) ---

STORED = "Lender\u202eOld"


def _store_hidden(db, token, model, row_id, field):
    """Write a hidden-character name under the user's key, as data from
    before this check would be."""
    import uuid
    from app.core import user_crypto
    from tests.integration.test_transactions_endpoint import _dek_from_token
    ctx = user_crypto.current_dek.set(_dek_from_token(token))
    try:
        row = db.get(model, uuid.UUID(str(row_id)))
        setattr(row, field, STORED)
        db.commit()
    finally:
        user_crypto.current_dek.reset(ctx)


def test_a_stored_hidden_lender_does_not_block_other_edits(alice, db_session):  # noqa: F811
    from app.models import Liability
    lid = alice.create().json()["id"]
    _store_hidden(db_session, alice.token, Liability, lid, "lender")
    assert alice.patch(lid, balance="8000.00").status_code == 200
    assert alice.patch(lid, lender=STORED, apr="10.00").status_code == 200  # sent back unchanged
    assert alice.patch(lid, lender="New\u202eName").status_code == 422


def test_a_stored_hidden_asset_name_does_not_block_other_edits(alice, db_session):  # noqa: F811
    from app.models import Asset
    aid = alice.client.post(f"{API}/assets", json={"name": "Sample ISA", "asset_type": "isa", "value": "100.00"},
                            headers=_bearer(alice.token)).json()["id"]
    _store_hidden(db_session, alice.token, Asset, aid, "name")
    res = alice.client.patch(f"{API}/assets/{aid}", json={"name": STORED, "assumed_growth_pct": "4"},
                             headers=_bearer(alice.token))
    assert res.status_code == 200, res.text


def test_a_stored_hidden_plan_name_does_not_block_other_edits(world, db_session):  # noqa: F811
    from app.models import CardPlan
    pid = world.plan().json()["id"]
    world.as_user(lambda: (setattr(db_session.get(CardPlan, __import__("uuid").UUID(pid)), "name", STORED), db_session.commit()))
    res = world.client.patch(f"{API}/card-plans/{pid}", json={"name": STORED, "fee": "2.00"}, headers=world.h)
    assert res.status_code == 200, res.text
    res = world.client.patch(f"{API}/card-plans/{pid}", json={"name": "Plan\u200b"}, headers=world.h)
    assert res.status_code == 422
