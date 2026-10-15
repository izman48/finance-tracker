"""Forecast events from a commitment carry its id (sec nit on #198), so the
UI names a loan's linked bill by id, as Coming up does, not by matching the
bill's label. Other events carry none. No figure changes.

Synthetic fixture: current account £3,000, salary £2,500, gym £32.
"""
from datetime import timedelta
from decimal import Decimal

from app.models import AccountSetting, CommitmentRule
from tests.clock import TODAY
from tests.integration.test_net_worth_liabilities import World
from tests.integration.test_oauth import READ, _connect
from tests.integration.test_transactions_endpoint import _account


def _rule(world, label, amount, direction, days):
    def make():
        rule = CommitmentRule(
            user_id=world.user.id, direction=direction, label=label, amount=Decimal(amount), cadence="monthly",
            next_date=TODAY + timedelta(days=days), source="manual", status="confirmed",
        )
        world.db.add(rule)
        world.db.commit()
        return str(rule.id)
    return world.as_user(make)


def _events(world):
    forecast = world.get("/analytics/forecast?horizon=30")
    return [e for p in forecast["timeline"] for e in p["events"]]


def test_commitment_events_carry_the_commitment_id(client, db_session):
    w = World(client, db_session, email="event-id@example.com")
    w.bank()  # current account + a salary commitment
    gym = _rule(w, "Gym", "32", "expense", 4)
    events = _events(w)
    gym_events = [e for e in events if e["label"] == "Gym"]
    assert gym_events and all(e["commitment_id"] == gym for e in gym_events)
    salary = [e for e in events if e["label"] == "Salary"]
    assert salary and all(e["commitment_id"] for e in salary)


def test_events_not_from_a_commitment_carry_none(client, db_session):
    w = World(client, db_session, email="event-none@example.com")
    w.bank()
    res = client.post("/api/v1/analytics/planned-items", json={
        "name": "Laptop", "direction": "expense", "kind": "one_off", "amount": "300.00",
        "start_date": (TODAY + timedelta(days=6)).isoformat(),
    }, headers={"Authorization": f"Bearer {w.web}"})
    assert res.status_code in (200, 201), res.text
    planned = [e for e in _events(w) if e["label"] == "Laptop"]
    assert planned and all(e["commitment_id"] is None for e in planned)


# What Claude's `forecast` tool receives (sec on #201): the exact key set of
# an event of every kind, so the next new field fails here first.
EVENT_KEYS = {"label", "amount", "kind", "commitment_id"}


def test_claude_receives_exactly_these_event_fields(client, db_session):
    web, _, tokens = _connect(client, scopes=(READ,), email="event-keys@example.com")
    w = World(client, db_session, email="event-keys@example.com", token=web)
    w.bank()  # current account + salary (income)
    _rule(w, "Gym", "32", "expense", 4)

    def card():
        acc = _account(db_session, w.user.id, atype="CREDIT_CARD", name="Card", balance="600")
        db_session.add(AccountSetting(
            user_id=w.user.id, account_id=acc.id, role="credit", repayment_cadence="end_of_month",
            repayment_strategy="full_balance",
        ))
        db_session.commit()
    w.as_user(card)
    res = client.post("/api/v1/analytics/planned-items", json={
        "name": "Laptop", "direction": "expense", "kind": "one_off", "amount": "300.00",
        "start_date": (TODAY + timedelta(days=6)).isoformat(),
    }, headers={"Authorization": f"Bearer {web}"})
    assert res.status_code in (200, 201), res.text

    forecast = w.get("/analytics/forecast?horizon=90", token=tokens["access_token"])
    by_kind = {}
    for event in (e for p in forecast["timeline"] for e in p["events"]):
        by_kind.setdefault(event["kind"], event)
    assert set(by_kind) == {"income", "expense", "repayment", "planned"}
    for kind, event in by_kind.items():
        assert set(event) == EVENT_KEYS, kind
    assert by_kind["repayment"]["commitment_id"] is None
    assert by_kind["planned"]["commitment_id"] is None
