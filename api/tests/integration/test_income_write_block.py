"""Stopgap T-08-21a is lifted (T-08-21): Claude may move, re-time, confirm or
dismiss an income commitment over MCP again.

21a refused these with 422 because they could shrink the payday window and
raise safe-to-spend. T-08-21 now holds the window at the later of payday now
and payday before Claude's pending changes, and T-08-20 holds savable back,
until the user keeps the change. These tests pin that the writes work again
and that sec's repro stays safe; test_claude_payday_window.py has the rest.
"""
from datetime import timedelta
from decimal import Decimal

import pytest

from app.models import CommitmentRule
from app.services import analytics_service as svc
from tests.integration.test_commitment_writes_api import API, World, _bearer
from tests.integration.test_transactions_endpoint import _account



@pytest.fixture
def world(client, db_session):
    return World(client, db_session)


def _income(world, **over):
    rid = world.commitment(label="Salary", amount="2000", direction="income", **over)
    with world.as_user():
        rule = world.db.get(CommitmentRule, rid)
        rule.is_payday = True
        world.db.commit()
    return rid


@pytest.mark.parametrize("body", [
    {"next_date": (svc._today() + timedelta(days=2)).isoformat()},
    {"cadence": "weekly"},
    {"cadence": "every_n_months", "interval_months": 1},
    {"interval_months": 2},
    {"interval_days": 7},
    {"status": "confirmed"},
    {"label": "Salary", "next_date": (svc._today() + timedelta(days=2)).isoformat()},
])
@pytest.mark.parametrize("dry_run", [False, True])
def test_timing_or_status_writes_on_income_work_again(world, body, dry_run):
    """T-08-21 lifted the 21a stopgap: the real fix holds the payday window
    and savable back until the user keeps the change, so these are allowed."""
    rid = _income(world)
    r = world.update(rid, dry_run=dry_run, **body)
    assert r.status_code == 200, r.text
    recorded = not dry_run and not r.json()["unchanged"]  # re-confirming a confirmed income is a no-op
    assert world.audit_count() == (1 if recorded else 0)


def test_confirming_a_suggested_income_works_again(world):
    rid = _income(world, status="suggested", source="detected")
    assert world.update(rid, status="confirmed", dry_run=False).status_code == 200
    assert world.rule(rid).status == "confirmed"


def test_dismissing_an_income_works_again(world):
    rid = _income(world)
    assert world.dismiss(rid, dry_run=False).status_code == 200
    assert world.rule(rid).status == "dismissed"


def test_an_income_label_can_still_be_fixed(world):
    rid = _income(world)
    assert world.update(rid, label="Salary (Acme)", dry_run=False).status_code == 200
    assert world.rule(rid).label == "Salary (Acme)"


def test_expense_commitments_are_unchanged(world):
    rid = world.commitment(label="Gym", amount="30")
    new_date = (svc._today() + timedelta(days=9)).isoformat()
    assert world.update(rid, next_date=new_date, cadence="weekly", dry_run=False).status_code == 200
    assert world.dismiss(rid, dry_run=False).status_code == 200


def test_another_users_income_is_still_404_not_422(client, db_session):
    victim = World(client, db_session, email="v21a@example.com")
    rid = _income(victim)
    attacker = World(client, db_session, email="a21a@example.com")
    assert attacker.update(rid, next_date=svc._today().isoformat(), dry_run=False).status_code == 404
    assert attacker.dismiss(rid, dry_run=False).status_code == 404


def test_the_web_route_still_lets_the_user_move_their_payday(world):
    rid = _income(world)
    new_date = (svc._today() + timedelta(days=2)).isoformat()
    r = world.client.patch(f"{API}/analytics/commitments/{rid}", json={"next_date": new_date}, headers=_bearer(world.web))
    assert r.status_code == 200, r.text


def test_secs_repro_safe_to_spend_cannot_be_raised(world):
    """Salary in 10 days, a £300 bill in 5: moving the salary to 2 days used
    to lift safe-to-spend from £200 to £500."""
    with world.as_user():
        _account(world.db, world.user.id, name="Main", balance="500")
    rid = _income(world, next_date=svc._today() + timedelta(days=10))
    world.commitment(label="Phone", amount="300", next_date=svc._today() + timedelta(days=5))

    def safe():
        r = world.client.get(f"{API}/analytics/summary", headers=_bearer(world.web))
        return Decimal(r.json()["safe_to_spend"])

    assert safe() == Decimal("200")  # precondition: the bill counts
    r = world.update(rid, next_date=(svc._today() + timedelta(days=2)).isoformat(), dry_run=False)
    assert r.status_code == 200  # allowed again: T-08-21 holds the window back instead
    assert safe() == Decimal("200")
