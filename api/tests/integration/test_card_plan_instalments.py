"""A card plan's instalment and fee leave the bank (T-12-5b; owner D3/D4; sec T-12-5).

The instalment plus fee goes into what the card will take each month: on the
card's next pay day on or after the instalment date when the card has a pay
day, else on the instalment date itself. It counts in the Cashflow forecast,
safe-to-spend and Coming up whatever the provider's verification status, and
even after the card has gone. It is never a commitment, and a commitment
tied to the card never drops it (counted alongside, the safe side). Past
instalments are in the card's statement or unbilled spend already, so they
are never added again. Synthetic figures.
"""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.models import AccountSetting, CardPlan, CommitmentRule
from app.services.analytics.common import _add_months
from tests.clock import TODAY
from tests.integration.test_card_plans_api import NEXT, World, API
from tests.integration.test_oauth import READ, _bearer, _connect

LABEL = "Test Plan instalment"


def _forecast(world, horizon="90"):
    return world.client.get(f"{API}/analytics/forecast", params={"horizon": horizon}, headers=world.h).json()


def _plan_events(world, horizon="90"):
    return [(day["date"], e["amount"]) for day in _forecast(world, horizon)["timeline"] for e in day["events"]
            if e["label"] == LABEL]


def _payday(world, days=40):
    world.as_user(lambda: (world.db.add(CommitmentRule(
        user_id=world.user.id, direction="income", label="Salary", amount=Decimal("2000"), cadence="monthly",
        next_date=TODAY + timedelta(days=days), source="manual", status="confirmed", is_payday=True,
    )), world.db.commit()))


def test_with_no_pay_day_each_instalment_leaves_on_its_own_date(client, db_session):
    world = World(client, db_session)
    world.plan(instalments_remaining=3)
    assert _plan_events(world) == [(_add_months(NEXT, n).isoformat(), "-102.50") for n in range(3)]


def test_safe_to_spend_falls_by_the_instalment_before_payday(client, db_session):
    world = World(client, db_session)
    _payday(world, days=40)
    before = world.summary()
    world.plan(instalments_remaining=3)
    after = world.summary()
    # Two instalments (12 and ~42 days out): only the first is before payday.
    assert Decimal(str(before["safe_to_spend"])) - Decimal(str(after["safe_to_spend"])) == Decimal("102.50")


def test_an_unconfirmed_providers_plan_still_counts_in_cash(client, db_session):
    # Hidden from net worth (D4), never from what leaves the bank (sec b).
    world = World(client, db_session)
    body = world.plan().json()
    assert body["provider_confirmed"] is False and body["in_net_worth"] is False
    assert _plan_events(world)[0] == (NEXT.isoformat(), "-102.50")


# eng-a on #233: a statement-strategy card too.
@pytest.mark.parametrize("strategy", ["full_balance", "statement_balance"])
def test_on_a_card_with_a_pay_day_it_joins_the_next_payment(client, db_session, strategy):
    world = World(client, db_session)
    pay_day = (NEXT + timedelta(days=3)).day
    if pay_day > 28:
        pay_day = 28
    world.as_user(lambda: _set_pay_day(world, pay_day, strategy))
    world.plan(instalments_remaining=1)
    (when, amount), = _plan_events(world)
    due = date.fromisoformat(when)
    assert amount == "-102.50"
    assert due >= NEXT and due.day == pay_day and (due - NEXT).days < 32


def _set_pay_day(world, day, strategy="full_balance"):
    s = world.db.query(AccountSetting).filter(AccountSetting.account_id == world.card_id).one()
    s.repayment_cadence = "monthly"
    s.repayment_day = day
    s.repayment_strategy = strategy
    world.db.commit()


def test_a_commitment_tied_to_the_card_never_drops_the_instalment(client, db_session):
    world = World(client, db_session)
    world.as_user(lambda: _set_pay_day(world, 20))
    world.as_user(lambda: (world.db.add(CommitmentRule(
        user_id=world.user.id, direction="expense", label="TEST BANK card", amount=Decimal("5000"),
        cadence="monthly", next_date=TODAY + timedelta(days=5), source="manual", status="confirmed",
        card_account_id=world.card_id,
    )), world.db.commit()))
    world.plan(instalments_remaining=1)
    assert len(_plan_events(world)) == 1


def test_it_is_never_a_commitment(client, db_session):
    world = World(client, db_session)
    world.plan()
    labels = [r["label"] for r in world.client.get(f"{API}/analytics/commitments", headers=world.h).json()]
    assert LABEL not in labels and "Test Plan" not in labels


def test_past_instalments_are_never_added_again(client, db_session):
    world = World(client, db_session)
    world.plan(next_date=(TODAY - timedelta(days=40)).isoformat(), instalments_remaining=3)
    # Two dates have passed (on the card already); one is still to come.
    assert len(_plan_events(world)) == 1


def test_after_the_card_goes_the_instalments_still_count(client, db_session):
    world = World(client, db_session)
    world.plan(instalments_remaining=2)
    world.db.query(CardPlan).update({CardPlan.card_account_id: None})
    world.db.commit()
    assert _plan_events(world) == [(_add_months(NEXT, n).isoformat(), "-102.50") for n in range(2)]
    assert world.client.get(f"{API}/analytics/summary", headers=world.h).status_code == 200


def test_another_users_plan_never_reaches_my_forecast(client, db_session):
    alice = World(client, db_session, "instal-alice@example.com")
    alice.plan()
    bob = World(client, db_session, "instal-bob@example.com")
    assert _plan_events(bob) == []
    assert _plan_events(alice)[0] == (NEXT.isoformat(), "-102.50")


def test_claude_sees_a_generic_label_never_the_plan_name(client, db_session):
    # Lead / sec S-7 (2026-10-15): plans reach Claude only as totals, so its
    # forecast events say "Card plan instalment"; the app keeps the name.
    email = "instal-claude@example.com"
    _, _, tokens = _connect(client, scopes=(READ,), email=email)
    world = World(client, db_session, email)
    world.plan(instalments_remaining=1)
    claude = world.client.get(f"{API}/analytics/forecast", params={"horizon": "90"},
                              headers=_bearer(tokens["access_token"])).json()
    events = [(e["label"], e["amount"]) for day in claude["timeline"] for e in day["events"]]
    assert ("Card plan instalment", "-102.50") in events
    assert "Test Plan" not in str(claude)
    assert _plan_events(world) == [(NEXT.isoformat(), "-102.50")]
