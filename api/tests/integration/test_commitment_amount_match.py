"""A one-off purchase under a commitment's descriptor is spending (T-19-1).

A merchant bills its subscription and its one-off purchases under one
descriptor. Each surface must tag and exclude only the payments within
max(25%, GBP 5) of the commitment's amount; the one-offs count as spending.
Synthetic merchant and amounts (public repo).
"""
from datetime import timedelta
from decimal import Decimal

import pytest

from app.core import user_crypto
from app.models import CommitmentRule, User
from app.services import analytics_service as svc
from app.services.budget_spend import budget_spend
from tests.clock import TODAY
from tests.integration.test_transactions_endpoint import _account, _dek_from_token, _login, _register, _tx

API = "/api/v1/banking"
EMAIL = "oneoff@example.com"
DESCRIPTOR = "STREAMCO.COM/UK LONDON"
DAY = TODAY - timedelta(days=2)
START = TODAY - timedelta(days=10)


class World:
    def __init__(self, client, db):
        self.client, self.db = client, db
        _register(client, email=EMAIL)
        self.token = _login(client, email=EMAIL)
        self.dek = _dek_from_token(self.token)
        self.user = db.query(User).filter(User.email == EMAIL).one()
        self.as_user(self._seed)

    def as_user(self, fn):
        token = user_crypto.current_dek.set(self.dek)
        try:
            return fn()
        finally:
            user_crypto.current_dek.reset(token)

    def _seed(self):
        db, uid = self.db, self.user.id
        current = _account(db, uid, name="Current", balance="3000")
        card = _account(db, uid, atype="CREDIT_CARD", name="Card", balance="0")
        _tx(db, current, "9.99", DAY, merchant=DESCRIPTOR, category="Entertainment")     # the subscription
        _tx(db, current, "10.49", DAY, merchant=DESCRIPTOR, category="Entertainment")    # after a price rise
        _tx(db, current, "1499.00", DAY, merchant=DESCRIPTOR, category="Shopping")       # one-off, cash
        _tx(db, card, "649.00", DAY, merchant=DESCRIPTOR, category="Shopping")           # one-off, on the card
        db.add(CommitmentRule(
            user_id=uid, direction="expense", label="StreamCo", amount=Decimal("9.99"),
            match_key="expense:streamco com/uk london", cadence="monthly",
            next_date=TODAY + timedelta(days=20), source="detected", status="confirmed",
        ))
        db.commit()

    def get(self, path, **params):
        res = self.client.get(f"{API}{path}", params=params, headers={"Authorization": f"Bearer {self.token}"})
        assert res.status_code == 200, res.text
        return res.json()

    def spending(self, **kw):
        user = self.db.get(User, self.user.id)
        return self.as_user(lambda: svc.get_spending(
            self.db, user, period="custom", frm=START, to=TODAY, exclude_commitments=True, **kw,
        ))


@pytest.fixture
def world(client, db_session):
    return World(client, db_session)


def _tags(items):
    return {Decimal(str(i["amount"])): i["is_commitment"] for i in items}


EXPECTED_TAGS = {
    Decimal("9.99"): True, Decimal("10.49"): True,
    Decimal("1499.00"): False, Decimal("649.00"): False,
}


def test_the_transactions_list_tags_only_payments_near_the_commitment_amount(world):
    assert _tags(world.get("/transactions")["items"]) == EXPECTED_TAGS


def test_excluding_commitments_from_the_list_keeps_the_one_offs(world):
    items = world.get("/transactions", exclude_commitments="true")["items"]
    assert sorted(Decimal(str(i["amount"])) for i in items) == [Decimal("649.00"), Decimal("1499.00")]


def test_search_tags_only_payments_near_the_commitment_amount(world):
    res = world.client.post(
        f"{API}/transactions/search", json={"query": "streamco"},
        headers={"Authorization": f"Bearer {world.token}"},
    )
    assert res.status_code == 200, res.text
    assert _tags(res.json()["items"]) == EXPECTED_TAGS


def test_one_offs_count_as_purchases_and_the_subscription_does_not(world):
    s = world.spending(lens="purchases")
    assert s["paid_from_cash"] == Decimal("1499.00")
    assert s["charged_to_credit"] == Decimal("649.00")


def test_one_off_paid_from_the_bank_counts_in_money_out(world):
    assert world.spending(lens="money_out")["total_spent"] == Decimal("1499.00")


def test_money_out_composition_files_only_the_subscription_as_commitments(world):
    user = world.db.get(User, world.user.id)
    s = world.as_user(lambda: svc.get_spending(world.db, user, period="custom", frm=START, to=TODAY))
    assert s["composition"]["commitments"] == Decimal("20.48")
    assert s["composition"]["other"] == Decimal("1499.00")


def test_the_spending_drill_down_lists_the_one_offs(world):
    user = world.db.get(User, world.user.id)
    rows = world.as_user(lambda: svc.spending_transactions(
        world.db, user, period="custom", frm=START, to=TODAY, exclude_commitments=True,
    ))
    assert sorted((r["amount"], r["kind"]) for r in rows) == [
        (Decimal("649.00"), "credit"), (Decimal("1499.00"), "cash"),
    ]


def test_one_offs_count_in_budget_spend_and_the_subscription_is_excluded(world):
    user = world.db.get(User, world.user.id)
    spend = world.as_user(lambda: budget_spend(world.db, user, START, TODAY))
    assert spend.by_category == {"Shopping": Decimal("2148.00")}
    assert spend.excluded["commitments"] == Decimal("20.48")
