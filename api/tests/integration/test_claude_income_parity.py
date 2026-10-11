"""Claude can't raise savable on its own (T-08-20, owner decision D4 = strict parity).

When Claude raises an income commitment, confirms a suggested income, or
changes when or how often it arrives, `savable` keeps using the pre-Claude
version until the user keeps the change: POST /audit/{id}/keep, web session
only (ux spec section 9, A8). A hand edit is not keeping, but a hand edit
of the field Claude changed replaces Claude's value with the user's (KP14).
A change that brings in less counts at once. Undo works as normal.
Safe-to-spend never counts income; the forecast may move (D1 = a).
"""
import uuid
from datetime import date, timedelta
from decimal import Decimal

from app.core import user_crypto
from app.models import CommitmentRule, User
from tests.integration.test_oauth import READ, _bearer, _connect
from tests.integration.test_transactions_endpoint import _account, _dek_from_token

API = "/api/v1"
PLANNING = "finance:planning.write"
TODAY = date.today()


class World:
    def __init__(self, client, db, email="parity@example.com"):
        self.client, self.db = client, db
        self.web, _, tokens = _connect(client, scopes=(READ, PLANNING), email=email)
        self.mcp = tokens["access_token"]
        self.dek = _dek_from_token(self.web)
        self.user = db.query(User).filter(User.email == email).one()
        self.as_user(lambda: _account(db, self.user.id, name="Current", balance="500.00"))
        self.n = 0

    def as_user(self, fn):
        token = user_crypto.current_dek.set(self.dek)
        try:
            return fn()
        finally:
            user_crypto.current_dek.reset(token)

    def income(self, amount="1000.00", status="confirmed", direction="income") -> uuid.UUID:
        def make():
            rule = CommitmentRule(
                user_id=self.user.id, direction=direction, label="Income A", amount=Decimal(amount),
                cadence="monthly", next_date=TODAY + timedelta(days=10), source="manual", status=status,
            )
            self.db.add(rule)
            self.db.commit()
            return rule.id
        return self.as_user(make)

    def claude_update(self, cid, **fields) -> str:
        self.n += 1
        res = self.client.post(
            f"{API}/planning/commitments/{cid}/update",
            json={**fields, "dry_run": False, "idempotency_key": f"parity-key-{self.n:04d}"},
            headers=_bearer(self.mcp),
        )
        assert res.status_code == 200, res.text
        return res.json()["audit_id"]

    def keep(self, audit_id, token=None):
        return self.client.post(f"{API}/audit/{audit_id}/keep", headers=_bearer(token or self.web))

    def summary(self):
        return self.client.get(f"{API}/analytics/summary", headers=_bearer(self.web)).json()

    def savable(self) -> Decimal:
        return Decimal(self.summary()["savable"])

    def commitment(self, cid):
        rows = self.client.get(f"{API}/analytics/commitments", headers=_bearer(self.web)).json()
        return next(c for c in rows if c["id"] == str(cid))

    def audit_row(self, audit_id):
        items = self.client.get(f"{API}/audit", headers=_bearer(self.web)).json()["items"]
        return next(i for i in items if i["id"] == audit_id)


def test_a_claude_raise_does_not_raise_savable_until_kept(client, db_session):
    w = World(client, db_session)
    cid = w.income("1000.00")
    assert w.savable() == Decimal("1500.00")

    audit_id = w.claude_update(cid, amount="1500.00")
    summary = w.summary()
    assert Decimal(summary["savable"]) == Decimal("1500.00")  # still the pre-Claude 1,000
    assert Decimal(summary["savable_pending_keep_total"]) == Decimal("500.00")
    assert w.commitment(cid)["keep"] == "pending" and w.audit_row(audit_id)["keep"] == "pending"

    res = w.keep(audit_id)
    assert res.status_code == 200, res.text
    assert res.json()["keep"] == "kept" and res.json()["kept_at"]
    assert w.savable() == Decimal("2000.00")
    assert Decimal(w.summary()["savable_pending_keep_total"]) == Decimal("0")
    row = w.commitment(cid)
    assert row["keep"] == "kept" and row["kept_at"]


def test_keep_is_idempotent(client, db_session):
    w = World(client, db_session)
    audit_id = w.claude_update(w.income("1000.00"), amount="1500.00")
    first = w.keep(audit_id).json()
    again = w.keep(audit_id)
    assert again.status_code == 200 and again.json()["kept_at"] == first["kept_at"]


def test_a_claude_confirmed_suggestion_counts_nothing_until_kept(client, db_session):
    w = World(client, db_session)
    cid = w.income("1000.00", status="suggested")
    assert w.savable() == Decimal("500.00")
    audit_id = w.claude_update(cid, status="confirmed")
    assert w.savable() == Decimal("500.00")
    w.keep(audit_id)
    assert w.savable() == Decimal("1500.00")


def test_a_claude_cadence_change_that_brings_in_more_waits_too(client, db_session):
    w = World(client, db_session)
    cid = w.income("1000.00")
    w.claude_update(cid, cadence="custom_days", interval_days=7)  # weekly: ~4x in 30 days
    assert w.savable() == Decimal("1500.00")
    assert w.commitment(cid)["keep"] == "pending"


def test_a_claude_cut_counts_at_once_and_needs_no_keep(client, db_session):
    w = World(client, db_session)
    cid = w.income("1000.00")
    audit_id = w.claude_update(cid, amount="600.00")
    assert w.savable() == Decimal("1100.00")
    assert w.commitment(cid)["keep"] is None and w.audit_row(audit_id)["keep"] is None


def test_a_hand_edit_of_another_field_is_not_keeping(client, db_session):
    """KP14: editing only the name leaves Claude's raise pending."""
    w = World(client, db_session)
    cid = w.income("1000.00")
    w.claude_update(cid, amount="1500.00")
    res = client.patch(f"{API}/analytics/commitments/{cid}", json={"label": "Income A (salary)"},
                       headers=_bearer(w.web))
    assert res.status_code == 200, res.text
    assert w.savable() == Decimal("1500.00")
    assert w.commitment(cid)["keep"] == "pending"


def test_a_hand_edit_of_the_amount_makes_it_the_users_figure(client, db_session):
    """KP14: the user's own GBP 1,800 counts; nothing left to keep."""
    w = World(client, db_session)
    cid = w.income("1000.00")
    audit_id = w.claude_update(cid, amount="1500.00")
    client.patch(f"{API}/analytics/commitments/{cid}", json={"amount": "1800.00"}, headers=_bearer(w.web))
    assert w.savable() == Decimal("2300.00")
    assert w.commitment(cid)["keep"] is None
    assert w.keep(audit_id).status_code == 409  # nothing of Claude's left in effect


def test_a_hand_edit_of_one_of_two_claude_fields_stays_pending(client, db_session):
    """KP14: Claude changed amount and cadence; the user edits only the amount."""
    w = World(client, db_session)
    cid = w.income("1000.00")
    w.claude_update(cid, amount="1500.00", cadence="custom_days", interval_days=7)
    client.patch(f"{API}/analytics/commitments/{cid}", json={"amount": "1800.00"}, headers=_bearer(w.web))
    assert w.commitment(cid)["keep"] == "pending"


def test_undo_of_a_pending_raise_ends_it(client, db_session):
    w = World(client, db_session)
    cid = w.income("1000.00")
    audit_id = w.claude_update(cid, amount="1500.00")
    assert client.post(f"{API}/audit/{audit_id}/undo", headers=_bearer(w.web)).status_code == 200
    assert w.savable() == Decimal("1500.00")
    assert w.commitment(cid)["keep"] is None


def test_undo_of_a_kept_raise_restores_the_before_state(client, db_session):
    w = World(client, db_session)
    cid = w.income("1000.00")
    audit_id = w.claude_update(cid, amount="1500.00")
    w.keep(audit_id)
    assert client.post(f"{API}/audit/{audit_id}/undo", headers=_bearer(w.web)).status_code == 200
    assert w.savable() == Decimal("1500.00")
    assert w.commitment(cid)["keep"] is None


def test_a_kept_change_stays_kept_and_a_new_one_waits(client, db_session):
    w = World(client, db_session)
    cid = w.income("1000.00")
    w.keep(w.claude_update(cid, amount="1500.00"))
    w.claude_update(cid, amount="2500.00")
    assert w.savable() == Decimal("2000.00")  # the kept 1,500, not the new 2,500
    assert w.commitment(cid)["keep"] == "pending"


def test_safe_to_spend_is_unaffected(client, db_session):
    w = World(client, db_session)
    cid = w.income("1000.00")
    before = w.summary()["safe_to_spend"]
    w.claude_update(cid, amount="1500.00")
    assert w.summary()["safe_to_spend"] == before


def test_expenses_are_out_of_scope(client, db_session):
    w = World(client, db_session)
    cid = w.income("100.00", direction="expense")
    audit_id = w.claude_update(cid, amount="150.00")
    assert w.commitment(cid)["keep"] is None and w.audit_row(audit_id)["keep"] is None
    assert w.keep(audit_id).status_code == 409


def test_an_mcp_token_cannot_keep(client, db_session):
    w = World(client, db_session)
    audit_id = w.claude_update(w.income("1000.00"), amount="1500.00")
    assert w.keep(audit_id, token=w.mcp).status_code == 401
    assert w.savable() == Decimal("1500.00")


def test_keep_is_scoped_to_the_callers_rows(client, db_session):
    a = World(client, db_session, "a@example.com")
    audit_id = a.claude_update(a.income("1000.00"), amount="1500.00")
    b = World(client, db_session, "b@example.com")
    assert b.keep(audit_id).status_code == 404
    assert b.keep(uuid.uuid4()).status_code == 404
    assert a.savable() == Decimal("1500.00")
