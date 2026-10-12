"""Budget history: lazy per-cycle snapshots and GET /budgets/history
(T-09-3; concept section 14, BH1-BH12; sec's T-09-3 criteria).

The user's payday was 20 days ago (monthly), so the completed cycles end
21, about 51, 81 ... days ago. Eating out spent 45, 50, 55, 60 and Groceries
85, 90, 95, 100 in the last four completed cycles (newest first).
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.models import BudgetChange, CommitmentRule
from tests.clock import TODAY
from tests.integration.test_budgets_api import API, World
from tests.integration.test_oauth import READ, _bearer, _connect

LONG_AGO = datetime.combine(TODAY - timedelta(days=200), datetime.min.time(), tzinfo=timezone.utc)


@pytest.fixture
def w(client, db_session):
    world = World(client, db_session)
    world.history(cycles=6)
    return world


def _backdate(w, budget_id, when=LONG_AGO):
    """As if the budget was made `when` (its change log too)."""
    w.db.execute(text("UPDATE budgets SET created_at = :t WHERE id = :id"), {"t": when, "id": budget_id.replace("-", "")})
    w.db.execute(text("UPDATE budget_changes SET effective_at = :t WHERE budget_id = :id"),
                 {"t": when, "id": budget_id.replace("-", "")})
    w.db.commit()


def _days_ago(days):
    return datetime.combine(TODAY - timedelta(days=days), datetime.min.time(), tzinfo=timezone.utc)


def _history(w, token=None, **params):
    r = w.client.get(f"{API}/budgets/history", params=params, headers=_bearer(token or w.web))
    assert r.status_code == 200, r.text
    return r.json()


def _budget(body, category):
    return next(b for b in body["budgets"] if b["category"] == category)


def _snapshots(w):
    return w.db.execute(text("SELECT count(*) FROM budget_cycle_snapshots")).scalar()


def test_kept_means_at_or_under_the_limit_at_close(w):
    budget_id = w.create("Eating out", 50).json()["id"]
    _backdate(w, budget_id)
    body = _history(w, cycles=3)
    slots = _budget(body, "Eating out")["cycles"]
    assert [(s["limit_pounds"], s["spent"], s["kept"]) for s in slots] == [
        (50, "55.00", False), (50, "50.00", True), (50, "45.00", True)]  # oldest first
    assert (_budget(body, "Eating out")["kept"], _budget(body, "Eating out")["counted"]) == (2, 3)
    assert _budget(body, "Eating out")["usually"] == "50.00"


def test_a_limit_changed_after_a_cycle_closed_doesnt_rewrite_it(w):
    """sec: close a cycle, change the limit before the first load, then
    load: the old limit and verdict are shown."""
    budget_id = w.create("Eating out", 50).json()["id"]
    _backdate(w, budget_id)
    w.patch(budget_id, limit_pounds=40)  # today, after every completed cycle closed
    slots = _budget(_history(w, cycles=3), "Eating out")["cycles"]
    assert [s["limit_pounds"] for s in slots] == [50, 50, 50]
    assert [s["kept"] for s in slots] == [False, True, True]


def test_a_snapshot_is_written_once_and_never_changes(w):
    budget_id = w.create("Eating out", 50).json()["id"]
    _backdate(w, budget_id)
    first = _history(w, cycles=3)
    count = _snapshots(w)
    from tests.integration.test_transactions_endpoint import _tx
    w.as_user(lambda: (_tx(w.db, w.current, "500.00", TODAY - timedelta(days=35), merchant="Late", category="Eating out"),
                       w.db.commit()))
    assert _history(w, cycles=3) == first
    assert _snapshots(w) == count


def test_get_budgets_writes_them_too(w):
    budget_id = w.create("Eating out", 50).json()["id"]
    _backdate(w, budget_id)
    assert _snapshots(w) == 0
    w.get()
    assert _snapshots(w) > 0


def test_a_payday_change_doesnt_move_history(w):
    budget_id = w.create("Eating out", 50).json()["id"]
    _backdate(w, budget_id)
    before = [(c["start"], c["end"]) for c in _history(w, cycles=6)["cycles"]]

    def move_payday():
        rule = w.db.query(CommitmentRule).filter(CommitmentRule.is_payday.is_(True)).one()
        rule.next_date = TODAY - timedelta(days=10)
        w.db.commit()
    w.as_user(move_payday)
    after = [(c["start"], c["end"]) for c in _history(w, cycles=6)["cycles"]]
    assert after[: len(before)] == before or set(before) <= set(after)


def test_overall_on_target(w):
    a = w.create("Eating out", 50).json()["id"]
    b = w.create("Groceries", 90).json()["id"]
    _backdate(w, a)
    _backdate(w, b)
    body = _history(w, cycles=3)
    # oldest first: (55+95 vs 140) over, (50+90) on, (45+85) on
    assert [c["on_target"] for c in body["cycles"]] == [False, True, True]
    assert (body["on_target"], body["counted"]) == (2, 3)


def test_a_budget_made_mid_history_has_empty_slots(w):
    a = w.create("Eating out", 50).json()["id"]
    _backdate(w, a)
    b = w.create("Groceries", 90).json()["id"]
    _backdate(w, b, datetime.combine(TODAY - timedelta(days=40), datetime.min.time(), tzinfo=timezone.utc))
    groceries = _budget(_history(w, cycles=3), "Groceries")
    assert [s["existed"] for s in groceries["cycles"]] == [False, False, True]
    assert groceries["counted"] == 1


def test_a_paused_cycle_is_its_own_slot_and_not_counted(w):
    budget_id = w.create("Eating out", 50).json()["id"]
    _backdate(w, budget_id)

    def paused_then_resumed():
        import uuid as _uuid
        bid = _uuid.UUID(budget_id)
        # Paused 90 days ago, resumed 60 days ago: paused at the close of the
        # oldest of the three cycles (~82 days ago) only.
        for days, paused in ((90, True), (60, False)):
            w.db.add(BudgetChange(user_id=w.user.id, budget_id=bid, limit_pounds=Decimal("50"), paused=paused,
                                  active=True, effective_at=datetime.combine(TODAY - timedelta(days=days),
                                                                             datetime.min.time(), tzinfo=timezone.utc)))
        w.db.commit()
    w.as_user(paused_then_resumed)
    eating = _budget(_history(w, cycles=3), "Eating out")
    assert [s["paused"] for s in eating["cycles"]] == [True, False, False]
    assert eating["counted"] == 2


def test_cycles_are_capped_and_before_pages(w):
    budget_id = w.create("Eating out", 50).json()["id"]
    _backdate(w, budget_id)
    assert w.client.get(f"{API}/budgets/history", params={"cycles": 13}, headers=_bearer(w.web)).status_code == 422
    assert w.client.get(f"{API}/budgets/history", params={"before": "not-a-date"},
                        headers=_bearer(w.web)).status_code == 422
    newest = _history(w, cycles=2)
    assert newest["has_more"] is True
    older = _history(w, cycles=2, before=newest["cycles"][0]["start"])
    assert older["cycles"][-1]["end"] < newest["cycles"][0]["start"]


def test_trend_needs_6_cycles(w):
    short = w.create("Eating out", 500).json()["id"]
    _backdate(w, short, _days_ago(100))  # 3 completed cycles
    assert _history(w, cycles=6)["trend"] is None
    _backdate(w, short)
    w.db.execute(text("DELETE FROM budget_cycle_snapshots"))
    w.db.commit()
    trend = _history(w, cycles=6)["trend"]
    # Older spends are higher (60.. back), so recent cycles are lower.
    assert trend is not None and trend["direction"] in ("lower", "same")


def test_another_users_history_is_their_own(client, db_session, w):
    budget_id = w.create("Eating out", 50).json()["id"]
    _backdate(w, budget_id)
    _history(w)
    other = World(client, db_session, email="other@example.com")
    body = _history(other)
    assert body["cycles"] == [] and body["budgets"] == []


def test_history_is_web_only(client, db_session):
    w = World(client, db_session, email="mcp-history@example.com")
    _, _, tokens = _connect(client, scopes=(READ,), email="mcp-history@example.com")
    assert w.client.get(f"{API}/budgets/history", headers=_bearer(tokens["access_token"])).status_code == 401


def test_amounts_are_encrypted_at_rest(w):
    budget_id = w.create("Eating out", 50).json()["id"]
    _backdate(w, budget_id)
    _history(w)
    raw = w.db.execute(text("SELECT limit_pounds, spent FROM budget_cycle_snapshots")).first()
    for value in raw:
        assert _not_a_number(value)


def _not_a_number(value) -> bool:
    """Ciphertext, not the amount: a base64 token can contain digits, so a
    substring check would flake."""
    from decimal import InvalidOperation
    try:
        Decimal(str(value))
    except InvalidOperation:
        return len(str(value)) > 40
    return False


def test_a_request_that_dies_mid_cycle_leaves_no_gap(w, monkeypatch):
    """sec on #160: snapshots are immutable, so a cycle written for one budget
    but not another would be a permanent hole. A cycle is written whole or
    not at all, and the next load fills it."""
    from app.services import budget_history

    a = w.create("Eating out", 50).json()["id"]
    b = w.create("Groceries", 90).json()["id"]
    _backdate(w, a)
    _backdate(w, b)
    real = budget_history._snapshot_row
    calls = []

    def dies_on_the_second(*args):
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("the request died")
        return real(*args)

    monkeypatch.setattr(budget_history, "_snapshot_row", dies_on_the_second)
    with pytest.raises(RuntimeError):
        w.as_user(lambda: budget_history.write_snapshots(w.db, w.user))
    assert _snapshots(w) == 0  # nothing half-written
    monkeypatch.setattr(budget_history, "_snapshot_row", real)
    body = _history(w, cycles=3)
    for category in ("Eating out", "Groceries"):
        assert all(s["existed"] for s in _budget(body, category)["cycles"])


def test_the_snapshot_amounts_decrypt_with_the_users_key(w):
    from app.models import BudgetCycleSnapshot

    budget_id = w.create("Eating out", 50).json()["id"]
    _backdate(w, budget_id)
    _history(w, cycles=1)
    w.db.expire_all()
    snap = w.as_user(lambda: w.db.query(BudgetCycleSnapshot).order_by(BudgetCycleSnapshot.cycle_end.desc()).first())
    assert w.as_user(lambda: (Decimal(snap.limit_pounds), Decimal(snap.spent))) == (Decimal("50"), Decimal("45.00"))


def test_a_failed_snapshot_write_never_hides_the_budgets(w, monkeypatch, caplog):
    """If writing snapshots fails, GET /budgets still answers with the
    budgets, logs no category or amount, and the next load retries."""
    from app.services import budget_history

    budget_id = w.create("Eating out", 50).json()["id"]
    _backdate(w, budget_id)
    real = budget_history.budget_spend

    def broken(*args, **kwargs):
        raise ValueError("Eating out 50.00")
    monkeypatch.setattr(budget_history, "budget_spend", broken)
    caplog.set_level("INFO")
    r = w.get()
    assert r.status_code == 200, r.text
    assert [b["category"] for b in r.json()["budgets"]] == ["Eating out"]
    assert _snapshots(w) == 0
    assert "Eating out" not in caplog.text and "50.00" not in caplog.text
    monkeypatch.setattr(budget_history, "budget_spend", real)
    w.get()
    assert _snapshots(w) > 0


# --- eng-a's #160 nits ----------------------------------------------------------------

def test_a_budget_from_before_the_log_keeps_its_old_limit_when_edited(w):
    """A budget made before the change log existed has no rows. Editing it
    first records its state from creation, so History still judges older
    cycles by the old limit."""
    budget_id = w.create("Eating out", 50).json()["id"]
    _backdate(w, budget_id)
    w.db.execute(text("DELETE FROM budget_changes"))
    w.db.commit()
    w.patch(budget_id, limit_pounds=40)
    slots = _budget(_history(w, cycles=3), "Eating out")["cycles"]
    assert [s["limit_pounds"] for s in slots] == [50, 50, 50]


def test_the_trend_uses_every_stored_cycle_not_just_the_page(w):
    """The trend compares the latest 6 completed cycles, whatever page."""
    budget_id = w.create("Eating out", 500).json()["id"]
    _backdate(w, budget_id)
    full = _history(w, cycles=6)["trend"]
    assert full is not None
    assert _history(w, cycles=2)["trend"] == full


# --- one row per category (BH15, ux on #160) ---------------------------------------------
# Completed cycles end about 171, 141, 111, 81, 51 and 21 days ago (c1 to c6,
# oldest first); Eating out spent 0, 65, 60, 55, 50, 45 in them.

def _removed_on(w, budget_id, when):
    w.db.execute(text("UPDATE budget_changes SET effective_at = :t WHERE budget_id = :id AND active = :f"),
                 {"t": when, "id": budget_id.replace("-", ""), "f": False})
    w.db.commit()


def _groceries_throughout(w):
    """Another budget, so every cycle has a snapshot (a cycle with no budget
    at all is not in History)."""
    _backdate(w, w.create("Groceries", 200).json()["id"])


def _removed_in_c3_readded_in_c5(w):
    _groceries_throughout(w)
    old = w.create("Eating out", 50).json()["id"]
    _backdate(w, old)
    assert w.delete(old).status_code == 204
    _removed_on(w, old, _days_ago(125))
    new = w.create("Eating out", 60).json()["id"]
    _backdate(w, new, _days_ago(70))
    return old, new


def test_a_removed_and_re_added_category_is_one_row(w):
    _, new = _removed_in_c3_readded_in_c5(w)
    rows = [b for b in _history(w, cycles=6)["budgets"] if b["category"] == "Eating out"]
    assert len(rows) == 1
    row = rows[0]
    assert [(s["existed"], s["limit_pounds"]) for s in row["cycles"]] == [
        (True, 50), (True, 50), (False, None), (False, None), (True, 60), (True, 60)]
    assert row["budget_id"] == new and row["limit_pounds"] == 60 and row["removed"] is False


def test_kept_and_usually_span_both_budgets_and_skip_the_gap(w):
    _removed_in_c3_readded_in_c5(w)
    row = _budget(_history(w, cycles=6), "Eating out")
    assert [s["kept"] for s in row["cycles"]] == [True, False, None, None, True, True]
    assert (row["kept"], row["counted"]) == (3, 4)
    assert row["usually"] == "40.00"  # (0 + 65 + 50 + 45) / 4


def test_a_removed_category_with_no_replacement_is_flagged(w):
    old = w.create("Eating out", 50).json()["id"]
    _backdate(w, old)
    assert w.delete(old).status_code == 204
    _removed_on(w, old, _days_ago(125))
    row = _budget(_history(w, cycles=6), "Eating out")
    assert row["removed"] is True and row["limit_pounds"] == 50 and row["budget_id"] == old


def test_a_removed_category_goes_once_no_shown_cycle_had_it(w):
    _groceries_throughout(w)
    old = w.create("Eating out", 50).json()["id"]
    _backdate(w, old)
    assert w.delete(old).status_code == 204
    _removed_on(w, old, _days_ago(125))
    assert [b["category"] for b in _history(w, cycles=2)["budgets"]] == ["Groceries"]


def test_a_snapshot_always_has_its_written_at(w):
    """eng-a on #160: NOT NULL, with the server default filling it."""
    from app.models import BudgetCycleSnapshot
    assert BudgetCycleSnapshot.__table__.c.written_at.nullable is False
    _backdate(w, w.create("Eating out", 50).json()["id"])
    _history(w, cycles=3)
    assert w.db.execute(text("SELECT count(*) FROM budget_cycle_snapshots WHERE written_at IS NULL")).scalar() == 0
