"""Server-side bounds on the web's transaction, commitment and planned-item
writes (T-12-12; sec: lengths, enums and amounts with 422 tests, labels free
of hidden and control characters as on the Claude path). Also: clearing a
category forgets the learned rule (the UI sends null). Synthetic figures.
"""
from datetime import timedelta

import pytest

from app.core import user_crypto
from app.models import CategoryRule, Transaction
from tests.clock import TODAY
from tests.integration.test_transactions_endpoint import _account, _setup, _tx

API = "/api/v1"
SOON = (TODAY + timedelta(days=5)).isoformat()
HIDDEN = "Rent\u202e"  # a bidi override


@pytest.fixture
def web(client, db_session):
    user, ctx = _setup(client, db_session)
    acc = _account(db_session, user.id)
    tx = _tx(db_session, acc, "12.00", TODAY - timedelta(days=2), merchant="Corner Cafe")
    yield client, db_session, tx
    user_crypto.current_dek.reset(ctx)


# --- transactions ---------------------------------------------------------------

@pytest.mark.parametrize("body", [
    {"category": "x" * 101},
    {"subcategory": "x" * 101},
    {"category": HIDDEN},
    {"category": "Food\x00"},
    {"counts_as": "gift"},
])
def test_a_bad_transaction_edit_is_422_and_changes_nothing(web, body):
    client, db, tx = web
    res = client.patch(f"{API}/banking/transactions/{tx.id}", json=body)
    assert res.status_code == 422, res.text
    db.expire_all()
    assert db.get(Transaction, tx.id).category is None


def test_a_category_at_the_limit_is_accepted(web):
    client, _, tx = web
    assert client.patch(f"{API}/banking/transactions/{tx.id}", json={"category": "x" * 100}).status_code == 200


def test_clearing_a_category_forgets_the_learned_rule(web):
    client, db, tx = web
    assert client.patch(f"{API}/banking/transactions/{tx.id}", json={"category": "Eating out"}).status_code == 200
    assert db.query(CategoryRule).filter(CategoryRule.source == "learned").count() == 1
    res = client.patch(f"{API}/banking/transactions/{tx.id}", json={"category": None})
    assert res.status_code == 200, res.text
    assert res.json()["category"] is None
    assert db.query(CategoryRule).filter(CategoryRule.source == "learned").count() == 0


def test_a_subcategory_alone_leaves_the_category_alone(web):
    client, _, tx = web
    client.patch(f"{API}/banking/transactions/{tx.id}", json={"category": "Eating out"})
    res = client.patch(f"{API}/banking/transactions/{tx.id}", json={"subcategory": "Coffee"})
    assert res.json()["category"] == "Eating out"


# --- commitments ----------------------------------------------------------------

GOOD_COMMITMENT = {"direction": "expense", "label": "Gym", "amount": "32.00", "cadence": "monthly", "next_date": SOON}


@pytest.mark.parametrize("change", [
    {"direction": "sideways"},
    {"label": ""},
    {"label": "x" * 101},
    {"label": HIDDEN},
    {"amount": "0"},
    {"amount": "-5.00"},
    {"amount": "1000000.01"},
    {"amount": "12.345"},
    {"cadence": "fortnightly"},
    {"cadence": "custom_days", "interval_days": 0},
    {"cadence": "every_n_months", "interval_months": 25},
    {"match_merchant": "x" * 201},
    {"match_merchant": "Gym\u200b"},
])
def test_a_bad_new_commitment_is_422(web, change):
    client, _, _ = web
    res = client.post(f"{API}/analytics/commitments", json={**GOOD_COMMITMENT, **change})
    assert res.status_code == 422, res.text


def test_a_good_commitment_is_still_accepted(web):
    client, _, _ = web
    assert client.post(f"{API}/analytics/commitments", json=GOOD_COMMITMENT).status_code == 201


@pytest.mark.parametrize("change", [
    {"status": "archived"},
    {"label": HIDDEN},
    {"amount": "0"},
    {"cadence": "yearly"},
])
def test_a_bad_commitment_edit_is_422(web, change):
    client, _, _ = web
    cid = client.post(f"{API}/analytics/commitments", json=GOOD_COMMITMENT).json()["id"]
    res = client.patch(f"{API}/analytics/commitments/{cid}", json=change)
    assert res.status_code == 422, res.text


def test_clearing_the_match_key_with_an_empty_string_still_works(web):
    client, _, _ = web
    cid = client.post(f"{API}/analytics/commitments", json={**GOOD_COMMITMENT, "match_merchant": "GYM LTD"}).json()["id"]
    assert client.patch(f"{API}/analytics/commitments/{cid}", json={"match_merchant": ""}).status_code == 200


# --- planned items --------------------------------------------------------------

GOOD_PLANNED = {"name": "Car insurance", "direction": "expense", "kind": "one_off", "start_date": SOON, "amount": "200.00"}


@pytest.mark.parametrize("change", [
    {"name": ""},
    {"name": "x" * 101},
    {"name": HIDDEN},
    {"direction": "both"},
    {"kind": "lottery"},
    {"amount": "0"},
    {"amount": "1000000.01"},
    {"kind": "recurring", "cadence": "hourly"},
    {"kind": "installment_plan", "amount": None, "total_amount": "-1.00", "installments": 3},
    {"kind": "installment_plan", "amount": None, "total_amount": "300.00", "installments": 3, "apr": "101"},
    {"kind": "installment_plan", "amount": None, "total_amount": "300.00", "installments": 3, "fee_amount": "-1"},
])
def test_a_bad_planned_item_is_422(web, change):
    client, _, _ = web
    res = client.post(f"{API}/analytics/planned-items", json={**GOOD_PLANNED, **change})
    assert res.status_code == 422, res.text


def test_a_good_planned_item_is_still_accepted(web):
    client, _, _ = web
    assert client.post(f"{API}/analytics/planned-items", json=GOOD_PLANNED).status_code == 201


def test_an_unchanged_bank_label_is_never_refused_on_edit(web):
    """A detected commitment's label comes from bank text, which can be long
    or hold a tab. The edit form sends the label back with every save, so an
    unchanged label is let through; only a new label must be visible text."""
    from app.models import CommitmentRule, User
    client, db, _ = web
    bank_label = "DIRECT DEBIT\tGYM " + "X" * 110
    user = db.query(User).first()
    rule = CommitmentRule(user_id=user.id, direction="expense", label=bank_label, amount=32, cadence="monthly",
                          next_date=TODAY + timedelta(days=5), source="detected", status="confirmed")
    db.add(rule)
    db.commit()
    res = client.patch(f"{API}/analytics/commitments/{rule.id}", json={"label": bank_label, "amount": "40.00"})
    assert res.status_code == 200, res.text
    assert client.patch(f"{API}/analytics/commitments/{rule.id}", json={"label": bank_label + "!"}).status_code == 422


def test_an_unchanged_amount_above_the_cap_still_saves_on_edit(web):
    """sec-1 on #245: a commitment stored above £1,000,000 before the cap
    existed must still save from the edit form (which sends the amount back)
    when the amount isn't changed; a changed amount is held to the cap."""
    from decimal import Decimal
    from app.models import CommitmentRule, User
    client, db, _ = web
    user = db.query(User).first()
    rule = CommitmentRule(user_id=user.id, direction="expense", label="Big", amount=Decimal("1500000.00"),
                          cadence="monthly", next_date=TODAY + timedelta(days=5), source="manual", status="confirmed")
    db.add(rule)
    db.commit()
    res = client.patch(f"{API}/analytics/commitments/{rule.id}", json={"amount": 1500000, "label": "Big one"})
    assert res.status_code == 200, res.text
    assert client.patch(f"{API}/analytics/commitments/{rule.id}", json={"amount": "1500000.01"}).status_code == 422
    assert client.patch(f"{API}/analytics/commitments/{rule.id}", json={"amount": "999.999"}).status_code == 422


def test_unchanged_intervals_outside_the_bounds_still_save(web):
    """eng-b on #245: intervals come back unchanged from the edit form too."""
    from app.models import CommitmentRule, User
    client, db, _ = web
    user = db.query(User).first()
    rule = CommitmentRule(user_id=user.id, direction="expense", label="Rare", amount=50, cadence="custom_days",
                          interval_days=400, next_date=TODAY + timedelta(days=5), source="detected", status="confirmed")
    db.add(rule)
    db.commit()
    assert client.patch(f"{API}/analytics/commitments/{rule.id}", json={"interval_days": 400, "amount": "60.00"}).status_code == 200
    assert client.patch(f"{API}/analytics/commitments/{rule.id}", json={"interval_days": 401}).status_code == 422
