"""No Claude change can raise safe-to-spend until the user keeps it
(T-08-21b, owner decision D5 = yes; ux spec 9, KP15-KP20, A8).

eng-a's sibling of sec's gap: over MCP, dismissing an expense commitment,
cutting its amount or moving its next date later took safe-to-spend from
GBP 200 to GBP 500 in sec's setup (salary in 10 days, a GBP 300 bill in 5,
GBP 500 in the bank). An expense now counts the *higher* of the commitment
as it is and as it was before Claude's pending changes (dismissals
included), mirroring the lower-of rule for income (T-08-20). The same
pending/keep state, keep endpoint and undo apply, with `keep_kind:
"expense_cut"`. Raising or confirming a bill lowers safe-to-spend and
applies at once (KP20).
"""
from datetime import date, timedelta
from decimal import Decimal

from app.models import CommitmentRule
from tests.integration.test_claude_income_parity import _projection
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

    def safe_and_savable(self):
        s = self.summary()
        return Decimal(s["safe_to_spend"]), Decimal(s["savable"])

    def listed(self, cid) -> bool:
        rows = self.client.get(f"{API}/analytics/commitments", headers=_bearer(self.web)).json()
        return str(cid) in {r["id"] for r in rows}

    def undo(self, audit_id):
        return self.client.post(f"{API}/audit/{audit_id}/undo", headers=_bearer(self.web))


# --- held until kept ---------------------------------------------------------

def test_dismissing_a_bill_raises_nothing_until_kept(client, db_session):
    w = World(client, db_session)
    before = w.safe_and_savable()
    assert before[0] == Decimal("200.00")
    audit_id = w.claude_dismiss(w.bill)
    assert w.safe_and_savable() == before
    assert w.keep(audit_id).status_code == 200
    assert w.safe_and_savable()[0] == Decimal("500.00")


def test_cutting_a_bill_raises_nothing_until_kept(client, db_session):
    w = World(client, db_session)
    before = w.safe_and_savable()
    audit_id = w.claude_update(w.bill, amount="100.00")
    assert w.safe_and_savable() == before
    assert w.commitment(w.bill)["keep"] == "pending"
    assert w.keep(audit_id).status_code == 200
    assert w.safe_and_savable()[0] == Decimal("400.00")
    assert w.commitment(w.bill)["keep"] == "kept"


def test_moving_a_bill_past_payday_raises_nothing_until_kept(client, db_session):
    w = World(client, db_session)
    before = w.safe_and_savable()
    audit_id = w.claude_update(w.bill, next_date=(TODAY + timedelta(days=15)).isoformat())
    assert w.safe_and_savable() == before
    assert w.keep(audit_id).status_code == 200
    assert w.safe_and_savable()[0] == Decimal("500.00")


def test_making_a_bill_less_frequent_raises_nothing_until_kept(client, db_session):
    w = World(client, db_session)
    cleaner = w.rule("Cleaner", "50.00", TODAY + timedelta(days=1), direction="expense", cadence="weekly")
    before = w.safe_and_savable()
    w.claude_update(cleaner, cadence="monthly")
    assert w.safe_and_savable() == before
    assert w.commitment(cleaner)["keep"] == "pending"


def test_the_projections_hold_back_a_cut_bill_too(client, db_session):
    w = World(client, db_session)
    before = _projection(w)
    audit_id = w.claude_update(w.bill, amount="100.00")
    assert _projection(w) == before
    w.keep(audit_id)
    assert sum(_projection(w)[1]) > sum(before[1])


# --- not held: the fail-safe direction (KP20) --------------------------------

def test_raising_a_bill_applies_at_once_and_needs_no_keep(client, db_session):
    w = World(client, db_session)
    audit_id = w.claude_update(w.bill, amount="400.00")
    assert w.safe_and_savable()[0] == Decimal("100.00")
    assert w.commitment(w.bill)["keep"] is None
    assert w.audit_row(audit_id)["keep"] is None
    assert w.keep(audit_id).status_code == 409


def test_moving_a_bill_earlier_applies_at_once(client, db_session):
    w = World(client, db_session)
    w.claude_update(w.bill, next_date=(TODAY + timedelta(days=2)).isoformat())
    assert w.commitment(w.bill)["keep"] is None


def test_confirming_a_suggested_bill_applies_at_once(client, db_session):
    w = World(client, db_session)
    gym = w.rule("Gym", "100.00", TODAY + timedelta(days=3), direction="expense", status="suggested")
    w.claude_update(gym, status="confirmed")
    assert w.safe_and_savable()[0] == Decimal("100.00")
    assert w.commitment(gym)["keep"] is None


# --- what the app is told (A8) ------------------------------------------------

def test_keep_kind_is_expense_cut_on_the_commitment_and_its_audit_row(client, db_session):
    w = World(client, db_session)
    audit_id = w.claude_update(w.bill, amount="100.00")
    assert w.commitment(w.bill)["keep_kind"] == "expense_cut"
    assert w.audit_row(audit_id)["keep_kind"] == "expense_cut"
    w.keep(audit_id)
    assert w.commitment(w.bill)["keep_kind"] == "expense_cut"  # kept keeps its kind


def test_keep_kind_is_income_for_an_income_and_null_when_nothing_is_held(client, db_session):
    w = World(client, db_session)
    raised = w.claude_update(w.salary, amount="2500.00")
    assert w.commitment(w.salary)["keep_kind"] == "income"
    assert w.audit_row(raised)["keep_kind"] == "income"
    assert w.commitment(w.bill)["keep_kind"] is None


def test_held_values_say_what_still_counts(client, db_session):
    """KP18: the lowered and moved lines need the before-Claude values."""
    w = World(client, db_session)
    bill_date = w.commitment(w.bill)["next_date"]
    w.claude_update(w.bill, amount="100.00")
    row = w.commitment(w.bill)
    assert (Decimal(row["held_amount"]), row["held_next_date"]) == (Decimal("300.00"), None)
    w.claude_update(w.bill, next_date=(TODAY + timedelta(days=15)).isoformat())
    row = w.commitment(w.bill)
    assert (Decimal(row["held_amount"]), row["held_next_date"]) == (Decimal("300.00"), bill_date)


def test_held_values_are_null_when_nothing_is_pending(client, db_session):
    w = World(client, db_session)
    audit_id = w.claude_update(w.bill, amount="100.00")
    w.keep(audit_id)
    row = w.commitment(w.bill)
    assert (row["held_amount"], row["held_next_date"]) == (None, None)


def test_the_safe_to_spend_amount_held_back_is_reported(client, db_session):
    w = World(client, db_session)
    assert Decimal(w.summary()["safe_to_spend_pending_keep_total"]) == Decimal(0)
    w.claude_update(w.bill, amount="100.00")
    s = w.summary()
    assert Decimal(s["safe_to_spend_pending_keep_total"]) == Decimal("200.00")
    assert Decimal(s["savable_pending_keep_total"]) == Decimal(0)  # income only: its note says income


def test_a_dismissed_bill_stays_listed_while_pending(client, db_session):
    """A8(g), KP15/KP16: listed as dismissed and pending; off the list once kept."""
    w = World(client, db_session)
    audit_id = w.claude_dismiss(w.bill)
    row = w.commitment(w.bill)
    assert (row["status"], row["keep"], row["keep_kind"]) == ("dismissed", "pending", "expense_cut")
    assert row["keep_audit_ids"] == [audit_id]
    w.keep(audit_id)
    assert not w.listed(w.bill)


# --- undo, hand edits, who can keep -------------------------------------------

def test_undo_of_a_pending_dismissal_ends_it(client, db_session):
    w = World(client, db_session)
    audit_id = w.claude_dismiss(w.bill)
    assert w.undo(audit_id).status_code == 200
    assert w.safe_and_savable()[0] == Decimal("200.00")
    assert w.commitment(w.bill)["keep"] is None


def test_undo_of_a_kept_cut_restores_the_bill(client, db_session):
    w = World(client, db_session)
    audit_id = w.claude_update(w.bill, amount="100.00")
    w.keep(audit_id)
    assert w.undo(audit_id).status_code == 200
    assert w.safe_and_savable()[0] == Decimal("200.00")


def test_a_hand_edit_of_the_amount_makes_it_the_users(client, db_session):
    """A8(d) refinement: the user's own value counts and needs no keep."""
    w = World(client, db_session)
    w.claude_update(w.bill, amount="100.00")
    res = w.client.patch(f"{API}/analytics/commitments/{w.bill}", json={"amount": "150.00"}, headers=_bearer(w.web))
    assert res.status_code == 200, res.text
    assert w.safe_and_savable()[0] == Decimal("350.00")
    assert w.commitment(w.bill)["keep"] is None


def test_an_mcp_token_cannot_keep_an_expense_change(client, db_session):
    w = World(client, db_session)
    audit_id = w.claude_dismiss(w.bill)
    assert w.keep(audit_id, token=w.mcp).status_code == 401
    assert w.safe_and_savable()[0] == Decimal("200.00")


# --- a card link Claude sets (sec on T-08-21b) --------------------------------

def _card_with_repayment(w, owed="400"):
    """An Amex owing GBP 400, repaid in full in 6 days (after the bill, before payday)."""
    from app.models import AccountSetting
    from tests.integration.test_transactions_endpoint import _account

    def make():
        card = _account(w.db, w.user.id, atype="CREDIT_CARD", name="Gold", balance=owed)
        card.provider_name = "American Express"
        w.db.add(AccountSetting(
            user_id=w.user.id, account_id=card.id, role="credit", repayment_cadence="monthly",
            repayment_day=(TODAY + timedelta(days=6)).day, repayment_strategy="full_balance",
        ))
        w.db.commit()
        return card.id
    return w.as_user(make)


def _committed(w) -> Decimal:
    return Decimal(w.summary()["committed_before_payday"])


def test_a_card_link_claude_sets_raises_nothing_until_kept(client, db_session):
    """Linking the GBP 300 bill to the card makes the summary count the larger
    of the bill and the card's GBP 400 repayment once, not both: committed
    would drop from 700 to 400. Held until kept."""
    w = World(client, db_session)
    card = _card_with_repayment(w)
    assert _committed(w) == Decimal("700.00")
    audit_id = w.claude_update(w.bill, card_account_id=str(card))
    assert _committed(w) == Decimal("700.00")
    row = w.commitment(w.bill)
    assert (row["keep"], row["keep_kind"]) == ("pending", "expense_cut")
    assert Decimal(w.summary()["safe_to_spend_pending_keep_total"]) == Decimal("300.00")
    assert w.keep(audit_id).status_code == 200
    assert _committed(w) == Decimal("400.00")


def test_clearing_a_card_link_applies_at_once(client, db_session):
    """No card: both count, which only lowers safe-to-spend."""
    w = World(client, db_session)
    card = _card_with_repayment(w)
    res = w.client.patch(f"{API}/analytics/commitments/{w.bill}", json={"card_account_id": str(card)},
                         headers=_bearer(w.web))
    assert res.status_code == 200, res.text
    assert _committed(w) == Decimal("400.00")
    w.claude_update(w.bill, card_account_id=None)
    assert _committed(w) == Decimal("700.00")
    assert w.commitment(w.bill)["keep"] is None


def test_a_card_link_with_a_1p_raise_in_one_write_raises_nothing(client, db_session):
    """sec on #131: the raised version wins on value and carried the new
    link, so committed fell to GBP 400. The link is chosen on its own."""
    w = World(client, db_session)
    card = _card_with_repayment(w)
    audit_id = w.claude_update(w.bill, card_account_id=str(card), amount="300.01")
    assert _committed(w) >= Decimal("700.00")
    assert w.keep(audit_id).status_code == 200
    assert _committed(w) == Decimal("400.00")


def test_a_card_link_then_a_1p_raise_raises_nothing(client, db_session):
    w = World(client, db_session)
    card = _card_with_repayment(w)
    w.claude_update(w.bill, card_account_id=str(card))
    w.claude_update(w.bill, amount="300.01")
    assert _committed(w) >= Decimal("700.00")


def test_a_card_link_with_a_1p_raise_leaves_the_projection_unchanged(client, db_session):
    w = World(client, db_session)
    card = _card_with_repayment(w)
    before = _projection(w)
    w.claude_update(w.bill, card_account_id=str(card), amount="300.01")
    assert sum(_projection(w)[1]) <= sum(before[1])


def test_a_raise_then_a_card_link_raises_nothing(client, db_session):
    """eng-a on #131: the raise applies, the link waits (GBP 310 + 400)."""
    w = World(client, db_session)
    card = _card_with_repayment(w)
    w.claude_update(w.bill, amount="310.00")
    w.claude_update(w.bill, card_account_id=str(card))
    assert _committed(w) == Decimal("710.00")
