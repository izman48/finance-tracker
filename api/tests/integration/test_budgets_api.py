"""Budgets: table, CRUD, bulk PUT and suggest (T-09-2; budgets concept
sections 2, 13 and 15; sec's T-09-2 criteria).

A budget is one whole-pound limit (1 to 100,000) for one of the user's own
categories, at most one active per category and 20 per user. The limit is
DEK-encrypted. The category is untrusted text (Claude can create category
labels through rule packs): it must be one of the user's categories, at
most 100 characters with no hidden characters, it's never in a URL path, and
a category whose spending is mostly commitments can't have a budget.
PUT /budgets is all or nothing. Suggest writes nothing. Every route is web
session only and scoped to the caller; another user's id is a 404.
"""
import logging
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select, text

from app.models import Budget, CommitmentRule
from tests.clock import TODAY
from tests.integration.test_oauth import READ, _bearer, _connect, _web_login
from tests.integration.test_transactions_endpoint import _account, _dek_from_token, _tx
from tests.integration.test_budget_spend import World as SpendWorld

API = "/api/v1"


class World(SpendWorld):
    """A user with a payday 20 days ago (so a cycle of about a month), a
    current account and a card, and spending history in a few categories."""

    def __init__(self, client, db, email="budgets@example.com"):
        super().__init__(client, db, email)
        self.client = client
        self.web = _web_login(client, email)

    def history(self, categories=("Eating out", "Groceries", "Shopping"), cycles=5):
        """Spending in each category for the last `cycles` months, plus rent."""
        def make():
            db, uid = self.db, self.user.id
            self.current = _account(db, uid, name="Current", balance="3000")
            db.add(CommitmentRule(user_id=uid, direction="income", label="Salary", amount=Decimal("2500"),
                                  cadence="monthly", next_date=TODAY - timedelta(days=20), source="manual",
                                  status="confirmed", is_payday=True))
            db.add(CommitmentRule(user_id=uid, direction="expense", label="LANDLORD RENT", amount=Decimal("950"),
                                  cadence="monthly", next_date=TODAY + timedelta(days=5), source="manual",
                                  status="confirmed"))
            for back in range(cycles):
                day = TODAY - timedelta(days=5 + 30 * back)
                for i, cat in enumerate(categories):
                    _tx(db, self.current, f"{(i + 1) * 40 + back * 5}.00", day, merchant=f"Shop {cat}", category=cat)
                _tx(db, self.current, "950.00", day, merchant="LANDLORD RENT", category="Rent")
            db.commit()
        self.as_user(make)

    def get(self, token=None):
        return self.client.get(f"{API}/budgets", headers=_bearer(token or self.web))

    def create(self, category="Eating out", limit=150, token=None):
        return self.client.post(f"{API}/budgets", json={"category": category, "limit_pounds": limit},
                                headers=_bearer(token or self.web))

    def patch(self, budget_id, token=None, **body):
        return self.client.patch(f"{API}/budgets/{budget_id}", json=body, headers=_bearer(token or self.web))

    def delete(self, budget_id, token=None):
        return self.client.delete(f"{API}/budgets/{budget_id}", headers=_bearer(token or self.web))

    def put(self, entries, token=None):
        return self.client.put(f"{API}/budgets", json={"budgets": entries}, headers=_bearer(token or self.web))

    def suggest(self):
        return self.client.post(f"{API}/budgets/suggest", json={}, headers=_bearer(self.web))

    def budget_rows(self):
        return self.db.execute(select(func.count()).select_from(Budget)).scalar()


@pytest.fixture
def w(client, db_session):
    world = World(client, db_session)
    world.history()
    return world


# --- create and read ------------------------------------------------------------

def test_a_budget_tracks_this_cycles_spend(w):
    r = w.create("Eating out", 150)
    assert r.status_code == 201, r.text
    created = r.json()
    assert (created["category"], created["limit_pounds"], created["paused"], created["created_via"]) == (
        "Eating out", 150, False, "web")
    body = w.get().json()
    [budget] = body["budgets"]
    assert Decimal(budget["spent"]) == Decimal("40.00")
    assert budget["status"] in ("under_pace", "on_pace", "ahead_of_pace")
    assert Decimal(budget["over_by"]) == 0
    cycle = body["cycle"]
    assert cycle["start"] == (TODAY - timedelta(days=20)).isoformat() and cycle["fallback"] is False
    assert Decimal(body["other_spending"]) == Decimal("200.00")  # Groceries 80 + Shopping 120
    assert Decimal(body["total_spent"]) == Decimal("240.00")
    assert Decimal(body["not_counted"]["commitments"]) == Decimal("950.00")


def test_over_the_limit_says_by_how_much(w):
    w.create("Shopping", 100)
    [budget] = w.get().json()["budgets"]
    assert (budget["status"], Decimal(budget["over_by"])) == ("over", Decimal("20.00"))


def test_the_reconciliation_line_adds_up(w):
    w.create("Eating out", 150)
    rec = w.get().json()["reconciliation"]
    summary = w.client.get(f"{API}/analytics/summary", headers=_bearer(w.web)).json()
    assert Decimal(rec["safe_to_spend"]) == Decimal(summary["safe_to_spend"])
    assert Decimal(rec["budgets_left"]) == Decimal("110.00")
    assert Decimal(rec["headroom"]) == (
        Decimal(rec["safe_to_spend"]) - Decimal(rec["budgets_left"]) - Decimal(rec["other_at_pace"])
    )


def test_no_budgets_no_reconciliation(w):
    assert w.get().json()["reconciliation"] is None


def test_the_limit_is_encrypted_at_rest(w):
    w.create("Eating out", 150)
    raw = w.db.execute(text("SELECT limit_pounds FROM budgets")).scalar()
    assert "150" not in str(raw)


# --- validation (sec: untrusted category, bounds) ---------------------------------

@pytest.mark.parametrize("limit", [0, -5, 100_001, 1.5, "150"])
def test_the_limit_is_a_whole_pound_amount_from_1_to_100000(w, limit):
    assert w.create("Eating out", limit).status_code == 422
    assert w.budget_rows() == 0


@pytest.mark.parametrize("category", ["Holidays", "x" * 101, "Eating‮out", "Eating\x00out", ""])
def test_the_category_must_be_one_of_the_users_own(w, category):
    assert w.create(category, 150).status_code == 422
    assert w.budget_rows() == 0


def test_a_category_that_is_mostly_commitments_cant_have_a_budget(w):
    r = w.create("Rent", 1000)
    assert r.status_code == 422
    assert "commitment" in r.json()["detail"].lower()


def test_one_active_budget_per_category(w):
    assert w.create("Eating out", 150).status_code == 201
    assert w.create("Eating out", 200).status_code == 422


def test_at_most_20_budgets(client, db_session):
    w = World(client, db_session)
    w.history(categories=[f"Cat {i}" for i in range(21)], cycles=1)
    for i in range(20):
        assert w.create(f"Cat {i}", 10).status_code == 201
    assert w.create("Cat 20", 10).status_code == 422


# --- edit, pause, remove -----------------------------------------------------------

def test_patch_changes_the_limit_and_pauses(w):
    budget_id = w.create("Eating out", 150).json()["id"]
    r = w.patch(budget_id, limit_pounds=90)
    assert (r.status_code, r.json()["limit_pounds"]) == (200, 90)
    r = w.patch(budget_id, paused=True)
    assert (r.json()["paused"], r.json()["status"]) == (True, None)
    body = w.get().json()
    assert Decimal(body["other_spending"]) == Decimal("240.00")  # a paused budget's spending is "other"


def test_patch_bounds(w):
    budget_id = w.create("Eating out", 150).json()["id"]
    assert w.patch(budget_id, limit_pounds=0).status_code == 422
    assert w.patch(budget_id, category="Groceries").status_code == 422  # extra fields forbidden


def test_delete_is_soft_and_the_category_can_be_budgeted_again(w):
    budget_id = w.create("Eating out", 150).json()["id"]
    assert w.delete(budget_id).status_code == 204
    assert w.get().json()["budgets"] == []
    assert w.budget_rows() == 1  # kept, inactive, for history
    assert w.create("Eating out", 120).status_code == 201


def test_another_users_budget_is_not_found(client, db_session, w):
    budget_id = w.create("Eating out", 150).json()["id"]
    other = World(client, db_session, email="other@example.com")
    assert w.patch(budget_id, token=other.web, limit_pounds=1).status_code == 404
    assert w.delete(budget_id, token=other.web).status_code == 404
    assert other.get().json()["budgets"] == []
    assert w.get().json()["budgets"][0]["limit_pounds"] == 150


def test_an_unknown_id_is_not_found(w):
    import uuid
    assert w.patch(uuid.uuid4(), limit_pounds=10).status_code == 404


def test_the_routes_are_web_only(client, db_session):
    w = World(client, db_session, email="mcp@example.com")
    _, _, tokens = _connect(client, scopes=(READ,), email="mcp@example.com")
    assert w.get(token=tokens["access_token"]).status_code == 401


# --- bulk PUT: all or nothing --------------------------------------------------------

def test_put_creates_and_updates_and_leaves_others_alone(w):
    shopping_id = w.create("Shopping", 200).json()["id"]
    eating_id = w.create("Eating out", 150).json()["id"]
    r = w.put([{"category": "Eating out", "limit_pounds": 120}, {"category": "Groceries", "limit_pounds": 300}])
    assert r.status_code == 200, r.text
    limits = {b["category"]: (b["id"], b["limit_pounds"]) for b in r.json()["budgets"]}
    assert limits == {"Eating out": (eating_id, 120), "Groceries": (limits["Groceries"][0], 300),
                      "Shopping": (shopping_id, 200)}


@pytest.mark.parametrize("bad_last", [
    {"category": "Holidays", "limit_pounds": 50},             # not the user's category
    {"category": "Rent", "limit_pounds": 50},                 # commitment-covered
    {"category": "Groceries", "limit_pounds": 0},             # bounds
    {"category": "Eating out", "limit_pounds": 99},           # duplicate in one request
])
def test_put_writes_nothing_when_any_entry_is_invalid(w, bad_last):
    w.create("Shopping", 200)
    before = w.get().json()["budgets"]
    rows = w.budget_rows()
    r = w.put([{"category": "Eating out", "limit_pounds": 120}, {"category": "Shopping", "limit_pounds": 10}, bad_last])
    assert r.status_code == 422
    assert w.budget_rows() == rows
    assert w.get().json()["budgets"] == before


def test_put_counts_the_20_cap_after_the_change(client, db_session):
    w = World(client, db_session)
    w.history(categories=[f"Cat {i}" for i in range(21)], cycles=1)
    for i in range(19):
        w.create(f"Cat {i}", 10)
    assert w.put([{"category": "Cat 19", "limit_pounds": 10}, {"category": "Cat 20", "limit_pounds": 10}]).status_code == 422
    assert w.put([{"category": "Cat 0", "limit_pounds": 20}, {"category": "Cat 19", "limit_pounds": 10}]).status_code == 200


# --- suggest: dry ----------------------------------------------------------------------

def test_suggest_is_the_median_of_the_last_3_cycles_rounded_up_to_10(w):
    r = w.suggest()
    assert r.status_code == 200, r.text
    body = r.json()
    by_cat = {s["category"]: s for s in body["suggestions"]}
    # Eating out: 55, 50, 45 in the last three complete cycles (oldest first) -> median 50.
    assert [Decimal(c["spent"]) for c in by_cat["Eating out"]["last_cycles"]] == [
        Decimal("55.00"), Decimal("50.00"), Decimal("45.00")]
    assert by_cat["Eating out"]["suggested_limit"] == 50
    # Groceries: 85, 90, 95 -> 90.
    assert by_cat["Groceries"]["suggested_limit"] == 90
    assert "Rent" in body["commitment_covered"] and "Rent" not in by_cat


def test_suggest_rounds_the_median_up_to_10(w):
    def more_books():
        for back, amount in ((1, "41.00"), (2, "47.00"), (3, "52.00")):
            _tx(w.db, w.current, amount, TODAY - timedelta(days=5 + 30 * back), merchant="Books", category="Books")
        w.db.commit()
    w.as_user(more_books)
    by_cat = {s["category"]: s for s in w.suggest().json()["suggestions"]}
    assert by_cat["Books"]["suggested_limit"] == 50  # median 47 -> 50


def test_suggest_says_when_there_isnt_enough_history(client, db_session):
    w = World(client, db_session)
    w.history(cycles=1)
    by_cat = {s["category"]: s for s in w.suggest().json()["suggestions"]}
    assert by_cat["Eating out"]["suggested_limit"] is None
    assert by_cat["Eating out"]["reason"] == "not_enough_history"


def test_suggest_shows_the_current_limit_for_the_diff(w):
    w.create("Eating out", 150)
    by_cat = {s["category"]: s for s in w.suggest().json()["suggestions"]}
    assert by_cat["Eating out"]["current_limit"] == 150


def test_suggest_writes_nothing(w):
    counts = lambda: {t: w.db.execute(text(f"SELECT count(*) FROM {t}")).scalar()  # noqa: E731
                      for t in ("budgets", "audit_entries", "transactions", "commitment_rules")}
    before = counts()
    assert w.suggest().status_code == 200
    assert counts() == before


# --- logs (sec: only the caller's own ids) ------------------------------------------------

def test_logs_carry_no_category_or_limit(w, caplog):
    with caplog.at_level(logging.DEBUG):
        w.create("Eating out", 137)
        w.get()
        w.suggest()
    text_ = "\n".join(r.getMessage() for r in caplog.records)
    assert "Eating out" not in text_ and "137" not in text_


def test_a_partial_oldest_cycle_is_not_enough_history(client, db_session):
    """eng-a on #150: transactions starting partway into the oldest of the
    three cycles would pull the median down, so no suggestion yet."""
    w = World(client, db_session)
    w.history(cycles=4)  # the 4th month back is only partly inside the oldest cycle
    by_cat = {s["category"]: s for s in w.suggest().json()["suggestions"]}
    assert by_cat["Eating out"]["reason"] == "not_enough_history"


def test_suggest_offers_at_most_8_categories(client, db_session):
    w = World(client, db_session)
    w.history(categories=[f"Cat {i}" for i in range(10)], cycles=5)
    body = w.suggest().json()
    assert len(body["suggestions"]) == 8
    assert {"Cat 0", "Cat 1"}.isdisjoint({s["category"] for s in body["suggestions"]})  # the smallest two


def test_no_payday_no_reconciliation(client, db_session):
    from app.models import CommitmentRule

    w = World(client, db_session)
    w.history()

    def drop_payday():
        w.db.query(CommitmentRule).filter(CommitmentRule.direction == "income").delete()
        w.db.commit()
    w.as_user(drop_payday)
    w.create("Eating out", 150)
    body = w.get().json()
    assert body["cycle"]["fallback"] is True and body["reconciliation"] is None
