"""No Claude change can raise safe-to-spend or savable until the user keeps it (T-08-21b).

eng-a's sibling of sec's gap: over MCP, dismissing an expense commitment,
cutting its amount or moving its next date past payday took safe-to-spend
from GBP 200 to GBP 500 in sec's setup (salary in 10 days, a GBP 300 bill in
5, GBP 500 in the bank). For expenses the summary now counts the *higher*
of the commitment as it is and as it was before Claude's pending changes
(dismissals included), mirroring the lower-of rule for income (T-08-20). The
same pending/keep state and POST /audit/{id}/keep apply.
"""
from datetime import date, timedelta
from decimal import Decimal

from app.models import CommitmentRule
from tests.integration.test_claude_payday_window import World as PaydayWorld
from tests.integration.test_oauth import _bearer

API = "/api/v1"
TODAY = date.today()


class World(PaydayWorld):
    def __init__(self, client, db, email="noraise@example.com"):
        super().__init__(client, db, email)
        self.bill = self.as_user(
            lambda: db.query(CommitmentRule).filter(CommitmentRule.direction == "expense").one().id
        )

    def money(self):
        s = self.summary()
        return Decimal(s["safe_to_spend"]), Decimal(s["savable"])

    def keep_state(self, cid):
        return self.commitment(cid)["keep"]


def test_dismissing_a_bill_does_not_raise_anything_until_kept(client, db_session):
    w = World(client, db_session)
    before = w.money()
    assert before[0] == Decimal("200.00")
    audit_id = w.claude_dismiss(w.bill)
    assert w.money() == before
    assert w.keep(audit_id).status_code == 200
    assert w.money()[0] == Decimal("500.00")


def test_cutting_a_bill_does_not_raise_anything_until_kept(client, db_session):
    w = World(client, db_session)
    before = w.money()
    audit_id = w.claude_update(w.bill, amount="100.00")
    assert w.money() == before
    assert w.keep_state(w.bill) == "pending"
    w.keep(audit_id)
    assert w.money()[0] == Decimal("400.00")
    assert w.keep_state(w.bill) == "kept"


def test_moving_a_bill_past_payday_does_not_raise_anything_until_kept(client, db_session):
    w = World(client, db_session)
    before = w.money()
    audit_id = w.claude_update(w.bill, next_date=(TODAY + timedelta(days=15)).isoformat())
    assert w.money() == before
    w.keep(audit_id)
    assert w.money()[0] == Decimal("500.00")


def test_raising_a_bill_applies_at_once_and_needs_no_keep(client, db_session):
    w = World(client, db_session)
    w.claude_update(w.bill, amount="400.00")
    assert w.money()[0] == Decimal("100.00")
    assert w.keep_state(w.bill) is None


def test_the_held_back_amount_is_reported(client, db_session):
    w = World(client, db_session)
    w.claude_update(w.bill, amount="100.00")
    # savable's 30-day window: the GBP 200 cut is held back.
    assert Decimal(w.summary()["savable_pending_keep_total"]) == Decimal("200.00")


def test_an_mcp_token_cannot_keep_an_expense_change(client, db_session):
    w = World(client, db_session)
    audit_id = w.claude_dismiss(w.bill)
    assert w.keep(audit_id, token=w.mcp).status_code == 401
    assert w.money()[0] == Decimal("200.00")


def test_undo_of_a_pending_dismissal_ends_it(client, db_session):
    w = World(client, db_session)
    audit_id = w.claude_dismiss(w.bill)
    assert client.post(f"{API}/audit/{audit_id}/undo", headers=_bearer(w.web)).status_code == 200
    assert w.money()[0] == Decimal("200.00")
    assert w.keep_state(w.bill) is None


def test_projections_hold_back_a_cut_bill_too(client, db_session):
    from tests.integration.test_claude_income_parity import _projection

    w = World(client, db_session)
    before = _projection(w)
    audit_id = w.claude_update(w.bill, amount="100.00")
    assert _projection(w) == before
    w.keep(audit_id)
    assert sum(_projection(w)[1]) > sum(before[1])
