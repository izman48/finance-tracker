"""Claude can't widen safe-to-spend by moving payday closer (T-08-21, sec).

sec's repro (live since #110): salary in 10 days, a GBP 300 bill in 5,
GBP 500 in the bank: safe-to-spend GBP 200. Moving the salary's next date to
2 days ends the committed window before the bill, so safe-to-spend became
GBP 500. The same works by changing its cadence, confirming a nearer
suggested income, or dismissing the payday income.

Fix: while such a Claude change is pending (not kept), the committed window
ends at the *later* of next payday as things are and next payday as they
were before Claude (the T-08-20 pre-Claude view, dismissals included).
"""
from datetime import date, timedelta
from decimal import Decimal

from app.core import user_crypto
from app.models import CommitmentRule
from tests.integration.test_claude_income_parity import World as ParityWorld

API = "/api/v1"
TODAY = date.today()


class World(ParityWorld):
    def __init__(self, client, db, email="payday@example.com"):
        super().__init__(client, db, email)
        self.salary = self.rule("Salary", "2000.00", TODAY + timedelta(days=10))
        self.rule("Phone bill", "300.00", TODAY + timedelta(days=5), direction="expense")

    def rule(self, label, amount, next_date, direction="income", status="confirmed", cadence="monthly"):
        def make():
            r = CommitmentRule(
                user_id=self.user.id, direction=direction, label=label, amount=Decimal(amount),
                cadence=cadence, next_date=next_date, source="manual", status=status,
            )
            self.db.add(r)
            self.db.commit()
            return r.id
        return self.as_user(make)

    def safe(self) -> Decimal:
        return Decimal(self.summary()["safe_to_spend"])

    def claude_dismiss(self, cid):
        self.n += 1
        from tests.integration.test_oauth import _bearer
        res = self.client.post(
            f"{API}/planning/commitments/{cid}/dismiss",
            json={"dry_run": False, "idempotency_key": f"payday-dismiss-{self.n:04d}"},
            headers=_bearer(self.mcp),
        )
        assert res.status_code == 200, res.text
        return res.json()["audit_id"]


def test_the_baseline(client, db_session):
    w = World(client, db_session)
    assert w.safe() == Decimal("200.00")


def test_moving_the_salary_closer_does_not_widen_safe_to_spend(client, db_session):
    """sec's repro: 200 must not become 500."""
    w = World(client, db_session)
    w.claude_update(w.salary, next_date=(TODAY + timedelta(days=2)).isoformat())
    assert w.safe() == Decimal("200.00")


def test_keeping_the_change_applies_it(client, db_session):
    w = World(client, db_session)
    audit_id = w.claude_update(w.salary, next_date=(TODAY + timedelta(days=2)).isoformat())
    assert w.keep(audit_id).status_code == 200
    assert w.safe() == Decimal("500.00")


def test_a_cadence_change_does_not_widen_it(client, db_session):
    w = World(client, db_session)
    # Weekly from a date 5 days ago: the next one would land in 2 days.
    w.claude_update(w.salary, cadence="custom_days", interval_days=7,
                    next_date=(TODAY - timedelta(days=5)).isoformat())
    assert w.safe() == Decimal("200.00")


def test_confirming_a_nearer_suggested_income_does_not_widen_it(client, db_session):
    w = World(client, db_session)
    side = w.rule("Side income", "50.00", TODAY + timedelta(days=2), status="suggested")
    w.claude_update(side, status="confirmed")
    assert w.safe() == Decimal("200.00")


def test_dismissing_the_payday_income_does_not_widen_it(client, db_session):
    """The salary is the flagged payday; a nearer income (interest in 2
    days) isn't. Dismissing the salary would make the interest payday."""
    w = World(client, db_session)
    def flag():
        db_session.get(CommitmentRule, w.salary).is_payday = True
        db_session.commit()
    w.as_user(flag)
    w.rule("Interest", "1.00", TODAY + timedelta(days=2))
    assert w.safe() == Decimal("200.00")
    w.claude_dismiss(w.salary)
    assert w.safe() == Decimal("200.00")


def test_a_change_that_moves_payday_later_applies_at_once(client, db_session):
    """Later payday = more bills before it: the safe side, no keep needed."""
    w = World(client, db_session)
    w.rule("Gym", "100.00", TODAY + timedelta(days=15), direction="expense")
    w.claude_update(w.salary, next_date=(TODAY + timedelta(days=20)).isoformat())
    assert w.safe() == Decimal("100.00")  # 500 - 300 - 100


def test_the_payday_shown_is_unchanged(client, db_session):
    """Only the committed window is held back; next_payday still reports the
    commitment as it now is."""
    w = World(client, db_session)
    w.claude_update(w.salary, next_date=(TODAY + timedelta(days=2)).isoformat())
    assert w.summary()["next_payday"] == (TODAY + timedelta(days=2)).isoformat()
