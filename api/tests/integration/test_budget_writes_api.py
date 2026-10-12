"""Claude's budget writes over MCP (T-09-5; concept section 6; sec's T-09-5
criteria; owner D6 = No).

Routes under /planning/budgets take a token with the new
`finance:budgets.write` scope (not finance:planning.write, whose consent
named planned events and commitments only). Every write goes through the
Sprint 08 framework: dry_run by default, an idempotency key, an encrypted
audit row (`target_kind: "budget"`), web-only undo with 409 "changed since"
and the shared per-user write limit. Only `limit_pounds`, `paused` and
`active` can change. A budget is addressed by id only. `set` takes a whole
set (at most 8), validated before anything is written, applied in one
transaction with one batch id. A lowered limit applies at once (D6). Pausing
or removing keeps the category counting this cycle (sec's max rule), and
a pause or resume that changes nothing is a 422.
"""
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import func, select, text

from app.models import AuditEntry, Budget, BudgetChange
from tests.integration.test_budgets_api import API, World as BudgetsWorld
from tests.clock import TODAY
from tests.integration.test_oauth import READ, _bearer, _connect
from tests.integration.test_transactions_endpoint import _tx

BUDGETS_WRITE = "finance:budgets.write"
PLANNING = "finance:planning.write"


class World(BudgetsWorld):
    def __init__(self, client, db, email="claude-budgets@example.com", scopes=(READ, BUDGETS_WRITE)):
        super().__init__(client, db, email)
        _, _, tokens = _connect(client, scopes=scopes, email=email)
        self.mcp = tokens["access_token"]

    def _post(self, path, token=None, **body):
        body.setdefault("idempotency_key", f"k-{uuid.uuid4().hex[:12]}")
        return self.client.post(f"{API}/planning/budgets{path}", json=body, headers=_bearer(token or self.mcp))

    def claude_set(self, entries, **body):
        return self._post("/set", budgets=entries, **body)

    def claude(self, action, budget_id, **body):
        return self._post(f"/{budget_id}/{action}", **body)

    def count(self, model):
        return self.db.execute(select(func.count()).select_from(model)).scalar()

    def undo(self, audit_id):
        return self.client.post(f"{API}/audit/{audit_id}/undo", headers=_bearer(self.web))


@pytest.fixture
def w(client, db_session):
    world = World(client, db_session)
    world.history()
    return world


def _limits(w):
    return {b["category"]: (b["limit_pounds"], b["paused"]) for b in w.get().json()["budgets"]}


# --- scope ------------------------------------------------------------------------------

def test_a_planning_token_cant_write_budgets(client, db_session):
    w = World(client, db_session, email="planning-only@example.com", scopes=(READ, PLANNING))
    w.history()
    r = w.claude_set([{"category": "Eating out", "limit_pounds": 150}], dry_run=False)
    assert r.status_code == 403
    assert BUDGETS_WRITE in r.headers["WWW-Authenticate"]
    assert w.count(Budget) == 0


def test_a_read_token_can_list_budgets(w):
    _, _, tokens = _connect(w.client, scopes=(READ,), email="claude-budgets@example.com")
    w.create("Eating out", 150)
    r = w.client.get(f"{API}/budgets", headers=_bearer(tokens["access_token"]))
    assert r.status_code == 200 and r.json()["budgets"][0]["category"] == "Eating out"


def test_the_scope_is_offered(client):
    meta = client.get("/.well-known/oauth-authorization-server").json()
    assert BUDGETS_WRITE in meta["scopes_supported"]


# --- set: preview, apply, all or nothing -------------------------------------------------

def test_set_previews_by_default_and_writes_nothing(w):
    r = w.claude_set([{"category": "Eating out", "limit_pounds": 150}])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["dry_run"] is True
    [entry] = body["results"]
    assert entry["target_label"] == "Eating out"
    assert {"field": "limit_pounds", "before": None, "after": "150"} in entry["changes"]
    assert (w.count(Budget), w.count(AuditEntry), w.count(BudgetChange)) == (0, 0, 0)


def test_set_applies_creates_and_updates_in_one_batch(w):
    w.create("Groceries", 300)
    r = w.claude_set([{"category": "Eating out", "limit_pounds": 150},
                      {"category": "Groceries", "limit_pounds": 260}], dry_run=False)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["dry_run"] is False and body["batch_id"]
    assert _limits(w) == {"Eating out": (150, False), "Groceries": (260, False)}  # lowered at once (D6)
    rows = w.db.query(AuditEntry.batch_id, AuditEntry.tool).filter(AuditEntry.target_kind == "budget").all()
    assert len(rows) == 2 and {str(batch) for batch, _ in rows} == {body["batch_id"]}
    assert {tool for _, tool in rows} == {"set_budgets"}
    created = next(b for b in w.get().json()["budgets"] if b["category"] == "Eating out")
    assert created["created_via"] == "mcp"


def test_set_marks_the_budgets_changed_by_claude(w):
    w.claude_set([{"category": "Eating out", "limit_pounds": 150}], dry_run=False)
    [budget] = w.get().json()["budgets"]
    assert budget["changed_by_claude"]["audit_id"]


@pytest.mark.parametrize("bad_last", [
    {"category": "Holidays", "limit_pounds": 50},     # not a purchase category
    {"category": "Rent", "limit_pounds": 50},         # commitment-covered
    {"category": "Groceries", "limit_pounds": 0},     # bounds
    {"category": "Eating out", "limit_pounds": 99},   # duplicate in one call
])
def test_set_writes_nothing_when_any_entry_is_invalid(w, bad_last):
    r = w.claude_set([{"category": "Eating out", "limit_pounds": 120}, {"category": "Shopping", "limit_pounds": 10},
                      bad_last], dry_run=False)
    assert r.status_code == 422
    assert (w.count(Budget), w.count(AuditEntry), w.count(BudgetChange)) == (0, 0, 0)


def test_set_takes_at_most_8(w):
    entries = [{"category": f"Cat {i}", "limit_pounds": 10} for i in range(9)]
    assert w.claude_set(entries).status_code == 422


def test_set_is_idempotent(w):
    entries = [{"category": "Eating out", "limit_pounds": 150}]
    first = w.claude_set(entries, dry_run=False, idempotency_key="set-key-0001").json()
    again = w.claude_set(entries, dry_run=False, idempotency_key="set-key-0001").json()
    assert again["batch_id"] == first["batch_id"]
    assert w.count(Budget) == 1 and w.count(AuditEntry) == 1


def test_set_records_the_change_log(w):
    w.claude_set([{"category": "Eating out", "limit_pounds": 150}], dry_run=False)
    assert w.count(BudgetChange) == 1


def test_set_refuses_extra_fields(w):
    r = w.claude_set([{"category": "Eating out", "limit_pounds": 150, "paused": True}])
    assert r.status_code == 422
    r = w._post("/set", budgets=[{"category": "Eating out", "limit_pounds": 150}], user_id=str(uuid.uuid4()))
    assert r.status_code == 422


# --- pause, resume, remove ------------------------------------------------------------------

def test_pause_and_resume(w):
    budget_id = w.create("Eating out", 150).json()["id"]
    r = w.claude("pause", budget_id, dry_run=False)
    assert r.status_code == 200, r.text
    assert {"field": "paused", "before": False, "after": True} in r.json()["changes"]
    assert _limits(w)["Eating out"] == (150, True)
    assert w.claude("resume", budget_id, dry_run=False).status_code == 200
    assert _limits(w)["Eating out"] == (150, False)


def test_a_pause_or_resume_that_changes_nothing_is_a_422(w):
    budget_id = w.create("Eating out", 150).json()["id"]
    assert w.claude("resume", budget_id, dry_run=False).status_code == 422
    w.claude("pause", budget_id, dry_run=False)
    assert w.claude("pause", budget_id, dry_run=False).status_code == 422


def test_remove(w):
    budget_id = w.create("Eating out", 150).json()["id"]
    r = w.claude("remove", budget_id, dry_run=False)
    assert r.status_code == 200, r.text
    assert w.get().json()["budgets"] == []


def test_claudes_pause_and_remove_never_raise_the_figures(w):
    """sec: the T-09-4 max rule covers Claude's pause and remove too."""
    budget_id = w.create("Eating out", 300).json()["id"]
    w.create("Groceries", 400)
    headroom = Decimal(w.get().json()["reconciliation"]["headroom"])
    w.claude("pause", budget_id, dry_run=False)
    assert Decimal(w.get().json()["reconciliation"]["headroom"]) <= headroom
    w.claude("resume", budget_id, dry_run=False)
    w.claude("remove", budget_id, dry_run=False)
    assert Decimal(w.get().json()["reconciliation"]["headroom"]) <= headroom


def test_another_users_budget_is_not_found_and_nothing_is_audited(client, db_session, w):
    budget_id = w.create("Eating out", 150).json()["id"]
    other = World(client, db_session, email="other-claude@example.com")
    assert other.claude("pause", budget_id, dry_run=False).status_code == 404
    assert w.count(AuditEntry) == 0
    assert _limits(w)["Eating out"] == (150, False)


def test_a_budget_is_addressed_by_id_only(w):
    assert w.claude("pause", "Eating%20out", dry_run=False).status_code == 422


# --- undo (web only) --------------------------------------------------------------------------

def test_undo_of_a_created_budget_removes_it(w):
    r = w.claude_set([{"category": "Eating out", "limit_pounds": 150}], dry_run=False)
    audit_id = r.json()["results"][0]["audit_id"]
    assert w.undo(audit_id).status_code == 200
    assert w.get().json()["budgets"] == []


def test_undo_of_an_edit_restores_the_limit(w):
    w.create("Groceries", 300)
    r = w.claude_set([{"category": "Groceries", "limit_pounds": 260}], dry_run=False)
    assert w.undo(r.json()["results"][0]["audit_id"]).status_code == 200
    assert _limits(w)["Groceries"] == (300, False)


def test_undo_of_a_pause_resumes(w):
    budget_id = w.create("Eating out", 150).json()["id"]
    audit_id = w.claude("pause", budget_id, dry_run=False).json()["audit_id"]
    assert w.undo(audit_id).status_code == 200
    assert _limits(w)["Eating out"] == (150, False)


def test_undo_after_a_change_since_is_a_409(w):
    budget_id = w.create("Groceries", 300).json()["id"]
    r = w.claude_set([{"category": "Groceries", "limit_pounds": 260}], dry_run=False)
    w.patch(budget_id, limit_pounds=280)
    assert w.undo(r.json()["results"][0]["audit_id"]).status_code == 409


def test_undo_records_the_change_log(w):
    budget_id = w.create("Groceries", 300).json()["id"]
    before = w.count(BudgetChange)
    r = w.claude_set([{"category": "Groceries", "limit_pounds": 260}], dry_run=False)
    w.undo(r.json()["results"][0]["audit_id"])
    assert w.count(BudgetChange) == before + 2  # the edit, then the undo
    assert budget_id


def test_claude_cant_undo_or_read_the_trail(w):
    r = w.claude_set([{"category": "Eating out", "limit_pounds": 150}], dry_run=False)
    audit_id = r.json()["results"][0]["audit_id"]
    assert w.client.post(f"{API}/audit/{audit_id}/undo", headers=_bearer(w.mcp)).status_code == 401
    assert w.client.get(f"{API}/audit", headers=_bearer(w.mcp)).status_code == 401


def test_the_audit_row_is_encrypted(w):
    w.claude_set([{"category": "Eating out", "limit_pounds": 150}], dry_run=False)
    raw = w.db.execute(text("SELECT target_label, changes FROM audit_entries")).first()
    assert "Eating out" not in str(raw[0]) and "150" not in str(raw[1]).replace("1500", "")


@pytest.mark.parametrize("action", ["pause", "remove"])
def test_every_claude_write_and_its_undo_records_the_change_log(w, action):
    """Lead on #160: the change log sees every Claude write and every undo."""
    budget_id = w.create("Eating out", 150).json()["id"]
    before = w.count(BudgetChange)
    audit_id = w.claude(action, budget_id, dry_run=False).json()["audit_id"]
    assert w.count(BudgetChange) == before + 1
    assert w.undo(audit_id).status_code == 200
    assert w.count(BudgetChange) == before + 2
    last = (w.db.query(BudgetChange.paused, BudgetChange.active)
            .order_by(BudgetChange.effective_at.desc(), BudgetChange.id.desc()).first())
    assert tuple(last) == (False, True)  # the undo's state



# --- undo keeps the max rule (sec and eng-a on #162) ---------------------------------------

def _spend(w, amount, category="Eating out"):
    def make():
        _tx(w.db, w.current, amount, TODAY, merchant="Shop again", category=category)
        w.db.commit()
    w.as_user(make)


def _headroom(w):
    return Decimal(w.get().json()["reconciliation"]["headroom"])


def test_undoing_claudes_resume_brings_back_the_same_hold(w):
    budget_id = w.create("Eating out", 300).json()["id"]
    w.create("Groceries", 400)
    w.patch(budget_id, paused=True)
    before = _headroom(w)
    audit_id = w.claude("resume", budget_id, dry_run=False).json()["audit_id"]
    assert w.undo(audit_id).status_code == 200
    assert _limits(w)["Eating out"] == (300, True)
    assert _headroom(w) == before


def test_spending_between_the_pause_and_the_undo_doesnt_raise_headroom(w):
    budget_id = w.create("Eating out", 300).json()["id"]
    w.create("Groceries", 400)
    w.patch(budget_id, paused=True)
    _spend(w, "100.00")
    before = _headroom(w)
    audit_id = w.claude("resume", budget_id, dry_run=False).json()["audit_id"]
    assert w.undo(audit_id).status_code == 200
    assert _headroom(w) == before


def test_removing_again_after_an_undone_removal_keeps_the_first_hold(w):
    budget_id = w.create("Eating out", 300).json()["id"]
    w.create("Groceries", 400)
    audit_id = w.claude("remove", budget_id, dry_run=False).json()["audit_id"]
    _spend(w, "100.00")
    before = _headroom(w)
    assert w.undo(audit_id).status_code == 200  # re-activated
    assert w.claude("remove", budget_id, dry_run=False).status_code == 200
    assert _headroom(w) == before


def test_an_unchanged_entry_in_a_set_writes_no_audit_or_change_row(w):
    """sec on #162 (low): only the entries that change anything are recorded."""
    w.create("Groceries", 300)
    before = (w.count(AuditEntry), w.count(BudgetChange))
    r = w.claude_set([{"category": "Groceries", "limit_pounds": 300},
                      {"category": "Eating out", "limit_pounds": 150}], dry_run=False)
    assert r.status_code == 200, r.text
    unchanged = next(e for e in r.json()["results"] if e["target_label"] == "Groceries")
    assert unchanged["unchanged"] is True and unchanged["audit_id"] is None
    assert (w.count(AuditEntry), w.count(BudgetChange)) == (before[0] + 1, before[1] + 1)


# --- a budget from before the change log keeps its old limit (eng-a on #160) ---------------

def _pre_log_budget(w, limit=50):
    """A budget made long ago, before the change log existed (no rows)."""
    from tests.integration.test_budget_history import _backdate
    budget_id = w.create("Eating out", limit).json()["id"]
    _backdate(w, budget_id)
    w.db.execute(text("DELETE FROM budget_changes"))
    w.db.commit()
    return budget_id


def _old_limits(w):
    from tests.integration.test_budget_history import _budget, _history
    return [s["limit_pounds"] for s in _budget(_history(w, cycles=3), "Eating out")["cycles"]]


@pytest.mark.parametrize("write", ["set", "pause", "remove"])
def test_claudes_first_write_to_a_pre_log_budget_keeps_its_old_limit(w, write):
    budget_id = _pre_log_budget(w)
    if write == "set":
        r = w.claude_set([{"category": "Eating out", "limit_pounds": 40}], dry_run=False)
    else:
        r = w.claude(write, budget_id, dry_run=False)
    assert r.status_code == 200, r.text
    assert _old_limits(w) == [50, 50, 50]


def test_claudes_resume_of_a_pre_log_budget_keeps_its_old_state(w):
    budget_id = _pre_log_budget(w)
    w.db.execute(text("UPDATE budgets SET paused = :t WHERE id = :id"), {"t": True, "id": budget_id.replace("-", "")})
    w.db.commit()
    assert w.claude("resume", budget_id, dry_run=False).status_code == 200
    from tests.integration.test_budget_history import _budget, _history
    slots = _budget(_history(w, cycles=3), "Eating out")["cycles"]
    assert [s["paused"] for s in slots] == [True, True, True]


def test_an_undo_on_a_budget_with_no_log_records_the_state_it_restores(w):
    budget_id = _pre_log_budget(w)
    audit_id = w.claude_set([{"category": "Eating out", "limit_pounds": 40}], dry_run=False).json()["results"][0]["audit_id"]
    w.db.execute(text("DELETE FROM budget_changes"))
    w.db.commit()
    assert w.undo(audit_id).status_code == 200
    assert _old_limits(w) == [50, 50, 50]
    assert budget_id
