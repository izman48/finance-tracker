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

    def hand_set(self, description, category):
        """The user re-categorises one transaction on the web (locks it)."""
        tx_id = self.as_user(lambda: next(
            t.id for t in self.db.query(Transaction).join(Account).filter(Account.user_id == self.user.id)
            if t.description == description))
        r = self.client.patch(f"{API}/banking/transactions/{tx_id}", json={"category": category},
                              headers=_bearer(self.web))
        assert r.status_code == 200, r.text

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
    assert again.json()["transactions_recategorized"] == first.json()["transactions_recategorized"] == 2
    assert w.count(AuditEntry) == 1


def test_the_preview_counts_what_apply_will_recategorise_and_changes_nothing(w):
    """sec B2: the user confirms on this number, so it is the real one, never a placeholder 0."""
    w.transactions([("AMAZON MKTPLACE", 20), ("NETFLIX", 11)])
    rule_id = w.rule(pattern="TESCO", category="Groceries")
    before = w.categories()
    preview = w.update(rule_id, pattern=".*", match_type="regex", category="Everything")
    assert preview.status_code == 200, preview.text
    assert preview.json()["transactions_recategorized"] == 4
    assert "side_effects" not in preview.json()
    assert w.categories() == before
    applied = w.update(rule_id, pattern=".*", match_type="regex", category="Everything", dry_run=False)
    assert applied.json()["transactions_recategorized"] == 4


def test_a_failed_backfill_leaves_no_edit_and_no_audit(w, monkeypatch):
    """The edit, its audit row and its recategorisation are one transaction."""
    from app.services import categorization
    rule_id = w.rule(pattern="TESCO", category="Groceries")

    def boom(*args, **kwargs):
        raise RuntimeError("backfill failed")
    monkeypatch.setattr(categorization, "apply_rules", boom)
    with pytest.raises(RuntimeError):
        w.update(rule_id, category="Shopping", idempotency_key="fails-once-1", dry_run=False)
    monkeypatch.undo()
    assert w.listed(rule_id)["category"] == "Groceries"
    assert w.count(AuditEntry) == 0
    retry = w.update(rule_id, category="Shopping", idempotency_key="fails-once-1", dry_run=False)
    assert retry.status_code == 200, retry.text
    assert retry.json()["transactions_recategorized"] == 2


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


@pytest.mark.parametrize("dry_run", [True, False])
@pytest.mark.parametrize("field,value", [
    ("pattern", None), ("category", None), ("match_type", None), ("match_field", None), ("enabled", None),
    ("pattern", "   "), ("category", "   "),
])
def test_a_null_or_blank_required_field_is_refused(w, field, value, dry_run):
    """Only counts_as can be cleared; anything else null or blank is a 422, not a 500."""
    rule_id = w.rule(pattern="TESCO", category="Groceries")
    before = w.listed(rule_id)
    r = w.update(rule_id, dry_run=dry_run, **{field: value})
    assert r.status_code == 422, r.text
    assert w.listed(rule_id) == before
    assert w.count(AuditEntry) == 0


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


def test_undo_of_a_match_all_edit_restores_every_category(w):
    """sec B1: undo puts back what the edit's backfill changed, including categories no rule set."""
    w.transactions([("AMAZON MKTPLACE", 20), ("NETFLIX", 11)])
    rule_id = w.rule(pattern="TESCO", category="Groceries")
    before = w.categories()
    assert before["NETFLIX"] is None
    audit_id = w.update(rule_id, pattern=".*", match_type="regex", category="Hacked", dry_run=False).json()["audit_id"]
    assert set(w.categories().values()) == {"Hacked"}
    assert w.undo(audit_id).status_code == 200
    assert w.categories() == before
    assert w.listed(rule_id)["pattern"] == "TESCO"


def test_undo_of_a_switch_off_restores_history(w):
    w.rule(pattern="TESCO", category="Groceries")
    store = w.rule(pattern="TESCO STORE", category="Household")
    assert w.categories()["TESCO STORE 6593"] == "Household"
    r = w.update(store, enabled=False, dry_run=False)
    assert r.json()["transactions_recategorized"] == 1
    assert w.categories()["TESCO STORE 6593"] == "Groceries"
    assert w.undo(r.json()["audit_id"]).status_code == 200
    assert w.listed(store)["enabled"] is True
    assert w.categories()["TESCO STORE 6593"] == "Household"


def test_hand_set_categories_survive_the_edit_and_its_undo(w):
    """The consent copy promises Claude never changes categories you set by hand."""
    w.transactions([("AMAZON MKTPLACE", 20), ("NETFLIX", 11)])
    rule_id = w.rule(pattern="TESCO", category="Groceries")
    w.hand_set("NETFLIX", "Subscriptions")
    audit_id = w.update(rule_id, pattern=".*", match_type="regex", category="Hacked", dry_run=False).json()["audit_id"]
    assert w.categories()["NETFLIX"] == "Subscriptions"
    w.hand_set("AMAZON MKTPLACE", "Gifts")  # after the edit: undo must not take it back
    assert w.undo(audit_id).status_code == 200
    after = w.categories()
    assert (after["NETFLIX"], after["AMAZON MKTPLACE"]) == ("Subscriptions", "Gifts")
    assert after["TESCO PFS 3402"] == "Groceries"


def test_undo_leaves_a_category_that_changed_since(w):
    """Unlocked but no longer what the edit set (another change since): not overwritten."""
    w.transactions([("NETFLIX", 11)])
    rule_id = w.rule(pattern="TESCO", category="Groceries")
    audit_id = w.update(rule_id, pattern=".*", match_type="regex", category="Hacked", dry_run=False).json()["audit_id"]

    def change_since():
        tx = next(t for t in w.db.query(Transaction).join(Account).filter(Account.user_id == w.user.id)
                  if t.description == "NETFLIX")
        tx.category = "Streaming"
        w.db.commit()
    w.as_user(change_since)
    assert w.undo(audit_id).status_code == 200
    assert w.categories()["NETFLIX"] == "Streaming"


# --- pattern and match_type go together (T-16-1) --------------------------------------------
# A pattern means nothing without the match type it runs under, so an edit to
# either records the other as context (before == after): undo then refuses if
# either changed since, and the Changes page shows the pair.

def _web_edit(w, rule_id, **body):
    r = w.client.patch(f"{API}/rules/{rule_id}", json=body, headers=_bearer(w.web))
    assert r.status_code == 200, r.text


def test_a_pattern_edit_records_the_match_type_as_context(w):
    rule_id = w.rule(pattern="TESCO", category="Groceries")
    for dry_run in (True, False):
        changes = w.update(rule_id, pattern="TESCO PFS", dry_run=dry_run).json()["changes"]
        assert {"field": "match_type", "before": "contains", "after": "contains"} in changes
        assert {"field": "pattern", "before": "TESCO", "after": "TESCO PFS"} in changes


def test_a_match_type_edit_records_the_pattern_as_context(w):
    rule_id = w.rule(pattern="TESCO", category="Groceries")
    changes = w.update(rule_id, match_type="regex", dry_run=False).json()["changes"]
    assert {"field": "pattern", "before": "TESCO", "after": "TESCO"} in changes


def test_an_edit_to_neither_records_no_context(w):
    rule_id = w.rule(pattern="TESCO", category="Groceries")
    changes = w.update(rule_id, pattern="TESCO", category="Shopping", dry_run=False).json()["changes"]
    assert changes == [{"field": "category", "before": "Groceries", "after": "Shopping"}]


def test_re_sending_the_same_pattern_is_still_unchanged(w):
    """sec: the context lines alone are not a change, so no audit row."""
    rule_id = w.rule(pattern="TESCO", category="Groceries")
    r = w.update(rule_id, pattern="TESCO", match_type="contains", dry_run=False)
    assert r.status_code == 200, r.text
    assert r.json()["unchanged"] is True
    assert w.count(AuditEntry) == 0


def test_undo_of_a_pattern_edit_refuses_when_the_match_type_changed_since(w):
    rule_id = w.rule(pattern="TESCO", category="Groceries")
    audit_id = w.update(rule_id, pattern="TESCO PFS", dry_run=False).json()["audit_id"]
    _web_edit(w, rule_id, match_type="regex")
    r = w.undo(audit_id)
    assert r.status_code == 409
    assert "changed since" in r.json()["detail"]
    rule = w.listed(rule_id)
    assert (rule["pattern"], rule["match_type"]) == ("TESCO PFS", "regex")


def test_undo_of_a_match_type_edit_refuses_when_the_pattern_changed_since(w):
    rule_id = w.rule(pattern="TESCO", category="Groceries")
    audit_id = w.update(rule_id, match_type="exact", dry_run=False).json()["audit_id"]
    _web_edit(w, rule_id, pattern="TESCO PFS 3402")
    r = w.undo(audit_id)
    assert r.status_code == 409
    assert "changed since" in r.json()["detail"]
    rule = w.listed(rule_id)
    assert (rule["pattern"], rule["match_type"]) == ("TESCO PFS 3402", "exact")


@pytest.mark.parametrize("edit", [
    {"pattern": "TESCO PFS"}, {"match_type": "regex"}, {"pattern": "^TESCO", "match_type": "regex"},
])
def test_undo_with_no_change_since_restores_a_rule_that_can_run(w, edit):
    from app.services.categorization import validate_pattern
    rule_id = w.rule(pattern="TESCO", category="Groceries")
    audit_id = w.update(rule_id, dry_run=False, **edit).json()["audit_id"]
    assert w.undo(audit_id).status_code == 200
    rule = w.listed(rule_id)
    assert (rule["pattern"], rule["match_type"]) == ("TESCO", "contains")
    assert validate_pattern(rule["pattern"], rule["match_type"]) is None


def _strip_context(w, audit_id):
    """An audit row as written before T-16-1: changed fields only."""
    import json

    def strip():
        entry = w.db.get(AuditEntry, uuid.UUID(audit_id))
        entry.changes = json.dumps([c for c in json.loads(entry.changes) if c["before"] != c["after"]])
        w.db.commit()
    w.as_user(strip)


def test_undo_refuses_a_restore_the_engine_could_not_run(w):
    """sec guard, for audit rows without context: the restored pattern must
    validate under the restored match type, or nothing is restored."""
    rule_id = w.rule(pattern="(a)\\1", category="Groceries", match_type="contains")
    applied = w.update(rule_id, pattern="TESCO", dry_run=False).json()
    assert applied["transactions_recategorized"] == 2
    _strip_context(w, applied["audit_id"])
    _web_edit(w, rule_id, match_type="regex")  # "TESCO" is a fine regex; "(a)\1" isn't
    before = w.categories()
    undos_before = w.count(AuditEntry)

    r = w.undo(applied["audit_id"])
    assert r.status_code == 409
    assert r.json()["detail"] == "Can't undo: the rule it would restore can't run."
    rule = w.listed(rule_id)
    assert (rule["pattern"], rule["match_type"]) == ("TESCO", "regex")
    assert w.categories() == before
    assert w.count(AuditEntry) == undos_before
    w.db.expire_all()
    assert w.as_user(lambda: w.db.get(AuditEntry, uuid.UUID(applied["audit_id"])).undone_at) is None


def test_a_category_undo_on_a_rule_that_cannot_run_still_undoes(w):
    """sec on #259: the guard checks only undos that restore the pattern or
    match type; a category edit on a stored rule RE2 can't run (written
    before #248) undoes as before."""
    rule_id = w.rule(pattern="(a)\\1", category="Groceries", match_type="contains")

    def make_unrunnable():
        w.db.get(CategoryRule, uuid.UUID(rule_id)).match_type = "regex"
        w.db.commit()
    w.as_user(make_unrunnable)
    audit_id = w.update(rule_id, category="Shopping", dry_run=False).json()["audit_id"]
    r = w.undo(audit_id)
    assert r.status_code == 200, r.text
    assert w.listed(rule_id)["category"] == "Groceries"


# --- transactions synced after the edit (T-16-2) --------------------------------------------
# The undo record holds only what the edit's backfill changed. A transaction
# synced later that the edited rule categorised is found at undo time by
# re-matching (sec): inserted after the audit row, not in its record, not
# locked, still in the rule's category and won by this rule. It is cleared,
# then the restored rules run; no match leaves it Uncategorised (None).

def _sync(w, rows, user=None):
    """New transactions arrive as bank sync stores them: inserted now, typed
    by the provider, then run through the user's rules."""
    from app.services import categorization
    from app.services.categorization import category_from_provider
    world = user or w

    def make():
        acc = world.db.query(Account).filter(Account.user_id == world.user.id).first()
        new = []
        for i, (desc, provider_type) in enumerate(rows):
            tx = Transaction(
                account_id=acc.id, external_id=f"sync-{i}-{uuid.uuid4().hex}", transaction_type="debit",
                amount=Decimal("9.99"), currency="GBP", description=desc, merchant_name=desc,
                transaction_date=datetime(2026, 7, 20, tzinfo=timezone.utc),
                category=category_from_provider(provider_type, "debit"),
                created_at=datetime.now(timezone.utc),
            )
            world.db.add(tx)
            new.append(tx)
        world.db.flush()
        categorization.apply_rules(world.db, world.user.id, new)
        world.db.commit()
    world.as_user(make)


def _broaden(w):
    """Claude widens the TESCO rule to also catch AMAZON, as Shopping."""
    rule_id = w.rule(pattern="TESCO", category="Groceries")
    applied = w.update(rule_id, pattern="TESCO|AMAZON", match_type="regex", category="Shopping", dry_run=False)
    assert applied.status_code == 200, applied.text
    return rule_id, applied.json()["audit_id"]


def test_undo_restores_transactions_synced_after_the_edit(w):
    _rule_id, audit_id = _broaden(w)
    _sync(w, [("AMAZON MKTPLACE", "PURCHASE"), ("TESCO EXPRESS", "PURCHASE")])
    assert w.categories()["AMAZON MKTPLACE"] == "Shopping"
    assert w.undo(audit_id).status_code == 200
    after = w.categories()
    assert after["AMAZON MKTPLACE"] is None  # no rule matches after undo
    assert after["TESCO EXPRESS"] == "Groceries"  # the restored rule does


def test_a_transfer_synced_after_the_edit_is_uncategorised_after_undo(w):
    """sec: the provider type isn't stored, so "Transfers" can't be recomputed;
    None overstates spending (fail safe) and is never the edited category."""
    _rule_id, audit_id = _broaden(w)
    _sync(w, [("AMAZON PAY TRANSFER", "TRANSFER")])
    assert w.categories()["AMAZON PAY TRANSFER"] == "Shopping"
    assert w.undo(audit_id).status_code == 200
    assert w.categories()["AMAZON PAY TRANSFER"] is None


def test_a_hand_set_transaction_synced_after_the_edit_is_left_alone(w):
    _rule_id, audit_id = _broaden(w)
    _sync(w, [("AMAZON MKTPLACE", "PURCHASE")])

    def lock():
        # Same category, now the user's. Set directly: the web PATCH also
        # learns an exact rule, which would exclude it by precedence anyway.
        tx = next(t for t in w.db.query(Transaction).join(Account).filter(Account.user_id == w.user.id)
                  if t.description == "AMAZON MKTPLACE")
        tx.category_locked = True
        w.db.commit()
    w.as_user(lock)
    assert w.undo(audit_id).status_code == 200
    assert w.categories()["AMAZON MKTPLACE"] == "Shopping"


def test_a_transaction_recategorised_since_it_synced_is_left_alone(w):
    _rule_id, audit_id = _broaden(w)
    _sync(w, [("AMAZON MKTPLACE", "PURCHASE")])

    def change_since():
        tx = next(t for t in w.db.query(Transaction).join(Account).filter(Account.user_id == w.user.id)
                  if t.description == "AMAZON MKTPLACE")
        tx.category = "Gifts"
        w.db.commit()
    w.as_user(change_since)
    assert w.undo(audit_id).status_code == 200
    assert w.categories()["AMAZON MKTPLACE"] == "Gifts"


def test_a_transaction_another_rule_now_wins_is_left_alone(w):
    """A rule added after the sync claims it with another category."""
    _rule_id, audit_id = _broaden(w)
    _sync(w, [("AMAZON MKTPLACE", "PURCHASE")])
    w.rule(pattern="AMAZON MKTPLACE", match_type="exact", category="Online")
    assert w.categories()["AMAZON MKTPLACE"] == "Online"
    assert w.undo(audit_id).status_code == 200
    assert w.categories()["AMAZON MKTPLACE"] == "Online"


def test_a_transaction_from_before_the_edit_is_not_re_matched(w):
    """Already in the edited category before the edit, so the backfill didn't
    record it; it wasn't synced after either, so undo leaves it."""
    w.transactions([("AMAZON MKTPLACE", 20)])

    def preset():
        tx = next(t for t in w.db.query(Transaction).join(Account).filter(Account.user_id == w.user.id)
                  if t.description == "AMAZON MKTPLACE")
        tx.category = "Shopping"
        w.db.commit()
    w.as_user(preset)
    _rule_id, audit_id = _broaden(w)
    assert w.undo(audit_id).status_code == 200
    assert w.categories()["AMAZON MKTPLACE"] == "Shopping"


def test_another_users_transactions_synced_after_the_edit_are_untouched(client, db_session, w):
    """sec: only the caller's transactions are loaded."""
    other = World(client, db_session, email="claude-rules-other@example.com")
    other.transactions([("TESCO PFS 1", 5)])
    other.rule(pattern="TESCO|AMAZON", match_type="regex", category="Shopping")
    _rule_id, audit_id = _broaden(w)
    _sync(w, [("AMAZON MKTPLACE", "PURCHASE")], user=other)
    assert other.categories()["AMAZON MKTPLACE"] == "Shopping"
    assert w.undo(audit_id).status_code == 200
    assert other.categories()["AMAZON MKTPLACE"] == "Shopping"


def test_a_failed_undo_restores_nothing(w, monkeypatch):
    """Undo is one transaction: a failure after the clearing leaves the rule,
    every category and the audit row as they were."""
    from app.services import categorization
    rule_id, audit_id = _broaden(w)
    _sync(w, [("AMAZON MKTPLACE", "PURCHASE")])
    before = w.categories()

    def boom(*args, **kwargs):
        raise RuntimeError("re-run failed")
    monkeypatch.setattr(categorization, "apply_rules", boom)
    with pytest.raises(RuntimeError):
        w.undo(audit_id)
    monkeypatch.undo()
    w.db.rollback()
    assert w.categories() == before
    assert w.listed(rule_id)["pattern"] == "TESCO|AMAZON"
    assert w.as_user(lambda: w.db.get(AuditEntry, uuid.UUID(audit_id)).undone_at) is None
    assert w.undo(audit_id).status_code == 200
    assert w.categories()["AMAZON MKTPLACE"] is None
