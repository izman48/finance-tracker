"""Card instalment plans (T-12-5a; ADR-002 holding kind `card_plan`; sec T-12-5).

A plan (Amex Plan It, Monzo Flex) is a purchase repaid in fixed monthly
instalments plus a fee, inside a credit card. Its terms are entered by hand
and DEK-encrypted; the remaining instalments and balance are worked out on
read. Owner D4 (2026-10-15): while the plan has its card, it is never added
to net worth or Total owed on its own (the card's synced balance holds it,
or, for a provider not yet confirmed to include it, it is hidden until
confirmed, with a caveat). A provider is confirmed only by the code list.
If the card goes (bank disconnect), the plan stays as standalone debt and
counts. Every route is web only and loads by id and user (404 otherwise).

Synthetic figures only.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.core import user_crypto
from app.models import AccountSetting, CardPlan, User
from app.routers import card_plans as card_plans_router
from app.services import card_plans as service
from app.services.analytics.common import _add_months
from tests.clock import TODAY
from tests.integration.test_oauth import _bearer, _web_login
from tests.integration.test_transactions_endpoint import _account, _dek_from_token

API = "/api/v1"
NEXT = TODAY + timedelta(days=12)


class World:
    def __init__(self, client, db, email="plans@example.com"):
        self.client, self.db = client, db
        self.token = _web_login(client, email)
        self.h = _bearer(self.token)
        self.dek = _dek_from_token(self.token)
        self.user = db.query(User).filter(User.email == email).one()
        self.card_id = self.as_user(lambda: self._account("CREDIT_CARD", "Test Card", "640.00", "credit", "Test Bank"))
        self.current_id = self.as_user(lambda: self._account("TRANSACTION", "Test Current", "2000.00", "spending", "Test Bank"))

    def as_user(self, fn):
        token = user_crypto.current_dek.set(self.dek)
        try:
            return fn()
        finally:
            user_crypto.current_dek.reset(token)

    def _account(self, atype, name, balance, role, provider):
        acc = _account(self.db, self.user.id, atype=atype, name=name, balance=balance)
        acc.provider_name = provider
        self.db.add(AccountSetting(user_id=self.user.id, account_id=acc.id, role=role))
        self.db.commit()
        return acc.id

    def plan(self, **over):
        body = {"card_account_id": str(self.card_id), "name": "Test Plan", "balance": "600.00",
                "instalment": "100.00", "fee": "2.50", "instalments_remaining": 6,
                "next_date": NEXT.isoformat(), **over}
        return self.client.post(f"{API}/card-plans", json=body, headers=self.h)

    def summary(self):
        return self.client.get(f"{API}/analytics/summary", headers=self.h).json()


@pytest.fixture
def world(client, db_session):
    return World(client, db_session)


def test_adding_a_plan_returns_its_terms_and_read_time_figures(world):
    res = world.plan()
    assert res.status_code == 201, res.text
    body = res.json()
    assert set(body) == {
        "id", "card_account_id", "card_name", "name", "balance", "instalment", "fee", "instalments_remaining",
        "next_date", "final_date", "monthly_total", "in_net_worth", "provider_confirmed",
    }
    assert body["card_name"] == "Test Card"
    assert (body["monthly_total"], body["final_date"]) == ("102.50", _add_months(NEXT, 5).isoformat())
    assert (body["in_net_worth"], body["provider_confirmed"]) == (False, False)
    assert [p["id"] for p in world.client.get(f"{API}/card-plans", headers=world.h).json()] == [body["id"]]


def test_the_name_and_amounts_are_encrypted_at_rest(world):
    world.plan()
    row = world.db.execute(text("SELECT name, balance, instalment, fee FROM card_plans")).one()
    assert all(b"Test Plan" not in bytes(str(v), "utf8") and str(v) not in {"600.00", "100.00", "2.50"} for v in row)


def test_past_instalments_come_off_on_read(world):
    plan = world.plan(next_date=(TODAY - timedelta(days=40)).isoformat(), instalments_remaining=6).json()
    # Two instalment dates have passed (about 40 and 10 days ago).
    assert plan["instalments_remaining"] == 4
    assert plan["balance"] == "400.00"


# --- net worth and Total owed (owner D4) -------------------------------------

def test_a_plan_with_its_card_never_adds_to_net_worth_or_total_owed(world):
    before = world.summary()
    assert world.plan().status_code == 201
    after = world.summary()
    for key in ("net_worth", "total_owed", "liabilities_total"):
        assert Decimal(str(after[key])) == Decimal(str(before[key])), key


def test_a_confirmed_provider_is_marked_only_by_the_code_list(world, monkeypatch):
    monkeypatch.setattr(service, "PLAN_IN_CARD_BALANCE", frozenset({"TEST BANK"}))
    body = world.plan().json()
    assert (body["in_net_worth"], body["provider_confirmed"]) == (False, True)


def test_when_the_card_goes_the_plan_stays_as_debt_and_counts(world, db_session):
    plan_id = world.plan().json()["id"]
    before = world.summary()
    connection = db_session.connection()
    connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    try:
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
        db_session.execute(text("DELETE FROM account_settings WHERE account_id = :a"), {"a": world.card_id.hex})
        db_session.execute(text("DELETE FROM accounts WHERE id = :a"), {"a": world.card_id.hex})
        db_session.commit()
        plans = world.client.get(f"{API}/card-plans", headers=world.h).json()
        assert [(p["id"], p["card_account_id"], p["in_net_worth"]) for p in plans] == [(plan_id, None, True)]
        after = world.summary()
        # The card's £640 leaves; the plan's £600 is now owed on its own.
        assert Decimal(str(after["liabilities_total"])) - Decimal(str(before["liabilities_total"])) == Decimal("600.00")
    finally:
        db_session.rollback()
        db_session.connection().exec_driver_sql("PRAGMA foreign_keys=OFF")


# --- input, ownership and bounds (sec T-12-5) --------------------------------

@pytest.mark.parametrize("field,value", [
    ("balance", "10000000.01"), ("balance", "-1"), ("instalment", "0"), ("fee", "100.01"), ("fee", "-0.01"),
    ("instalments_remaining", 0), ("instalments_remaining", 121), ("apr", "100.01"), ("name", ""),
])
def test_out_of_bounds_input_is_422_and_writes_nothing(world, field, value):
    assert world.plan(**{field: value}).status_code == 422
    assert world.db.query(CardPlan).count() == 0


def test_server_fields_are_refused(world):
    assert world.plan(user_id=str(world.user.id)).status_code == 422
    assert world.plan(in_net_worth=True).status_code == 422


def test_only_a_credit_card_can_hold_a_plan(world):
    res = world.plan(card_account_id=str(world.current_id))
    assert res.status_code == 422
    assert world.db.query(CardPlan).count() == 0


def test_another_users_card_or_plan_is_404_and_nothing_is_written(client, db_session):
    alice = World(client, db_session, "plan-alice@example.com")
    plan_id = alice.plan().json()["id"]
    bob = World(client, db_session, "plan-bob@example.com")
    assert bob.plan(card_account_id=str(alice.card_id)).status_code == 404
    assert bob.client.patch(f"{API}/card-plans/{plan_id}", json={"fee": "0"}, headers=bob.h).status_code == 404
    assert bob.client.delete(f"{API}/card-plans/{plan_id}", headers=bob.h).status_code == 404
    assert [p["id"] for p in bob.client.get(f"{API}/card-plans", headers=bob.h).json()] == []
    assert alice.client.get(f"{API}/card-plans", headers=alice.h).json()[0]["fee"] == "2.50"


def test_plans_per_card_are_capped(world, monkeypatch):
    monkeypatch.setattr(card_plans_router, "PLANS_PER_CARD_MAX", 2)
    assert [world.plan().status_code for _ in range(2)] == [201, 201]
    res = world.plan()
    assert res.status_code == 409
    assert world.db.query(CardPlan).count() == 2


def test_editing_and_deleting_a_plan(world):
    plan_id = world.plan().json()["id"]
    res = world.client.patch(f"{API}/card-plans/{plan_id}", json={"fee": "0.00", "instalments_remaining": 3},
                             headers=world.h)
    assert res.status_code == 200
    assert (res.json()["fee"], res.json()["instalments_remaining"]) == ("0.00", 3)
    assert world.client.delete(f"{API}/card-plans/{plan_id}", headers=world.h).status_code == 204
    assert world.client.get(f"{API}/card-plans", headers=world.h).json() == []


def test_the_projection_follows_the_same_rule(world, db_session):
    """Inside its card a plan adds nothing to the projection; once standalone
    it is owed and falls by its instalments, from the same figure as today."""
    def liabilities():
        p = world.client.get(f"{API}/analytics/net-worth-projection",
                             params={"monthly_contribution": "0", "annual_growth_pct": "0"}, headers=world.h).json()
        return [Decimal(str(pt["liabilities"])) for pt in p["timeline"][:9]]

    before = liabilities()
    world.plan()
    assert liabilities() == before
    world.db.query(CardPlan).update({CardPlan.card_account_id: None})
    world.db.commit()
    after = liabilities()
    assert after[0] - before[0] == Decimal("600.00")
    # Six instalments of £100 from 12 days ahead: owed falls £100 a month to £0.
    assert [a - b for a, b in zip(after, before)][1:8] == [Decimal(x) for x in ("500", "400", "300", "200", "100", "0", "0")]
