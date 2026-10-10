"""The audit list and undo (T-08-3b part 2; ux spec A1/A2, sec T-08-3 criteria).

GET /audit and POST /audit/{id}/undo are web-session only: an MCP token
(any scope) gets 401, so an injected assistant can't read the trail or undo
the user's own fixes. The list is the caller's writes only, newest first,
50 per page with a validated cursor. The client is named from the grant
stored on the row, cleaned of hidden characters, and still shown after the
grant is revoked. Undo restores the before-state, refuses (409) when the
target changed since or is gone, records its own row, and never deletes.
"""
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.core import user_crypto
from app.core.oauth_tokens import Caller
from app.main import app
from app.models import AuditEntry, CommitmentRule, OAuthClient, OAuthGrant, PlannedItem, User
from app.services.planning_writes import WriteRequest, run_write
from tests.integration.test_oauth import READ, _bearer, _connect
from tests.integration.test_transactions_endpoint import _dek_from_token

API = "/api/v1"
PLANNING = "finance:planning.write"


class World:
    """A web-logged-in user with an MCP connection, and helpers that make
    Claude writes under that user's DEK."""

    def __init__(self, client, db, email="audit@example.com"):
        self.client, self.db = client, db
        self.web, self.client_id, tokens = _connect(client, scopes=(READ, PLANNING), email=email)
        self.mcp = tokens["access_token"]
        self.dek = _dek_from_token(self.web)
        self.user = db.query(User).filter(User.email == email).one()
        self.grant = db.query(OAuthGrant).filter(OAuthGrant.user_id == self.user.id).one()
        self.n = 0

    def _as_user(self, fn):
        token = user_crypto.current_dek.set(self.dek)
        try:
            return fn()
        finally:
            user_crypto.current_dek.reset(token)

    def write(self, req: WriteRequest, *, via_grant=True) -> dict:
        self.n += 1
        caller = Caller(self.user, self.grant.id, self.client_id) if via_grant else Caller(self.user)
        return self._as_user(lambda: run_write(self.db, caller, req, dry_run=False, idempotency_key=f"key-{self.n:04d}"))

    def commitment(self, label="Gym", amount="30.00") -> uuid.UUID:
        def make():
            rule = CommitmentRule(
                user_id=self.user.id, direction="expense", label=label, amount=Decimal(amount),
                cadence="monthly", next_date=date(2026, 11, 1), source="manual", status="confirmed",
            )
            self.db.add(rule)
            self.db.commit()
            return rule.id
        return self._as_user(make)

    def set_amount(self, cid, amount) -> dict:
        def apply(db, rule):
            rule.amount = Decimal(amount)
            return rule
        return self.write(WriteRequest("update_commitment", "commitment", cid, {"amount": amount}, apply))

    def add_planned(self, name="Holiday", amount="250.00") -> dict:
        def apply(db, _):
            item = PlannedItem(user_id=self.user.id, name=name, direction="expense", kind="one_off",
                               start_date=date(2026, 12, 1), amount=Decimal(amount))
            db.add(item)
            return item
        return self.write(WriteRequest("add_planned_event", "planned_event", None, {"name": name}, apply))

    def remove_planned(self, item_id) -> dict:
        def apply(db, item):
            item.active = False
            return item
        return self.write(WriteRequest("remove_planned_event", "planned_event", item_id, {}, apply))

    def get(self, model, id_):
        def load():
            self.db.expire_all()
            return self.db.get(model, id_)
        return self._as_user(load)

    def edit(self, model, id_, **values):
        def change():
            row = self.db.get(model, id_)
            for k, v in values.items():
                setattr(row, k, v)
            self.db.commit()
        self._as_user(change)

    def list(self, **params):
        return self.client.get(f"{API}/audit", params=params, headers=_bearer(self.web))

    def undo(self, audit_id, token=None):
        return self.client.post(f"{API}/audit/{audit_id}/undo", headers=_bearer(token or self.web))


def _raw_audit_count(db) -> int:
    return db.execute(text("SELECT count(*) FROM audit_entries")).scalar()


# --- access -------------------------------------------------------------------------


def test_an_mcp_token_cannot_read_the_trail_or_undo(client, db_session):
    w = World(client, db_session)
    cid = w.commitment()
    audit_id = w.set_amount(cid, "45.00")["audit_id"]
    assert client.get(f"{API}/audit", headers=_bearer(w.mcp)).status_code == 401
    assert w.undo(audit_id, token=w.mcp).status_code == 401
    assert w.get(CommitmentRule, cid).amount == Decimal("45.00")
    assert _raw_audit_count(db_session) == 1


def test_there_is_no_route_that_edits_or_deletes_audit_rows():
    audit_routes = {
        (method, route.path)
        for route in app.routes if getattr(route, "path", "").startswith(f"{API}/audit")
        for method in getattr(route, "methods", set())
    }
    assert audit_routes == {("GET", f"{API}/audit"), ("POST", f"{API}/audit/{{audit_id}}/undo")}


# --- list ---------------------------------------------------------------------------


def test_the_list_shows_the_callers_writes_newest_first_decrypted(client, db_session):
    w = World(client, db_session)
    cid = w.commitment()
    first = w.set_amount(cid, "45.00")
    second = w.add_planned("Dentist", "80.00")

    res = w.list()
    assert res.status_code == 200, res.text
    items = res.json()["items"]
    assert [i["id"] for i in items] == [second["audit_id"], first["audit_id"]]
    row = items[1]
    assert row["tool"] == "update_commitment" and row["target_kind"] == "commitment"
    assert row["target_label"] == "Gym"
    assert row["changes"] == [{"field": "amount", "before": "30.00", "after": "45.00"}]
    assert row["undone_at"] is None and row["batch_id"] is None
    assert set(row) == {
        "id", "created_at", "tool", "batch_id", "client_name", "connection_created_at",
        "target_kind", "target_id", "target_label", "changes", "undone_at",
    }


def test_another_users_rows_are_never_listed(client, db_session):
    a = World(client, db_session, "a@example.com")
    a.set_amount(a.commitment(), "45.00")
    b = World(client, db_session, "b@example.com")
    assert b.list().json()["items"] == []


def test_client_name_comes_from_the_stored_grant_and_survives_revocation(client, db_session):
    w = World(client, db_session)
    w.set_amount(w.commitment(), "45.00")
    row = w.list().json()["items"][0]
    assert row["client_name"] == "Test Client"
    assert row["connection_created_at"].startswith(w.grant.created_at.date().isoformat())

    w.grant.revoked_at = datetime.now(timezone.utc)
    db_session.commit()
    assert w.list().json()["items"][0]["client_name"] == "Test Client"


def test_a_stored_client_name_with_hidden_characters_is_cleaned(client, db_session):
    w = World(client, db_session)
    w.set_amount(w.commitment(), "45.00")
    db_session.get(OAuthClient, w.client_id).client_name = "Claude\u202e Desktop\u200b"
    db_session.commit()
    assert w.list().json()["items"][0]["client_name"] == "Claude Desktop"


def test_a_web_write_has_no_client(client, db_session):
    w = World(client, db_session)
    cid = w.commitment()
    def apply(db, rule):
        rule.amount = Decimal("1.00")
        return rule
    w.write(WriteRequest("update_commitment", "commitment", cid, {}, apply), via_grant=False)
    row = w.list().json()["items"][0]
    assert row["client_name"] is None and row["connection_created_at"] is None


def test_pages_of_50_with_a_cursor(client, db_session):
    w = World(client, db_session)
    cid = w.commitment()
    ids = [w.set_amount(cid, f"{n}.00")["audit_id"] for n in range(1, 56)]

    page1 = w.list().json()
    assert len(page1["items"]) == 50 and page1["next_cursor"]
    page2 = w.list(cursor=page1["next_cursor"]).json()
    assert len(page2["items"]) == 5 and page2["next_cursor"] is None
    seen = [i["id"] for i in page1["items"] + page2["items"]]
    assert seen == list(reversed(ids))


@pytest.mark.parametrize("limit", [0, 51, 1000])
def test_limit_is_capped_at_50(client, db_session, limit):
    w = World(client, db_session)
    assert w.list(limit=limit).status_code == 422


def test_a_cursor_must_be_one_of_the_callers_rows(client, db_session):
    a = World(client, db_session, "a@example.com")
    foreign = a.set_amount(a.commitment(), "45.00")["audit_id"]
    b = World(client, db_session, "b@example.com")
    assert b.list(cursor="not-a-uuid").status_code == 422
    assert b.list(cursor=str(uuid.uuid4())).status_code == 400
    assert b.list(cursor=foreign).status_code == 400


# --- undo ---------------------------------------------------------------------------


def test_undo_restores_the_before_state_and_records_its_own_row(client, db_session):
    w = World(client, db_session)
    cid = w.commitment()
    audit_id = w.set_amount(cid, "45.00")["audit_id"]

    res = w.undo(audit_id)
    assert res.status_code == 200, res.text
    assert res.json()["undone_at"] is not None
    assert w.get(CommitmentRule, cid).amount == Decimal("30.00")
    assert _raw_audit_count(db_session) == 2  # original kept, plus the undo row
    undo_row = w._as_user(lambda: db_session.query(AuditEntry).filter(AuditEntry.kind == "undo").one())
    assert undo_row.undoes_id == uuid.UUID(audit_id) and undo_row.grant_id is None

    # Undo rows are not listed; the original shows as undone.
    items = w.list().json()["items"]
    assert [i["id"] for i in items] == [audit_id] and items[0]["undone_at"]


def test_undoing_twice_is_a_no_op(client, db_session):
    w = World(client, db_session)
    cid = w.commitment()
    audit_id = w.set_amount(cid, "45.00")["audit_id"]
    first = w.undo(audit_id).json()
    w.edit(CommitmentRule, cid, amount=Decimal("45.00"))  # a later change the second undo must not touch
    again = w.undo(audit_id)
    assert again.status_code == 200 and again.json()["undone_at"] == first["undone_at"]
    assert w.get(CommitmentRule, cid).amount == Decimal("45.00")
    assert _raw_audit_count(db_session) == 2


def test_another_users_row_is_404(client, db_session):
    a = World(client, db_session, "a@example.com")
    cid = a.commitment()
    audit_id = a.set_amount(cid, "45.00")["audit_id"]
    b = World(client, db_session, "b@example.com")
    assert b.undo(audit_id).status_code == 404
    assert b.undo(uuid.uuid4()).status_code == 404
    assert a.get(CommitmentRule, cid).amount == Decimal("45.00")


def test_undo_refuses_when_the_changed_field_moved_since(client, db_session):
    w = World(client, db_session)
    cid = w.commitment()
    audit_id = w.set_amount(cid, "45.00")["audit_id"]
    w.edit(CommitmentRule, cid, amount=Decimal("50.00"))  # edited in the app afterwards

    res = w.undo(audit_id)
    assert res.status_code == 409 and "changed since" in res.json()["detail"]
    assert w.get(CommitmentRule, cid).amount == Decimal("50.00")
    assert _raw_audit_count(db_session) == 1
    assert w.list().json()["items"][0]["undone_at"] is None


def test_undo_ignores_fields_the_write_did_not_change(client, db_session):
    """sync_suggestions advances next_date on its own; that mustn't block undo."""
    w = World(client, db_session)
    cid = w.commitment()
    audit_id = w.set_amount(cid, "45.00")["audit_id"]
    w.edit(CommitmentRule, cid, next_date=date(2026, 12, 1))
    assert w.undo(audit_id).status_code == 200
    rule = w.get(CommitmentRule, cid)
    assert rule.amount == Decimal("30.00") and rule.next_date == date(2026, 12, 1)


def test_undo_of_an_add_soft_deletes(client, db_session):
    w = World(client, db_session)
    added = w.add_planned()
    assert w.undo(added["audit_id"]).status_code == 200
    item = w.get(PlannedItem, uuid.UUID(added["target_id"]))
    assert item is not None and item.active is False


def test_undo_of_a_remove_reactivates(client, db_session):
    w = World(client, db_session)
    item_id = uuid.UUID(w.add_planned()["target_id"])
    removed = w.remove_planned(item_id)
    assert w.get(PlannedItem, item_id).active is False
    assert w.undo(removed["audit_id"]).status_code == 200
    assert w.get(PlannedItem, item_id).active is True


def test_undo_of_a_row_whose_target_is_gone_is_409(client, db_session):
    w = World(client, db_session)
    cid = w.commitment()
    audit_id = w.set_amount(cid, "45.00")["audit_id"]
    db_session.execute(text("DELETE FROM commitment_rules"))
    db_session.commit()
    res = w.undo(audit_id)
    assert res.status_code == 409
    assert _raw_audit_count(db_session) == 1


def test_the_undo_row_is_encrypted_too(client, db_session):
    w = World(client, db_session)
    audit_id = w.set_amount(w.commitment(label="Secret Clinic"), "987.65")["audit_id"]
    w.undo(audit_id)
    raw = " ".join(str(v) for row in db_session.execute(text("SELECT * FROM audit_entries")) for v in row)
    assert "Secret Clinic" not in raw and "987.65" not in raw
