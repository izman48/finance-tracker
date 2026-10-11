"""Only a Claude dismissal that could bring payday nearer waits for keep
(T-08-21 follow-up; eng-a on #121, lead's decision).

Dismissing an income can only move the committed window's end *nearer*
when it changes which incomes set payday: the only flagged payday income
goes (payday falls back to every income), or the last income goes (payday
falls back to 30 days). Dismissing any other income can only leave payday
where it is or move it later, so it changes no held figure and applies at
once: no pending state, no Keep button that does nothing.
"""
from datetime import timedelta
from decimal import Decimal

from app.models import CommitmentRule
from tests.integration.test_claude_payday_window import API, TODAY, World
from tests.integration.test_oauth import _bearer


def _flag(w, rule_id):
    def flag():
        w.db.get(CommitmentRule, rule_id).is_payday = True
        w.db.commit()
    w.as_user(flag)


def _listed(w, rule_id) -> bool:
    rows = w.client.get(f"{API}/analytics/commitments", headers=_bearer(w.web)).json()
    return str(rule_id) in {r["id"] for r in rows}


def test_dismissing_the_payday_income_waits_for_keep(client, db_session):
    w = World(client, db_session)
    _flag(w, w.salary)
    w.rule("Interest", "1.00", TODAY + timedelta(days=2))
    audit_id = w.claude_dismiss(w.salary)
    assert w.commitment(w.salary)["keep"] == "pending"
    assert w.audit_row(audit_id)["keep"] == "pending"
    assert w.safe() == Decimal("200.00")  # the salary still ends the window


def test_dismissing_a_non_payday_income_applies_at_once(client, db_session):
    """eng-a's case: "Side job" due in 20 days beside the flagged salary."""
    w = World(client, db_session)
    _flag(w, w.salary)
    side = w.rule("Side job", "400.00", TODAY + timedelta(days=20))
    savable = w.savable()
    audit_id = w.claude_dismiss(side)
    assert not _listed(w, side)  # an ordinary dismissal: off the list
    assert w.audit_row(audit_id)["keep"] is None
    assert w.keep(audit_id).status_code == 409  # nothing to keep
    assert w.savable() < savable
    assert w.safe() == Decimal("200.00")


def test_without_a_flag_dismissing_one_of_two_incomes_applies_at_once(client, db_session):
    w = World(client, db_session)
    other = w.rule("Rent from lodger", "300.00", TODAY + timedelta(days=12))
    audit_id = w.claude_dismiss(other)
    assert w.audit_row(audit_id)["keep"] is None
    assert w.safe() == Decimal("200.00")


def test_dismissing_the_last_income_waits_for_keep(client, db_session):
    """No income left: payday falls back to 30 days, which can be nearer
    than the income's own date (a quarterly one, say)."""
    w = World(client, db_session)
    audit_id = w.claude_dismiss(w.salary)
    assert w.audit_row(audit_id)["keep"] == "pending"


def test_a_held_dismissal_is_released_when_another_payday_is_flagged(client, db_session):
    """Whether a dismissal is held follows the incomes as they are now: once
    another income is the flagged payday, the dismissal applies."""
    w = World(client, db_session)
    _flag(w, w.salary)
    bonus = w.rule("Bonus", "100.00", TODAY + timedelta(days=25))
    audit_id = w.claude_dismiss(w.salary)
    assert w.audit_row(audit_id)["keep"] == "pending"
    _flag(w, bonus)
    assert w.audit_row(audit_id)["keep"] is None


def test_an_applied_dismissal_is_held_again_once_it_would_move_payday(client, db_session):
    """eng-a on #128: whether a dismissal is held follows the incomes as they
    are now, so it can go back to pending. No flags: Claude's dismissal of
    the lodger applies at once while the salary sets payday; once the user
    dismisses the salary by hand, the lodger is the last income, and its
    dismissal would bring payday to the 30-day fallback, so it is held."""
    w = World(client, db_session)
    lodger = w.rule("Rent from lodger", "300.00", TODAY + timedelta(days=12))
    audit_id = w.claude_dismiss(lodger)
    assert w.audit_row(audit_id)["keep"] is None
    res = w.client.patch(f"{API}/analytics/commitments/{w.salary}", json={"status": "dismissed"},
                         headers=_bearer(w.web))
    assert res.status_code == 200, res.text
    assert w.audit_row(audit_id)["keep"] == "pending"
    assert w.commitment(lodger)["status"] == "dismissed"
