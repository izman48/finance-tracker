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
