"""Planned matching uses the held (before-Claude) view of a bill (T-20-1a).

sec's probe (sprint 20): a confirmed GBP 50 monthly bill, its GBP 50 payment,
and a GBP 50 one-off planned expense. The payment is the bill's, so it can't
settle the planned item, which still counts. Claude raises the bill to
GBP 200 (or dismisses it, or renames it so its key no longer matches): the
payment stopped being the bill's, settled the item, and safe-to-spend rose
before the user agreed to anything.

While a Claude change to a bill is unkept, a payment is the bill's for
planned matching if the current *or* the before-Claude version matches it
(the union: fewer items settle). The hold ends when the change is kept,
undone, or the user sets that field by hand. Incomes are unchanged. In
T-20-1a a raise or relabel can't be kept yet (T-20-1b), so no keep state
changes here.
"""
import uuid
from datetime import timedelta
from decimal import Decimal

import pytest

from app.models import Account, AuditEntry, CommitmentRule, PlannedItem
from app.services.analytics.commitments import merchant_match_key
from tests.integration.test_claude_income_parity import World as ParityWorld
from tests.integration.test_no_claude_raise import _card_with_repayment
from tests.integration.test_oauth import _bearer
from tests.integration.test_transactions_endpoint import _tx
from tests.clock import TODAY  # one day for the whole run (T-08-27)

API = "/api/v1"
BASELINE = Decimal("450.00")  # GBP 500 in the bank less the unsettled GBP 50 planned item
FREED = Decimal("500.00")  # the payment settled the item
HELD = (BASELINE, Decimal("50.00"))  # safe-to-spend unchanged; the difference is reported
NO_HOLD = (FREED, Decimal(0))


class World(ParityWorld):
    """Payday in 10 days; the GBP 50 gym bill is next due after it (day 20),
    so only the planned item's settlement moves safe-to-spend. With
    `relabel`, sec's relabel case: the bill's stored key (an old merchant)
    differs from its label's key, so a Claude rename (which keeps the stored
    key, not the label's) stops it matching its payments."""

    def __init__(self, client, db, relabel=False):
        super().__init__(client, db, "heldmatch@example.com")
        self.salary = self.rule("Salary", "2000.00", "income", 10)
        key = merchant_match_key("expense", "OLDGYM CO") if relabel else None
        self.bill = self.rule("Gym", "50.00", "expense", 20, match_key=key)
        self.payment = self.tx("50.00", "GYM")
        self.item = self.add(PlannedItem(user_id=self.user.id, name="Kit", direction="expense", kind="one_off",
                                         start_date=TODAY - timedelta(days=1), amount=Decimal("50.00")))

    def add(self, row):
        def make():
            self.db.add(row)
            self.db.commit()
            return row.id
        return self.as_user(make)

    def rule(self, label, amount, direction, next_in, match_key=None):
        return self.add(CommitmentRule(
            user_id=self.user.id, direction=direction, label=label, amount=Decimal(amount), cadence="monthly",
            next_date=TODAY + timedelta(days=next_in), source="manual", status="confirmed", match_key=match_key,
        ))

    def tx(self, amount, merchant, ttype="debit"):
        def make():
            current = self.db.query(Account).filter(Account.user_id == self.user.id).first()
            return _tx(self.db, current, amount, TODAY - timedelta(days=2), ttype=ttype, merchant=merchant).id
        return self.as_user(make)

    def claude_dismiss(self, cid):
        self.n += 1
        res = self.client.post(f"{API}/planning/commitments/{cid}/dismiss", headers=_bearer(self.mcp),
                               json={"dry_run": False, "idempotency_key": f"heldmatch-dismiss-{self.n:04d}"})
        assert res.status_code == 200, res.text
        return res.json()["audit_id"]

    def hand_edit(self, **fields):
        res = self.client.patch(f"{API}/analytics/commitments/{self.bill}", json=fields, headers=_bearer(self.web))
        assert res.status_code == 200, res.text

    def figures(self):
        s = self.summary()
        return Decimal(s["safe_to_spend"]), Decimal(s["safe_to_spend_pending_keep_total"])

    def web_item(self, item_id=None):
        rows = self.client.get(f"{API}/analytics/planned-items", headers=_bearer(self.web)).json()
        return next(i for i in rows if i["id"] == str(item_id or self.item))

    def settled(self) -> tuple:
        """The item's match on the web list and on Claude's list."""
        mcp = self.client.get(f"{API}/planning/planned-events", headers=_bearer(self.mcp)).json()["items"]
        on_mcp = next(i for i in mcp if i["id"] == str(self.item))
        return self.web_item()["matched_transaction_id"], on_mcp["matched_transaction_id"]

    def forecast_planned(self):
        res = self.client.get(f"{API}/analytics/forecast", params={"horizon": "30"}, headers=_bearer(self.web))
        assert res.status_code == 200, res.text
        return [e for p in res.json()["timeline"] for e in p["events"] if e["kind"] == "planned"]


# --- should not settle: a Claude change is unkept ---------------------------------

def test_the_baseline_payment_is_the_bills_and_the_item_counts(client, db_session):
    w = World(client, db_session)
    assert w.figures() == (BASELINE, Decimal(0))
    assert w.settled() == (None, None)


def test_secs_probe_a_claude_raise_settles_nothing(client, db_session):
    w = World(client, db_session)
    savable = Decimal(w.summary()["savable"])
    w.claude_update(w.bill, amount="200.00")
    assert w.figures() == HELD
    assert w.settled() == (None, None)
    # The raise itself still lowers savable at once (GBP 150 more out).
    assert Decimal(w.summary()["savable"]) == savable - Decimal("150.00")


def test_a_claude_raise_leaves_the_forecast_planned_item_in(client, db_session):
    w = World(client, db_session)
    before = w.forecast_planned()
    w.claude_update(w.bill, amount="200.00")
    assert w.forecast_planned() == before != []


def test_a_claude_dismissal_settles_nothing(client, db_session):
    w = World(client, db_session)
    savable = Decimal(w.summary()["savable"])
    w.claude_dismiss(w.bill)
    assert w.figures() == HELD
    assert Decimal(w.summary()["savable"]) == savable
    assert w.settled() == (None, None)


@pytest.mark.parametrize("labels", [("Fitness",), ("Fitness", "Sports")])
def test_claude_relabels_that_drop_the_key_settle_nothing(client, db_session, labels):
    """Two pending relabels hold the label from before both."""
    w = World(client, db_session, relabel=True)
    assert w.figures() == (BASELINE, Decimal(0))
    for label in labels:
        w.claude_update(w.bill, label=label)
    assert w.figures() == HELD
    assert w.settled() == (None, None)


def test_a_raise_still_cannot_be_kept_and_shows_no_keep_state(client, db_session):
    """The T-20-1a boundary: keep for raises and relabels ships in T-20-1b."""
    w = World(client, db_session)
    changes = (w.claude_update(w.bill, amount="200.00"), w.claude_update(w.bill, label="Fitness"))
    assert w.commitment(w.bill)["keep"] is None
    for audit_id in changes:
        assert w.audit_row(audit_id)["keep"] is None
        assert w.keep(audit_id).status_code == 409


def test_a_planned_card_payment_keeps_its_overlap_chip(client, db_session):
    w = World(client, db_session)
    _card_with_repayment(w)

    def flag():
        w.db.get(PlannedItem, w.item).is_card_payment = True
        w.db.commit()
    w.as_user(flag)
    assert w.web_item()["card_payment_overlap"] is True
    w.claude_update(w.bill, amount="200.00")
    assert w.web_item()["card_payment_overlap"] is True


# --- should settle: the hold is over -------------------------------------------------

def test_a_kept_dismissal_settles_the_item(client, db_session):
    w = World(client, db_session)
    assert w.keep(w.claude_dismiss(w.bill)).status_code == 200
    assert w.figures() == NO_HOLD
    assert w.settled() == (str(w.payment), str(w.payment))


def test_a_kept_cut_settles_the_item(client, db_session):
    """GBP 10 is out of the GBP 50 payment's range (max(25%, GBP 5))."""
    w = World(client, db_session)
    audit_id = w.claude_update(w.bill, amount="10.00")
    assert w.figures() == HELD
    assert w.keep(audit_id).status_code == 200
    assert w.figures() == NO_HOLD


@pytest.mark.parametrize("relabel,change", [(False, {"amount": "200.00"}), (True, {"label": "Fitness"})])
def test_undoing_a_claude_change_is_the_same_as_no_change(client, db_session, relabel, change):
    w = World(client, db_session, relabel=relabel)
    audit_id = w.claude_update(w.bill, **change)
    assert w.client.post(f"{API}/audit/{audit_id}/undo", headers=_bearer(w.web)).status_code == 200
    assert w.figures() == (BASELINE, Decimal(0))


def test_a_newer_kept_relabel_ends_an_older_pending_one(client, db_session):
    """The newer write is keepable because it also cuts the amount a little
    (still in the payment's range); keeping it settles its label too."""
    w = World(client, db_session, relabel=True)
    w.claude_update(w.bill, label="Fitness")
    assert w.keep(w.claude_update(w.bill, label="Sports", amount="48.00")).status_code == 200
    assert w.figures() == NO_HOLD


# --- hand edits end the hold for their field ----------------------------------------

def test_a_hand_set_amount_ends_a_raise_hold(client, db_session):
    w = World(client, db_session)
    w.claude_update(w.bill, amount="200.00")
    w.hand_edit(amount="200.00")
    assert w.figures() == NO_HOLD


def test_an_unrelated_hand_edit_keeps_the_hold(client, db_session):
    w = World(client, db_session)
    w.claude_update(w.bill, amount="200.00")
    w.hand_edit(next_date=(TODAY + timedelta(days=21)).isoformat())
    assert w.figures() == HELD


@pytest.mark.parametrize("edit", [{"label": "Fitness club"}, {"match_merchant": "FITNESS FIRST"}])
def test_a_hand_rename_or_matches_merchant_edit_ends_a_relabel_hold(client, db_session, edit):
    w = World(client, db_session, relabel=True)
    audit_id = w.claude_update(w.bill, label="Fitness")
    w.hand_edit(**edit)
    row = w.as_user(lambda: w.db.get(AuditEntry, uuid.UUID(audit_id)))
    assert {"label", "match_key"} <= set(row.user_set_fields or [])
    assert w.figures() == NO_HOLD


# --- incomes and card ties are unchanged ------------------------------------------------

def test_an_income_with_a_pending_raise_and_relabel_still_summarises(client, db_session):
    w = World(client, db_session)
    w.claude_update(w.salary, amount="2500.00", label="Pay")
    assert w.client.get(f"{API}/analytics/summary", headers=_bearer(w.web)).status_code == 200
    assert w.commitment(w.salary)["keep"] == "pending"


def test_an_income_change_still_frees_its_payment_to_settle_planned_income(client, db_session):
    """Incomes stay on the current view (as on main): settling planned income
    only takes it out of the forecast, so the union would be the unsafe side."""
    w = World(client, db_session)
    w.tx("2000.00", "SALARY", ttype="credit")
    bonus = w.add(PlannedItem(user_id=w.user.id, name="Bonus", direction="income", kind="one_off",
                              start_date=TODAY, amount=Decimal("2000.00")))
    assert w.web_item(bonus)["matched_transaction_id"] is None  # the credit is the salary's
    w.claude_update(w.salary, amount="1000.00")  # a lowered income applies at once
    assert w.web_item(bonus)["matched_transaction_id"] is not None


def test_card_ties_read_the_current_label_not_the_held_one(client, db_session):
    """A bill labelled after the card is tied to it (the larger of the two
    counts once). Claude renaming it away unties it at once: both count,
    which only lowers safe-to-spend, so the held label must not be used."""
    w = World(client, db_session)
    _card_with_repayment(w, owed="400")
    amex = w.rule("Amex", "300.00", "expense", 5)
    tied = Decimal(w.summary()["committed_before_payday"])
    w.claude_update(amex, label="Gadgets")
    assert Decimal(w.summary()["committed_before_payday"]) == tied + Decimal("300.00")
