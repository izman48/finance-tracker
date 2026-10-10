"""Planned events Claude adds and removes (T-08-6, API side).

Routes: POST /planning/planned-events (add), POST /planning/planned-events/{id}/remove,
GET /planning/planned-events (read, max 200). Writes go through the T-08-3
framework (scope, dry_run default true, idempotency, audit, undo, rate limit).

Money rules (fail safe, owner decision D1 = a):
  - a planned expense counts in safe-to-spend and committed-before-payday;
  - planned income shows in the forecast but never raises safe-to-spend or
    savable until the credit lands (a fake "refund coming" can't unlock spending).
"""
import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.core import user_crypto
from app.models import PlannedItem, User
from tests.integration.test_oauth import READ, _bearer, _connect
from tests.integration.test_transactions_endpoint import _account, _dek_from_token

API = "/api/v1"
PLANNING = "finance:planning.write"
TODAY = date.today()
SOON = TODAY + timedelta(days=10)


class World:
    def __init__(self, client, db, email="plan@example.com", scopes=(READ, PLANNING)):
        self.client, self.db = client, db
        self.web, _, tokens = _connect(client, scopes=scopes, email=email)
        self.mcp = tokens["access_token"]
        self.dek = _dek_from_token(self.web)
        self.user = db.query(User).filter(User.email == email).one()
        self.n = 0

    def as_user(self, fn):
        token = user_crypto.current_dek.set(self.dek)
        try:
            return fn()
        finally:
            user_crypto.current_dek.reset(token)

    def add(self, *, dry_run=False, key=None, token=None, **fields):
        self.n += 1
        body = {
            "name": "Car insurance", "amount": "200.00", "date": SOON.isoformat(), "direction": "expense",
            "idempotency_key": key or f"add-key-{self.n:04d}", **fields,
        }
        if dry_run is not None:
            body["dry_run"] = dry_run
        return self.client.post(f"{API}/planning/planned-events", json=body, headers=_bearer(token or self.mcp))

    def remove(self, item_id, *, dry_run=False, token=None):
        self.n += 1
        return self.client.post(
            f"{API}/planning/planned-events/{item_id}/remove",
            json={"dry_run": dry_run, "idempotency_key": f"rm-key-{self.n:04d}"},
            headers=_bearer(token or self.mcp),
        )

    def summary(self):
        return self.client.get(f"{API}/analytics/summary", headers=_bearer(self.web)).json()

    def item(self, item_id):
        def load():
            self.db.expire_all()
            return self.db.get(PlannedItem, uuid.UUID(str(item_id)))
        return self.as_user(load)


def _counts(db):
    return tuple(db.execute(text(f"SELECT count(*) FROM {t}")).scalar()
                 for t in ("planned_items", "audit_entries", "write_idempotency"))


# --- add -----------------------------------------------------------------------------


def test_add_previews_by_default_and_writes_nothing(client, db_session):
    w = World(client, db_session)
    counts = _counts(db_session)
    res = w.add(dry_run=None)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["dry_run"] is True and body["audit_id"] is None
    assert {"field": "amount", "before": None, "after": "200.00"} in body["changes"]
    assert _counts(db_session) == counts


def test_add_creates_a_one_off_mcp_item_that_the_forecast_shows(client, db_session):
    w = World(client, db_session)
    res = w.add()
    assert res.status_code == 200, res.text
    item = w.item(res.json()["target_id"])
    assert (item.kind, item.created_via, item.active, item.direction) == ("one_off", "mcp", True, "expense")
    assert item.amount == Decimal("200.00") and item.start_date == SOON

    forecast = client.get(f"{API}/analytics/forecast", params={"horizon": "30"}, headers=_bearer(w.web)).json()
    day = next(p for p in forecast["timeline"] if p["date"] == SOON.isoformat())
    assert {"label": "Car insurance", "amount": "-200.00", "kind": "planned"} in day["events"]


def test_a_read_only_token_cannot_add_or_remove(client, db_session):
    w = World(client, db_session, scopes=(READ,))
    assert w.add().status_code == 403
    assert w.remove(uuid.uuid4()).status_code == 403


@pytest.mark.parametrize("field,value", [
    ("name", ""),
    ("name", "x" * 101),
    ("name", "Rent\x07"),
    ("name", "Rent\u202eevil"),
    ("amount", "0"),
    ("amount", "-5"),
    ("amount", "1000000.01"),
    ("amount", "1.001"),
    ("amount", 12.5),
    ("date", (TODAY - timedelta(days=31)).isoformat()),
    ("date", (TODAY + timedelta(days=5 * 366 + 2)).isoformat()),
    ("date", "not-a-date"),
    ("direction", "transfer"),
    ("user_id", str(uuid.uuid4())),
    ("created_via", "web"),
    ("kind", "recurring"),
    ("dry_run", "false"),
])
def test_out_of_range_input_is_422_and_writes_nothing(client, db_session, field, value):
    w = World(client, db_session)
    counts = _counts(db_session)
    res = w.add(**{field: value})
    assert res.status_code == 422, res.text
    assert _counts(db_session) == counts


def test_the_bounds_themselves_are_accepted(client, db_session):
    w = World(client, db_session)
    assert w.add(name="x" * 100, amount="1000000.00", date=(TODAY - timedelta(days=30)).isoformat()).status_code == 200
    assert w.add(name="y", amount="0.01", date=(TODAY + timedelta(days=5 * 365)).isoformat()).status_code == 200


def test_another_users_account_id_is_404(client, db_session):
    owner = World(client, db_session, "owner@example.com")
    foreign = owner.as_user(lambda: _account(db_session, owner.user.id, name="Owner current").id)
    w = World(client, db_session, "w@example.com")
    counts = _counts(db_session)
    assert w.add(account_id=str(foreign)).status_code == 404
    assert _counts(db_session) == counts


def test_own_account_id_is_kept(client, db_session):
    w = World(client, db_session)
    acc = w.as_user(lambda: _account(db_session, w.user.id, name="Current").id)
    res = w.add(account_id=str(acc))
    assert res.status_code == 200 and w.item(res.json()["target_id"]).account_id == acc


# --- duplicate guard ----------------------------------------------------------------


def test_a_retry_with_a_fresh_key_returns_the_existing_item(client, db_session):
    """Claude may retry with a new key; for income above all, a duplicate
    would overstate money coming in."""
    w = World(client, db_session)
    first = w.add(direction="income", name="Refund from Shop").json()
    counts = _counts(db_session)
    again = w.add(direction="income", name="  refund  FROM shop ")
    assert again.status_code == 200
    assert again.json()["duplicate"] is True
    assert again.json()["target_id"] == first["target_id"]
    assert _counts(db_session) == counts


@pytest.mark.parametrize("change", [
    {"amount": "201.00"}, {"date": (SOON + timedelta(days=1)).isoformat()}, {"direction": "income"},
    {"name": "Car tax"},
])
def test_a_different_event_is_not_a_duplicate(client, db_session, change):
    w = World(client, db_session)
    w.add()
    res = w.add(**change)
    assert res.json()["duplicate"] is False and res.json()["audit_id"]


def test_the_duplicate_window_is_24_hours(client, db_session):
    w = World(client, db_session)
    w.add()
    db_session.execute(text("UPDATE planned_items SET created_at = :t"), {"t": TODAY - timedelta(days=2)})
    db_session.commit()
    assert w.add().json()["duplicate"] is False


def test_a_removed_item_is_not_a_duplicate(client, db_session):
    w = World(client, db_session)
    first = w.add().json()
    w.remove(first["target_id"])
    assert w.add().json()["duplicate"] is False


# --- remove ---------------------------------------------------------------------------


def test_remove_soft_deletes_and_audits_amount_and_date(client, db_session):
    w = World(client, db_session)
    item_id = w.add().json()["target_id"]
    res = w.remove(item_id)
    assert res.status_code == 200, res.text
    assert w.item(item_id).active is False  # soft: undo can bring it back
    changes = res.json()["changes"]
    assert {"field": "active", "before": True, "after": False} in changes
    assert {"field": "amount", "before": "200.00", "after": "200.00"} in changes
    assert {"field": "start_date", "before": SOON.isoformat(), "after": SOON.isoformat()} in changes


def test_remove_previews_by_default(client, db_session):
    w = World(client, db_session)
    item_id = w.add().json()["target_id"]
    res = w.remove(item_id, dry_run=True)
    assert res.json()["dry_run"] is True and w.item(item_id).active is True


def test_undo_of_a_remove_brings_it_back(client, db_session):
    w = World(client, db_session)
    item_id = w.add().json()["target_id"]
    audit_id = w.remove(item_id).json()["audit_id"]
    assert client.post(f"{API}/audit/{audit_id}/undo", headers=_bearer(w.web)).status_code == 200
    assert w.item(item_id).active is True


def test_items_made_in_the_app_cannot_be_removed(client, db_session):
    w = World(client, db_session)
    made = client.post(
        f"{API}/analytics/planned-items",
        json={"name": "Holiday", "kind": "one_off", "start_date": SOON.isoformat(), "amount": "500"},
        headers=_bearer(w.web),
    ).json()
    counts = _counts(db_session)
    assert w.remove(made["id"]).status_code == 404
    assert w.item(made["id"]).active is True
    assert _counts(db_session) == counts


def test_a_recurring_or_plan_item_cannot_be_removed_even_if_mcp_made(client, db_session):
    w = World(client, db_session)
    item_id = w.add().json()["target_id"]
    db_session.execute(text("UPDATE planned_items SET kind = 'installment_plan'"))
    db_session.commit()
    assert w.remove(item_id).status_code == 404


def test_another_users_item_or_an_unknown_id_is_404(client, db_session):
    a = World(client, db_session, "a@example.com")
    item_id = a.add().json()["target_id"]
    b = World(client, db_session, "b@example.com")
    assert b.remove(item_id).status_code == 404
    assert b.remove(uuid.uuid4()).status_code == 404
    assert a.item(item_id).active is True


def test_an_already_removed_item_is_404(client, db_session):
    w = World(client, db_session)
    item_id = w.add().json()["target_id"]
    w.remove(item_id)
    assert w.remove(item_id).status_code == 404


# --- list -----------------------------------------------------------------------------


def test_list_is_a_read_and_shows_who_made_each_item(client, db_session):
    w = World(client, db_session, scopes=(READ, PLANNING))
    mcp_item = w.add().json()["target_id"]
    client.post(f"{API}/analytics/planned-items",
                json={"name": "Holiday", "kind": "one_off", "start_date": SOON.isoformat(), "amount": "500"},
                headers=_bearer(w.web))
    _, _, read_only = _connect(client, scopes=(READ,), email="plan@example.com")
    res = client.get(f"{API}/planning/planned-events", headers=_bearer(read_only["access_token"]))
    assert res.status_code == 200, res.text
    items = {i["name"]: i for i in res.json()["items"]}
    assert items["Car insurance"]["created_via"] == "mcp" and items["Car insurance"]["id"] == mcp_item
    assert items["Holiday"]["created_via"] == "web"
    assert items["Car insurance"]["changed_by_claude"]["audit_id"]
    assert items["Holiday"]["changed_by_claude"] is None


def test_list_is_capped_at_200(client, db_session):
    w = World(client, db_session)
    def seed():
        for n in range(205):
            db_session.add(PlannedItem(user_id=w.user.id, name=f"Item {n}", kind="one_off",
                                       start_date=SOON, amount=Decimal("1")))
        db_session.commit()
    w.as_user(seed)
    res = client.get(f"{API}/planning/planned-events", headers=_bearer(w.mcp))
    assert len(res.json()["items"]) == 200 and res.json()["truncated"] is True


def test_the_app_list_marks_claude_changes_until_undone(client, db_session):
    w = World(client, db_session)
    audit_id = w.add().json()["audit_id"]
    rows = client.get(f"{API}/analytics/planned-items", headers=_bearer(w.web)).json()
    assert rows[0]["changed_by_claude"]["audit_id"] == audit_id
    client.post(f"{API}/audit/{audit_id}/undo", headers=_bearer(w.web))
    assert client.get(f"{API}/analytics/planned-items", headers=_bearer(w.web)).json() == []  # soft-deleted


# --- money rules --------------------------------------------------------------------


def _with_cash(w, balance="1000.00"):
    w.as_user(lambda: _account(db=w.db, user_id=w.user.id, name="Current", balance=balance))


def test_a_planned_expense_before_payday_reduces_safe_to_spend(client, db_session):
    w = World(client, db_session)
    _with_cash(w)
    before = w.summary()
    w.add(amount="200.00", date=SOON.isoformat())
    after = w.summary()
    assert Decimal(after["committed_before_payday"]) == Decimal(before["committed_before_payday"]) + 200
    assert Decimal(after["safe_to_spend"]) == Decimal(before["safe_to_spend"]) - 200
    assert Decimal(after["savable"]) == Decimal(before["savable"]) - 200


def test_a_planned_expense_after_the_window_does_not(client, db_session):
    w = World(client, db_session)
    _with_cash(w)
    before = w.summary()
    w.add(amount="200.00", date=(TODAY + timedelta(days=60)).isoformat())
    assert w.summary()["safe_to_spend"] == before["safe_to_spend"]


@pytest.mark.parametrize("via", ["mcp", "web"])
def test_planned_income_never_raises_safe_to_spend_or_savable(client, db_session, via):
    w = World(client, db_session)
    _with_cash(w)
    w.add(amount="300.00")  # an expense, so the figures are not at a floor of zero
    before = w.summary()
    if via == "mcp":
        assert w.add(direction="income", name="Refund", amount="5000.00").status_code == 200
    else:
        client.post(f"{API}/analytics/planned-items", headers=_bearer(w.web), json={
            "name": "Refund", "direction": "income", "kind": "one_off",
            "start_date": SOON.isoformat(), "amount": "5000"})
    after = w.summary()
    assert after["safe_to_spend"] == before["safe_to_spend"]
    assert after["savable"] == before["savable"]
    assert after["committed_before_payday"] == before["committed_before_payday"]
    # It is still visible in the forecast (D1 = a).
    forecast = client.get(f"{API}/analytics/forecast", params={"horizon": "30"}, headers=_bearer(w.web)).json()
    labels = [e["label"] for p in forecast["timeline"] for e in p["events"]]
    assert "Refund" in labels


def test_coming_up_sees_a_claude_added_item(client, db_session):
    """Home and Cashflow build "coming up" from /analytics/planned-items."""
    w = World(client, db_session)
    w.add()
    names = [i["name"] for i in client.get(f"{API}/analytics/planned-items", headers=_bearer(w.web)).json()]
    assert names == ["Car insurance"]


def test_a_same_key_retry_replays_the_first_result_not_a_duplicate(client, db_session):
    """An idempotent retry (same key, same body) gets the first write's result
    back, audit id included; the duplicate guard is for fresh keys only."""
    w = World(client, db_session)
    first = w.add(key="same-key-0001").json()
    counts = _counts(db_session)
    again = w.add(key="same-key-0001")
    assert again.status_code == 200
    assert again.json() == first
    assert again.json()["duplicate"] is False and again.json()["audit_id"]
    assert _counts(db_session) == counts
