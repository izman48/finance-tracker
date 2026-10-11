"""A late income clears when it arrives split, and Skip clears it (T-08-23).

Owner's case (anonymised): a monthly income of GBP 1,203, "Payer X Parents
and rent", expected 5 days ago, arrived 2 days ago as two credits from the
same payer: GBP 1,003 ("PAYER X RENT") and GBP 200 ("PAYER X MAMA AND
DADA"). Late needed one credit with the commitment's own key, within
max(GBP 1, 2%), so it never cleared. Credits from the same payer (the
leading words of the description) near the expected date now count
together, including ones the user marked as a transfer (for this check
only). Late income is never counted anywhere, so this is display only.
"""
from datetime import date, timedelta
from decimal import Decimal

from app.core import user_crypto
from app.models import CommitmentRule, Transaction
from tests.integration.test_late_income import World as LateWorld
from tests.integration.test_oauth import _bearer
from tests.integration.test_transactions_endpoint import _tx

API = "/api/v1"
TODAY = date.today()
EXPECTED = TODAY - timedelta(days=5)
ARRIVED = TODAY - timedelta(days=2)
LABEL = "Payer X Parents and rent"


class World(LateWorld):
    def __init__(self, client, db):
        super().__init__(client, db, email="split@example.com")
        self.rule_id = self.income(EXPECTED)

        def relabel():
            rule = db.get(CommitmentRule, self.rule_id)
            rule.label, rule.amount, rule.match_key = LABEL, Decimal("1203.00"), "income:payer x parents and rent"
            db.commit()
        self.as_user(relabel)

    def paid(self, amount, description, on=ARRIVED, override=None):
        def make():
            tx = _tx(self.db, self.current, amount, on, ttype="credit", merchant=description)
            if override:
                self.db.get(Transaction, tx.id).counts_as_override = override
                self.db.commit()
            return tx
        return self.as_user(make)

    def late(self) -> bool:
        return self.commitments()[LABEL]["late"]

    def skip(self):
        res = self.client.post(f"{API}/analytics/commitments/{self.rule_id}/skip", headers=_bearer(self.web))
        assert res.status_code == 200, res.text
        return res.json()


def test_it_is_late_with_nothing_paid(client, db_session):
    assert World(client, db_session).late() is True


def test_a_split_payment_from_the_same_payer_clears_it(client, db_session):
    w = World(client, db_session)
    w.paid("1003.00", "PAYER X RENT")
    w.paid("200.00", "PAYER X MAMA AND DADA")
    assert w.late() is False


def test_a_split_payment_marked_as_a_transfer_still_clears_it(client, db_session):
    """The owner marks some of these as transfers (pass-through): that changes
    no money figure, and for this check they still show the income came."""
    w = World(client, db_session)
    w.paid("1003.00", "PAYER X RENT", override="transfer")
    w.paid("200.00", "PAYER X MAMA AND DADA", override="transfer")
    assert w.late() is False


def test_a_larger_payment_from_the_payer_clears_it(client, db_session):
    """Earlier months varied (GBP 1,292, 1,219): more than expected arrived."""
    w = World(client, db_session)
    w.paid("1292.00", "PAYER X PARENTS")
    assert w.late() is False


def test_an_unrelated_gbp_5_from_the_payer_does_not_clear_it(client, db_session):
    w = World(client, db_session)
    w.paid("5.00", "PAYER X COFFEE")
    assert w.late() is True


def test_part_of_the_money_does_not_clear_it(client, db_session):
    w = World(client, db_session)
    w.paid("1003.00", "PAYER X RENT")
    assert w.late() is True


def test_another_payer_does_not_count(client, db_session):
    w = World(client, db_session)
    w.paid("1003.00", "PAYER X RENT")
    w.paid("200.00", "PAYER Y MAMA AND DADA")
    assert w.late() is True


def test_credits_long_after_the_expected_date_do_not_count(client, db_session):
    """Only near the expected date: a later month's money isn't this one."""
    w = World(client, db_session)
    w.paid("1003.00", "PAYER X RENT", on=EXPECTED - timedelta(days=20))
    w.paid("200.00", "PAYER X MAMA AND DADA", on=EXPECTED - timedelta(days=20))
    assert w.late() is True


def test_skip_clears_it_and_keeps_the_next_payment_expected(client, db_session):
    w = World(client, db_session)
    next_before = w.commitments()[LABEL]["next_date"]
    w.skip()
    row = w.commitments()[LABEL]
    assert row["late"] is False
    assert row["next_date"] == next_before  # next month's income still expected


def test_skip_on_an_income_that_is_not_late_still_skips_the_next_one(client, db_session):
    w = World(client, db_session)
    w.paid("1203.00", "PAYER X PARENTS AND RENT")
    next_before = date.fromisoformat(w.commitments()[LABEL]["next_date"])
    after = date.fromisoformat(w.skip()["next_date"])
    assert after > next_before
