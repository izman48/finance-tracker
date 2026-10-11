"""Claude removing a planned expense raises nothing until the user keeps it
(T-08-21b part 2, sec; owner decision D5 = yes).

A planned expense counts in safe-to-spend and savable (T-08-6). Removing it
over MCP would raise both at once, so the removal is held: the item keeps
counting until the user keeps the change on its Changes row (keep_kind
"expense_cut"; planned rows themselves never carry Keep, ux 9.1). Undo
brings the item back as normal. Removing planned income needs no keep:
planned income never counts (D1).
"""
from decimal import Decimal

from tests.integration.test_oauth import _bearer
from tests.integration.test_planned_events_api import API, SOON, World, _with_cash


def _money(w):
    s = w.summary()
    return (Decimal(s["committed_before_payday"]), Decimal(s["safe_to_spend"]), Decimal(s["savable"]))


def _audit_row(w, audit_id):
    items = w.client.get(f"{API}/audit", headers=_bearer(w.web)).json()["items"]
    return next(i for i in items if i["id"] == audit_id)


def _keep(w, audit_id, token=None):
    return w.client.post(f"{API}/audit/{audit_id}/keep", headers=_bearer(token or w.web))


def _added(w, **fields):
    _with_cash(w)
    return w.add(amount="200.00", date=SOON.isoformat(), **fields).json()["target_id"]


def test_a_removed_planned_expense_keeps_counting_until_kept(client, db_session):
    w = World(client, db_session)
    item_id = _added(w)
    before = _money(w)
    audit_id = w.remove(item_id).json()["audit_id"]
    assert _money(w) == before
    assert Decimal(w.summary()["safe_to_spend_pending_keep_total"]) == Decimal("200.00")
    assert _keep(w, audit_id).status_code == 200
    committed, safe, savable = _money(w)
    assert (committed, safe, savable) == (before[0] - 200, before[1] + 200, before[2] + 200)
    assert Decimal(w.summary()["safe_to_spend_pending_keep_total"]) == Decimal(0)


def test_its_changes_row_is_pending_then_kept(client, db_session):
    w = World(client, db_session)
    item_id = _added(w)
    audit_id = w.remove(item_id).json()["audit_id"]
    row = _audit_row(w, audit_id)
    assert (row["keep"], row["keep_kind"]) == ("pending", "expense_cut")
    _keep(w, audit_id)
    row = _audit_row(w, audit_id)
    assert (row["keep"], row["keep_kind"]) == ("kept", "expense_cut")
    assert row["kept_at"] is not None


def test_the_add_is_not_held(client, db_session):
    """Adding a planned expense lowers safe-to-spend: applies at once."""
    w = World(client, db_session)
    _added(w)
    add_row = w.client.get(f"{API}/audit", headers=_bearer(w.web)).json()["items"][0]
    assert add_row["keep"] is None


def test_removing_planned_income_needs_no_keep(client, db_session):
    w = World(client, db_session)
    item_id = _added(w, direction="income")
    audit_id = w.remove(item_id).json()["audit_id"]
    assert _audit_row(w, audit_id)["keep"] is None
    assert _keep(w, audit_id).status_code == 409


def test_undo_of_a_pending_removal_brings_it_back(client, db_session):
    w = World(client, db_session)
    item_id = _added(w)
    before = _money(w)
    audit_id = w.remove(item_id).json()["audit_id"]
    assert w.client.post(f"{API}/audit/{audit_id}/undo", headers=_bearer(w.web)).status_code == 200
    assert w.item(item_id).active is True
    assert _money(w) == before
    assert _audit_row(w, audit_id)["keep"] is None


def test_an_mcp_token_cannot_keep_a_removal(client, db_session):
    w = World(client, db_session)
    item_id = _added(w)
    before = _money(w)
    audit_id = w.remove(item_id).json()["audit_id"]
    assert _keep(w, audit_id, token=w.mcp).status_code == 401
    assert _money(w) == before
