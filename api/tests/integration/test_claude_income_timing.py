"""Claude's timing and status changes to income wait for keep (T-08-20/21).

These used #119's World but need MCP changes to an income's date, cadence
and status, which the 21a stopgap refused until T-08-21 lifted it.
"""
from datetime import timedelta
from decimal import Decimal

from app.models import CommitmentRule
from tests.integration.test_claude_income_parity import API, TODAY, World, _bearer, _projection  # noqa: F401


def test_a_claude_confirmed_suggestion_counts_nothing_until_kept(client, db_session):
    w = World(client, db_session)
    cid = w.income("1000.00", status="suggested")
    assert w.savable() == Decimal("500.00")
    audit_id = w.claude_update(cid, status="confirmed")
    assert w.savable() == Decimal("500.00")
    w.keep(audit_id)
    assert w.savable() == Decimal("1500.00")


def test_a_claude_cadence_change_that_brings_in_more_waits_too(client, db_session):
    w = World(client, db_session)
    cid = w.income("1000.00")
    w.claude_update(cid, cadence="custom_days", interval_days=7)  # weekly: ~4x in 30 days
    assert w.savable() == Decimal("1500.00")
    assert w.commitment(cid)["keep"] == "pending"


def test_a_hand_edit_of_one_of_two_claude_fields_stays_pending(client, db_session):
    """KP14: Claude changed amount and cadence; the user edits only the amount."""
    w = World(client, db_session)
    cid = w.income("1000.00")
    w.claude_update(cid, amount="1500.00", cadence="custom_days", interval_days=7)
    client.patch(f"{API}/analytics/commitments/{cid}", json={"amount": "1800.00"}, headers=_bearer(w.web))
    assert w.commitment(cid)["keep"] == "pending"


def test_a_claude_confirmed_suggestion_is_not_projected_until_kept(client, db_session):
    w = World(client, db_session)
    cid = w.income("1000.00", status="suggested")
    before = _projection(w)
    audit_id = w.claude_update(cid, status="confirmed")
    assert _projection(w) == before
    w.keep(audit_id)
    assert _projection(w)[0] > before[0]


def test_a_change_to_the_date_that_is_not_a_web_edit_keeps_it_pending(client, db_session):
    """sec on #121: sync advances a past next_date on every commitments load,
    so a stored date that no longer equals Claude's value is not proof the
    user overrode it. Only a recorded web edit is."""
    w = World(client, db_session)
    def make():
        rule = CommitmentRule(
            user_id=w.user.id, direction="income", label="Income A", amount=Decimal("1000.00"),
            cadence="monthly", next_date=TODAY + timedelta(days=40), source="manual", status="confirmed",
        )
        db_session.add(rule)
        db_session.commit()
        return rule.id
    cid = w.as_user(make)
    assert w.savable() == Decimal("500.00")  # nothing due within 30 days
    w.claude_update(cid, next_date=(TODAY + timedelta(days=2)).isoformat())
    assert w.savable() == Decimal("500.00")
    # The stored date moves on without a web edit (as sync does once a date passes).
    def move():
        db_session.get(CommitmentRule, cid).next_date = TODAY + timedelta(days=3)
        db_session.commit()
    w.as_user(move)
    assert w.savable() == Decimal("500.00")
    assert w.commitment(cid)["keep"] == "pending"
