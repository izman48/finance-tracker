"""GET /analytics/nudges with a duplicate-commitment nudge (T-08-25).

That nudge is about the user's own commitments, so it cites no outside
source: `source` is null. The endpoint 500'd on it in production because
the response model required a string.
"""
from datetime import timedelta
from decimal import Decimal

from app.models import CommitmentRule
from tests.integration.test_claude_income_parity import API, TODAY, World
from tests.integration.test_oauth import _bearer


def _confirmed_bill(w, label, next_date):
    def make():
        w.db.add(CommitmentRule(
            user_id=w.user.id, direction="expense", label=label, amount=Decimal("18.00"),
            cadence="monthly", next_date=next_date, source="manual", status="confirmed",
        ))
        w.db.commit()
    w.as_user(make)


def test_a_duplicate_commitment_nudge_is_served_with_no_source(client, db_session):
    w = World(client, db_session, email="nudges@example.com")
    _confirmed_bill(w, "ANTHROPIC CLAUDE SUB", TODAY + timedelta(days=5))
    _confirmed_bill(w, "CLAUDE.AI SUBSCRIPTION", TODAY + timedelta(days=6))

    res = client.get(f"{API}/analytics/nudges", headers=_bearer(w.web))

    assert res.status_code == 200, res.text
    duplicate = next(n for n in res.json() if n["id"].startswith("duplicate_commitment_"))
    assert duplicate["source"] is None and duplicate["as_of"] is None
