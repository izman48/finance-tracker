"""Forecast events from a commitment carry its id (sec nit on #198), so the
UI names a loan's linked bill by id, as Coming up does, not by matching the
bill's label. Other events carry none. No figure changes.

Synthetic fixture: current account £3,000, salary £2,500, gym £32.
"""
from datetime import timedelta
from decimal import Decimal

from app.models import CommitmentRule
from tests.clock import TODAY
from tests.integration.test_net_worth_liabilities import World


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
