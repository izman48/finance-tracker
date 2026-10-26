"""Claude's edits to existing rules over MCP.

`POST /planning/rules/{rule_id}/update` takes a token with its own
`finance:rules.edit` scope, not `finance:rules.write`: that scope's consent
copy promises Claude "can't edit or delete your existing rules", so existing
grants must not gain this. Every edit goes through the planning-write
framework: dry_run by default, an idempotency key, an encrypted audit row
(`target_kind: "rule"`), web-only undo with 409 "changed since", and the
shared per-user write limit. Only the rule's own matching fields change
(pattern, match_type, match_field, category, counts_as, enabled); its
owner, pack and source never do. Switching a rule off is `enabled: false`,
so it stays undoable. An applied edit, and its undo, re-run the rules over
the user's history.
"""
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.core import user_crypto
from app.models import Account, AuditEntry, BankConnection, CategoryRule, Transaction, User
from tests.integration.test_oauth import READ, _bearer, _connect, _refresh
from tests.integration.test_transactions_endpoint import _dek_from_token

API = "/api/v1"
RULES_EDIT = "finance:rules.edit"
RULES_WRITE = "finance:rules.write"


class World:
    """A user with a few transactions, one rule, and a Claude grant."""

    def __init__(self, client, db, email="claude-rules@example.com", scopes=(READ, RULES_EDIT)):
        self.client, self.db = client, db
        self.web, _, tokens = _connect(client, scopes=scopes, email=email)
        self.mcp = tokens["access_token"]
        self.user = db.query(User).filter(User.email == email).one()

    def as_user(self, fn):
        ctx = user_crypto.current_dek.set(_dek_from_token(self.web))
        try:
            return fn()
        finally:
            user_crypto.current_dek.reset(ctx)

    def transactions(self, rows):
        def make():
            conn = BankConnection(user_id=self.user.id, provider_id="ob-rules", provider_name="Test Bank",
                                  access_token="t", refresh_token="r")
            self.db.add(conn)
            self.db.flush()
            acc = Account(user_id=self.user.id, bank_connection_id=conn.id, external_id=f"ext-{uuid.uuid4().hex}",
                          provider_name="Test Bank", account_type="TRANSACTION", display_name="Cur",
                          current_balance=Decimal("0"))
            self.db.add(acc)
            self.db.flush()
            for i, (desc, amount) in enumerate(rows):
                self.db.add(Transaction(
                    account_id=acc.id, external_id=f"tx-{i}-{uuid.uuid4().hex}", transaction_type="debit",
                    amount=Decimal(str(amount)), currency="GBP", description=desc, merchant_name=desc,
                    transaction_date=datetime(2026, 7, 10, tzinfo=timezone.utc),
                ))
            self.db.commit()
        self.as_user(make)

    def rule(self, **body):
        r = self.client.post(f"{API}/rules", json=body, headers=_bearer(self.web))
        assert r.status_code == 201, r.text
        assert self.client.post(f"{API}/rules/apply", headers=_bearer(self.web)).status_code == 200
        return r.json()["id"]

    def update(self, rule_id, token=None, **body):
        body.setdefault("idempotency_key", f"k-{uuid.uuid4().hex[:12]}")
        return self.client.post(f"{API}/planning/rules/{rule_id}/update", json=body,
                                headers=_bearer(token or self.mcp))

    def listed(self, rule_id):
        listed = self.client.get(f"{API}/rules", headers=_bearer(self.web)).json()
        rules = listed["personal"] + [r for p in listed["packs"] for r in p["rules"]]
        return next(r for r in rules if r["id"] == rule_id)

    def categories(self):
        def read():
            self.db.expire_all()
            rows = self.db.query(Transaction).join(Account).filter(Account.user_id == self.user.id).all()
            return {t.description: t.category for t in rows}
        return self.as_user(read)

    def count(self, model):
        return self.db.execute(select(func.count()).select_from(model)).scalar()

    def undo(self, audit_id):
        return self.client.post(f"{API}/audit/{audit_id}/undo", headers=_bearer(self.web))


@pytest.fixture
def w(client, db_session):
    world = World(client, db_session)
    world.transactions([("TESCO PFS 3402", 40), ("TESCO STORE 6593", 12)])
    return world


# --- scope ------------------------------------------------------------------------------

def test_a_rules_write_token_cant_edit_rules(client, db_session):
    """rules.write consent says Claude can't edit existing rules: keep that promise."""
    w = World(client, db_session, email="writer-only@example.com", scopes=(READ, RULES_WRITE))
    rule_id = w.rule(pattern="TESCO", category="Groceries")
    r = w.update(rule_id, category="Transport", dry_run=False)
    assert r.status_code == 403
    assert RULES_EDIT in r.headers["WWW-Authenticate"]
    assert w.listed(rule_id)["category"] == "Groceries"


def test_the_scope_is_offered(client):
    meta = client.get("/.well-known/oauth-authorization-server").json()
    assert RULES_EDIT in meta["scopes_supported"]


def test_an_existing_grant_cannot_gain_the_scope_on_refresh(client):
    _, client_id, tokens = _connect(client, scopes=(READ, RULES_WRITE), email="old-grant@example.com")
    widened = _refresh(client, tokens["refresh_token"], client_id, scope=f"{READ} {RULES_EDIT}")
    assert widened.status_code == 400 and widened.json()["error"] == "invalid_scope"
    kept = _refresh(client, tokens["refresh_token"], client_id)
    assert kept.status_code == 200, kept.text
    assert RULES_EDIT not in kept.json()["scope"].split()


def test_the_scope_opens_no_other_write(client):
    """rules.edit edits rules; it can't create packs or touch planning."""
    _, _, tokens = _connect(client, scopes=(READ, RULES_EDIT), email="edit-only@example.com")
    bulk = client.post(f"{API}/rules/packs/bulk", json={"name": "x", "rules": [{"pattern": "A", "category": "B"}]},
                       headers=_bearer(tokens["access_token"]))
    assert bulk.status_code == 403
    planning = client.post(f"{API}/planning/planned-events", json={"dry_run": True, "idempotency_key": "probe-rules-1"},
                           headers=_bearer(tokens["access_token"]))
    assert planning.status_code == 403


# --- preview and apply ---------------------------------------------------------------------

def test_update_previews_by_default_and_writes_nothing(w):
    rule_id = w.rule(pattern="TESCO", category="Groceries")
    r = w.update(rule_id, category="Shopping")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["dry_run"] is True
    assert body["target_kind"] == "rule"
    assert {"field": "category", "before": "Groceries", "after": "Shopping"} in body["changes"]
    assert w.listed(rule_id)["category"] == "Groceries"
    assert w.count(AuditEntry) == 0


def test_update_applies_audits_and_recategorises_history(w):
    rule_id = w.rule(pattern="TESCO", category="Groceries")
    r = w.update(rule_id, pattern="TESCO PFS", category="Transport", dry_run=False)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["dry_run"] is False and body["audit_id"]
    assert body["transactions_recategorized"] == 1
    rule = w.listed(rule_id)
    assert (rule["pattern"], rule["category"]) == ("TESCO PFS", "Transport")
    assert w.categories()["TESCO PFS 3402"] == "Transport"
    [(kind, tool, target_id)] = w.db.query(AuditEntry.target_kind, AuditEntry.tool, AuditEntry.target_id).all()
    assert (kind, tool, str(target_id)) == ("rule", "update_rule", rule_id)


def test_switching_a_rule_off_is_a_soft_change(w):
    rule_id = w.rule(pattern="TESCO", category="Groceries")
    r = w.update(rule_id, enabled=False, dry_run=False)
    assert r.status_code == 200, r.text
    assert {"field": "enabled", "before": True, "after": False} in r.json()["changes"]
    assert w.listed(rule_id)["enabled"] is False
    assert w.count(CategoryRule) == 1  # still there, so undo can bring it back


def test_counts_as_can_be_set_and_cleared(w):
    rule_id = w.rule(pattern="TESCO", category="Groceries")
    assert w.update(rule_id, counts_as="transfer", dry_run=False).status_code == 200
    assert w.listed(rule_id)["counts_as"] == "transfer"
    r = w.update(rule_id, counts_as=None, dry_run=False)
    assert r.status_code == 200, r.text
    assert w.listed(rule_id)["counts_as"] is None


def test_an_edit_that_changes_nothing_is_unchanged(w):
    rule_id = w.rule(pattern="TESCO", category="Groceries")
    r = w.update(rule_id, category="Groceries", dry_run=False)
    assert r.status_code == 200, r.text
    assert r.json()["unchanged"] is True
    assert w.count(AuditEntry) == 0


def test_a_retry_with_the_same_key_replays(w):
    rule_id = w.rule(pattern="TESCO", category="Groceries")
    first = w.update(rule_id, category="Shopping", idempotency_key="same-key-123", dry_run=False)
    again = w.update(rule_id, category="Shopping", idempotency_key="same-key-123", dry_run=False)
    assert first.status_code == again.status_code == 200
    assert again.json()["audit_id"] == first.json()["audit_id"]
    assert w.count(AuditEntry) == 1


# --- refusals -------------------------------------------------------------------------------

def test_a_bad_regex_is_refused_and_nothing_changes(w):
    rule_id = w.rule(pattern="TESCO", category="Groceries")
    r = w.update(rule_id, pattern="(a)\\1", match_type="regex", dry_run=False)
    assert r.status_code == 400
    assert w.listed(rule_id)["match_type"] == "contains"
    assert w.count(AuditEntry) == 0


def test_a_new_match_type_is_checked_against_the_stored_pattern(w):
    rule_id = w.rule(pattern="(a)\\1", category="Groceries", match_type="contains")
    r = w.update(rule_id, match_type="regex", dry_run=False)
    assert r.status_code == 400
    assert w.listed(rule_id)["match_type"] == "contains"


@pytest.mark.parametrize("field,value", [
    ("source", "learned"), ("user_id", "00000000-0000-0000-0000-000000000000"),
    ("pack_id", "00000000-0000-0000-0000-000000000000"),
])
def test_fields_outside_the_allow_list_are_refused(w, field, value):
    rule_id = w.rule(pattern="TESCO", category="Groceries")
    r = w.update(rule_id, dry_run=False, **{field: value})
    assert r.status_code == 422
    assert w.count(AuditEntry) == 0


def test_another_users_rule_is_not_found(client, db_session, w):
    other = World(client, db_session, email="someone-else@example.com")
    theirs = other.rule(pattern="TESCO", category="Groceries")
    r = w.update(theirs, category="Shopping", dry_run=False)
    assert r.status_code == 404
    assert other.listed(theirs)["category"] == "Groceries"


def test_an_unknown_rule_is_not_found(w):
    assert w.update(str(uuid.uuid4()), category="Shopping", dry_run=False).status_code == 404


# --- undo -----------------------------------------------------------------------------------

def test_undo_restores_the_rule_and_reapplies_it(w):
    rule_id = w.rule(pattern="TESCO", category="Groceries")
    audit_id = w.update(rule_id, category="Shopping", dry_run=False).json()["audit_id"]
    assert w.categories()["TESCO STORE 6593"] == "Shopping"
    r = w.undo(audit_id)
    assert r.status_code == 200, r.text
    assert w.listed(rule_id)["category"] == "Groceries"
    assert w.categories()["TESCO STORE 6593"] == "Groceries"


def test_undo_refuses_when_the_rule_changed_since(w):
    rule_id = w.rule(pattern="TESCO", category="Groceries")
    audit_id = w.update(rule_id, category="Shopping", dry_run=False).json()["audit_id"]
    w.client.patch(f"{API}/rules/{rule_id}", json={"category": "Eating out"}, headers=_bearer(w.web))
    assert w.undo(audit_id).status_code == 409
    assert w.listed(rule_id)["category"] == "Eating out"
