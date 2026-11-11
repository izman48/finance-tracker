"""Claude's paid-back writes (T-03-3 P5; PRD "MCP contract", ACs 18-23; T-03-2
decisions T1, T2, T11).

Every route under /planning/repayments needs the new `finance:repayments.write`
scope (or a web session). No other write scope implies it, so existing grants
never gain it (T1). Writes go through the Sprint 08 framework: dry_run by
default, an idempotency key, an encrypted audit row per mark
(`target_kind: "repayment_mark"`), web-only undo. Claude may unmark only marks
it made (`created_via == "mcp"`); any other id, another user's included, is a
404 that never says whose.
"""
import uuid

import pytest
from sqlalchemy import func, select

from app.models import AuditEntry, RepaymentMark, User
from tests.integration.test_oauth import READ, _bearer, _connect
from tests.integration.test_repayment_marks import Ledger
from tests.integration.test_transactions_endpoint import _dek_from_token

API = "/api/v1/planning/repayments"
REPAYMENTS = "finance:repayments.write"
OTHER_WRITES = ("finance:rules.write", "finance:planning.write", "finance:sync", "finance:budgets.write",
                "finance:rules.edit")


class World:
    """A user with an MCP connection holding `scopes`, a £200 dinner and Sam's £60."""

    def __init__(self, client, db, email="repay@example.com", scopes=(READ, REPAYMENTS)):
        self.client, self.db = client, db
        self.web, _, tokens = _connect(client, scopes=scopes, email=email)
        self.mcp = tokens["access_token"]
        self.user = db.query(User).filter(User.email == email).one()
        self.ledger = Ledger(db, self.user.id, _dek_from_token(self.web))
        self.dinner, self.sam = self.ledger.spend("200.00"), self.ledger.credit("60.00")

    def mark(self, created_via="mcp", active=True) -> uuid.UUID:
        row = self.ledger.mark(self.sam, "60.00", spend=self.dinner, active=active)
        if created_via != "mcp":
            self.ledger.as_user(lambda: (setattr(row, "created_via", created_via), self.db.commit()))
        return self.ledger.as_user(lambda: row.id)

    def unmark(self, mark_id, token=None, **body):
        body.setdefault("idempotency_key", f"k-{uuid.uuid4().hex[:12]}")
        return self.client.post(f"{API}/{mark_id}/unmark", json=body, headers=_bearer(token or self.mcp))

    def active(self, mark_id) -> bool:
        self.db.expire_all()
        return self.ledger.as_user(lambda: self.db.get(RepaymentMark, mark_id).active)

    def audit_rows(self) -> int:
        return self.db.execute(select(func.count()).select_from(AuditEntry)).scalar()


@pytest.fixture
def w(client, db_session):
    return World(client, db_session)


# --- scope (T1, AC-21) ------------------------------------------------------------------


def test_every_other_write_scope_is_refused(client, db_session):
    w = World(client, db_session, scopes=(READ, *OTHER_WRITES))
    mark_id = w.mark()
    r = w.unmark(mark_id, dry_run=False)
    assert r.status_code == 403 and REPAYMENTS in r.headers["WWW-Authenticate"]
    assert w.active(mark_id) is True and w.audit_rows() == 0


def test_the_scope_is_offered_and_granted_only_when_asked_for(client, db_session):
    meta = client.get("/.well-known/oauth-authorization-server").json()
    assert REPAYMENTS in meta["scopes_supported"]
    _, _, tokens = _connect(client, scopes=(READ, REPAYMENTS), email="granted@example.com")
    assert tokens["scope"].split() == [READ, REPAYMENTS]


# --- unmark (AC-23, T2, T11) -----------------------------------------------------------


def test_unmark_is_a_dry_run_by_default(w):
    mark_id = w.mark()
    r = w.unmark(mark_id)
    assert r.status_code == 200, r.text
    assert r.json()["dry_run"] is True and {"field": "active", "before": True, "after": False} in r.json()["changes"]
    assert w.active(mark_id) is True and w.audit_rows() == 0


def test_unmark_soft_deletes_with_one_audit_row_and_a_retry_replays(w):
    mark_id = w.mark()
    r = w.unmark(mark_id, dry_run=False, idempotency_key="unmark-key-1")
    assert r.status_code == 200, r.text
    assert r.json()["audit_id"] and r.json()["target_kind"] == "repayment_mark"
    assert w.active(mark_id) is False

    again = w.unmark(mark_id, dry_run=False, idempotency_key="unmark-key-1")
    assert again.status_code == 200 and again.json()["audit_id"] == r.json()["audit_id"]
    assert w.audit_rows() == 1


@pytest.mark.parametrize("which", ["unknown", "made_in_the_app", "already_unmarked", "another_users"])
def test_unmark_of_anything_but_an_active_claude_mark_is_not_found(client, db_session, which):
    w = World(client, db_session)
    if which == "unknown":
        mark_id = uuid.uuid4()
    elif which == "made_in_the_app":
        mark_id = w.mark(created_via="web")
    elif which == "already_unmarked":
        mark_id = w.mark(active=False)
    else:
        mark_id = World(client, db_session, email="other@example.com").mark()

    r = w.unmark(mark_id, dry_run=False)

    assert r.status_code == 404 and r.json()["detail"] == "Not found"
    assert w.audit_rows() == 0


def test_undoing_an_unmark_made_through_the_route_puts_the_mark_back(w):
    mark_id = w.mark()
    audit_id = w.unmark(mark_id, dry_run=False).json()["audit_id"]

    r = w.client.post(f"/api/v1/audit/{audit_id}/undo", headers=_bearer(w.web))

    assert r.status_code == 200, r.text
    assert w.active(mark_id) is True


def test_an_unmark_records_what_it_removed_for_the_changes_page(w):
    r = w.unmark(w.mark(), dry_run=False)
    changes = {c["field"]: (c["before"], c["after"]) for c in r.json()["changes"]}
    assert changes["active"] == (True, False)
    assert changes["amount"] == ("60.00", "60.00") and changes["category"] == (None, None)
