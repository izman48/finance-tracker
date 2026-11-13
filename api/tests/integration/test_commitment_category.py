"""A commitment's category (T-24-2): the category of the most recent payment
`classify_purchase` matches to it, or None when nothing matched.

Budgets count a commitment's payments in their own category (T-24-3); this
says which category a commitment's still-to-come instalments belong to, and
what the Commitments list and Claude show. It reuses the one matching
predicate (`classify_purchase`), reads the user's own transactions only, and
looks back a bounded window in one pass.
"""
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import event

from app.models import CommitmentRule
from app.services.commitment_category import WINDOW_DAYS, commitment_categories
from tests.clock import TODAY
from tests.integration.test_budget_spend import World
from tests.integration.test_transactions_endpoint import _account, _tx

API = "/api/v1"


def _rule(w, label, amount="16.00"):
    rule = CommitmentRule(user_id=w.user.id, direction="expense", label=label, amount=Decimal(amount),
                          cadence="weekly", next_date=TODAY + timedelta(days=3),
                          source="manual", status="confirmed")
    w.db.add(rule)
    w.db.commit()
    return rule


def _categories(w):
    def read():
        rules = w.db.query(CommitmentRule).filter(CommitmentRule.user_id == w.user.id).all()
        return commitment_categories(w.db, w.user, rules)
    return w.as_user(read)


def _seed(w, payments, label="MEAL KIT CO"):
    """payments: (days ago, category) for each payment to `label`. Returns
    (rule id, account)."""
    def make():
        current = _account(w.db, w.user.id, name="Current")
        for days_ago, category in payments:
            _tx(w.db, current, "16.00", TODAY - timedelta(days=days_ago), merchant=label, category=category)
        return _rule(w, label).id, current
    return w.as_user(make)


def test_the_most_recent_matched_payments_category_wins(client, db_session):
    w = World(client, db_session)
    rule_id, _ = _seed(w, [(21, "Groceries"), (14, "Groceries"), (7, "Eating out")])
    assert _categories(w) == {rule_id: "Eating out"}


def test_a_commitment_with_no_matched_payment_has_no_category(client, db_session):
    w = World(client, db_session)
    rule_id, current = _seed(w, [])
    w.as_user(lambda: _tx(w.db, current, "16.00", TODAY - timedelta(days=2),
                          merchant="CORNER CAFE", category="Eating out"))
    assert _categories(w) == {rule_id: None}


def test_a_one_off_under_the_same_descriptor_never_lends_its_category(client, db_session):
    """Should not match (T-25-1): a large purchase billed under the
    subscription's descriptor is not its payment, however recent."""
    w = World(client, db_session)
    rule_id, current = _seed(w, [(9, "Entertainment")], label="STREAMCO.COM/UK LONDON")
    w.as_user(lambda: _tx(w.db, current, "1499.00", TODAY - timedelta(days=1),
                          merchant="STREAMCO.COM/UK LONDON", category="Shopping"))
    assert _categories(w) == {rule_id: "Entertainment"}


def test_a_payment_with_a_changing_reference_still_matches(client, db_session):
    """Should match: the bank's per-payment reference is not part of the key."""
    w = World(client, db_session)
    rule_id, current = _seed(w, [], label="GYM CLUB REF 1234567")
    w.as_user(lambda: _tx(w.db, current, "16.00", TODAY - timedelta(days=3),
                          merchant="GYM CLUB REF 7654321", category="Health"))
    assert _categories(w) == {rule_id: "Health"}


def test_a_different_merchant_never_lends_its_category(client, db_session):
    """Should NOT match: a similar but different payee, even if more recent."""
    w = World(client, db_session)
    rule_id, current = _seed(w, [(10, "Eating out")])
    w.as_user(lambda: _tx(w.db, current, "16.00", TODAY - timedelta(days=1),
                          merchant="MEAL KIT CO MARKET", category="Shopping"))
    assert _categories(w) == {rule_id: "Eating out"}


def test_a_payment_classify_purchase_calls_a_transfer_is_not_a_match(client, db_session):
    """The one predicate decides: a same-key payment the user marked as a
    transfer is not this commitment's payment."""
    w = World(client, db_session)
    rule_id, current = _seed(w, [(10, "Eating out")])

    def transfer():
        tx = _tx(w.db, current, "16.00", TODAY - timedelta(days=1), merchant="MEAL KIT CO", category="Savings")
        tx.counts_as_override = "transfer"
        w.db.commit()
    w.as_user(transfer)
    assert _categories(w) == {rule_id: "Eating out"}


def test_payments_older_than_the_window_are_not_read(client, db_session):
    w = World(client, db_session)
    rule_id, _ = _seed(w, [(WINDOW_DAYS + 5, "Eating out")])
    assert WINDOW_DAYS <= 400
    assert _categories(w) == {rule_id: None}


def test_the_category_is_returned_exactly_as_stored(client, db_session):
    """Exact text: no trimming or case folding of hidden characters (sec)."""
    w = World(client, db_session)
    stored = " eating OUT​"
    rule_id, _ = _seed(w, [(3, stored)])
    assert _categories(w) == {rule_id: stored}


def test_another_users_payments_never_set_the_category(client, db_session):
    a = World(client, db_session, email="a@example.com")
    rule_id, _ = _seed(a, [(10, "Eating out")])
    b = World(client, db_session, email="b@example.com")
    _seed(b, [(1, "Shopping")])
    assert _categories(a) == {rule_id: "Eating out"}


def _select_count(w, engine):
    statements: list[str] = []

    def capture(conn, cursor, statement, params, context, executemany):
        statements.append(statement)
    event.listen(engine, "before_cursor_execute", capture)
    try:
        _categories(w)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    return len([s for s in statements if s.lstrip().upper().startswith("SELECT")])


def test_the_query_count_does_not_grow_with_commitments(client, db_session):
    w = World(client, db_session)
    _seed(w, [(5, "Eating out")])
    engine = db_session.get_bind()
    one = _select_count(w, engine)
    for n in range(4):
        _seed(w, [(4, "Bills")], label=f"UTILITY {chr(65 + n)}")
    assert _select_count(w, engine) == one


def test_the_commitments_endpoint_returns_the_category(client, db_session):
    w = World(client, db_session)
    rule_id, _ = _seed(w, [(7, "Eating out")])
    db_session.expire_all()
    rows = client.get(f"{API}/analytics/commitments", headers=w.headers).json()
    assert {r["id"]: r["category"] for r in rows} == {str(rule_id): "Eating out"}
