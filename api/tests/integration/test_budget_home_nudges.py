"""Budgets on Home, the forecast's reason, and the two budget nudges (T-09-4b;
concept sections 4.3 and 15.6/15.8; sec's nudge rules).

- GET /budgets carries a small Home summary: how many budgets, how many on
  or under pace, and the first one over (category and amount).
- The forecast says why there's no budget_projection: "no_budgets" or
  "no_payday" (BC2/BC3), null when it's there.
- Two in-app nudges per budget per cycle, stored per user, budget and
  cycle so each fires at most once: at the limit ("Eating out is £12 over
  its £150 budget with 12 days left.") and one early pace nudge ("Groceries
  is ahead of pace: £212 of £300 with 12 days left."). Fixed copy, the
  category as text. Dismiss is web only and per nudge.
"""
from datetime import timedelta

import pytest
from sqlalchemy import text

from tests.clock import TODAY
from tests.integration.test_budgets_api import API, World
from tests.integration.test_oauth import READ, _bearer, _connect


@pytest.fixture
def w(client, db_session):
    world = World(client, db_session)
    world.history()  # this cycle: Eating out 40, Groceries 80, Shopping 120; 20 days in
    return world


def _nudges(w, token=None):
    r = w.client.get(f"{API}/analytics/nudges", headers=_bearer(token or w.web))
    assert r.status_code == 200, r.text
    return [n for n in r.json() if n["id"].startswith("budget-")]


# --- Home summary ---------------------------------------------------------------------

def test_the_home_summary(w):
    w.create("Eating out", 150)   # under pace
    w.create("Shopping", 100)     # £20 over
    w.create("Groceries", 70)     # £10 over
    summary = w.get().json()["summary"]
    assert (summary["budget_count"], summary["on_pace_count"]) == (3, 1)
    assert summary["first_over"]["category"] == "Shopping"
    assert summary["first_over"]["over_by"] == "20.00"


def test_no_budgets_an_empty_summary(w):
    assert w.get().json()["summary"] == {"budget_count": 0, "on_pace_count": 0, "first_over": None}


# --- why there's no projection ----------------------------------------------------------

def _reason(w):
    body = w.client.get(f"{API}/analytics/forecast", headers=_bearer(w.web)).json()
    return body["budget_projection"], body["budget_projection_reason"]


def test_the_forecast_says_why_there_is_no_projection(w):
    assert _reason(w) == (None, "no_budgets")
    w.create("Eating out", 150)
    projection, reason = _reason(w)
    assert projection is not None and reason is None


def test_no_payday_is_its_own_reason(w):
    from app.models import CommitmentRule

    w.create("Eating out", 150)

    def drop_payday():
        w.db.query(CommitmentRule).filter(CommitmentRule.direction == "income").delete()
        w.db.commit()
    w.as_user(drop_payday)
    assert _reason(w) == (None, "no_payday")


# --- nudges ---------------------------------------------------------------------------------

def test_at_the_limit_a_nudge_with_the_figures(w):
    w.create("Shopping", 100)  # 120 spent
    [nudge] = _nudges(w)
    assert nudge["body"].startswith("Shopping is £20 over its £100 budget ")
    assert nudge["source"] is None


def test_an_early_pace_nudge(client, db_session):
    """Ahead of pace in the first half of the cycle."""
    w = World(client, db_session, email="pace@example.com")
    w.history()

    def payday_recent():
        from app.models import CommitmentRule
        rule = w.db.query(CommitmentRule).filter(CommitmentRule.is_payday.is_(True)).one()
        rule.next_date = TODAY - timedelta(days=6)  # 7 days into a ~30-day cycle
        w.db.commit()
    w.as_user(payday_recent)
    w.create("Groceries", 300)  # 80 spent after 7 days: pace ~70, ahead
    [nudge] = _nudges(w)
    assert nudge["body"].startswith("Groceries is ahead of pace: £80 of £300 with ")


def test_under_pace_no_nudge(w):
    w.create("Eating out", 150)
    assert _nudges(w) == []


def test_a_nudge_fires_once_per_budget_per_cycle(w):
    w.create("Shopping", 100)
    first = _nudges(w)
    assert _nudges(w) == first  # the same stored nudge, not a new one
    assert w.db.execute(text("SELECT count(*) FROM budget_nudges")).scalar() == 1


def test_dismissed_stays_dismissed(w):
    w.create("Shopping", 100)
    [nudge] = _nudges(w)
    r = w.client.post(f"{API}/budgets/nudges/{nudge['id'].removeprefix('budget-')}/dismiss", headers=_bearer(w.web))
    assert r.status_code == 204
    assert _nudges(w) == []


def test_a_paused_or_removed_budget_has_no_nudge(w):
    budget_id = w.create("Shopping", 100).json()["id"]
    w.patch(budget_id, paused=True)
    assert _nudges(w) == []
    w.patch(budget_id, paused=False)
    w.delete(budget_id)
    assert _nudges(w) == []


def test_another_users_nudge_cant_be_dismissed(client, db_session, w):
    w.create("Shopping", 100)
    [nudge] = _nudges(w)
    other = World(client, db_session, email="other@example.com")
    r = client.post(f"{API}/budgets/nudges/{nudge['id'].removeprefix('budget-')}/dismiss", headers=_bearer(other.web))
    assert r.status_code == 404
    assert len(_nudges(w)) == 1


def test_dismiss_is_web_only(client, db_session, w):
    w.create("Shopping", 100)
    [nudge] = _nudges(w)
    _, _, tokens = _connect(client, scopes=(READ,), email="budgets@example.com")
    r = client.post(f"{API}/budgets/nudges/{nudge['id'].removeprefix('budget-')}/dismiss",
                    headers=_bearer(tokens["access_token"]))
    assert r.status_code == 401


def test_exactly_at_the_limit_says_reached_not_over(w):
    """Lead on #158: "kept" means at or under the limit, so spend equal to
    the limit is never called "over"."""
    w.create("Shopping", 120)  # exactly 120 spent
    [nudge] = _nudges(w)
    assert nudge["body"].startswith("Shopping has reached its £120 budget ")
    assert "over" not in nudge["body"]


def test_a_paused_budget_leaves_the_home_line(w):
    """eng-a on #158 (BM7): "1 of 1 on pace", not "1 of 2"."""
    w.create("Eating out", 150)
    paused = w.create("Groceries", 400).json()["id"]
    w.patch(paused, paused=True)
    summary = w.get().json()["summary"]
    assert (summary["budget_count"], summary["on_pace_count"]) == (1, 1)


@pytest.mark.parametrize("days,words", [(0, "on the last day of this pay cycle"), (1, "with 1 day left"),
                                        (9, "with 9 days left")])
def test_days_left_reads_naturally(days, words):
    from app.services.budgets import _left
    assert _left(days) == words
