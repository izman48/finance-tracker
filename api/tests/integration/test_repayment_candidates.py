"""Repayment candidates: which incoming payments look like repayments, and
which spend each most likely paid back (T-03-5 P7; PRD T-03-1 v2 "Which
spend is most likely", ACs 9 to 14 and 18).

Score 0 to 100: amount (35 for a near match or an equal split, else 20),
words and Claude's hints (up to 25), date (up to 25), and how much of the
spend is still unmarked (15 or 10). `high` is 70 or more and 15 ahead of the
next; `medium` is 45 or more; below that there is no likely spend, only a
fallback category at 30 or more. Computed per request; nothing is stored.
"""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.models import CommitmentRule, PlannedItem
from app.services.repayment_candidates import repayment_candidates
from tests.integration.test_spending_paid_back import World as SpendingWorld

TODAY = date(2026, 11, 15)
FRIDAY = date(2026, 11, 6)


class World(SpendingWorld):
    def candidates(self, **kw):
        return self.as_user(lambda: repayment_candidates(self.db, self.user, today=TODAY, **kw))

    def one(self, **kw):
        [candidate] = self.candidates(**kw)
        return candidate

    def counts_as(self, tx, value):
        self.as_user(lambda: (setattr(tx, "counts_as_override", value), self.db.commit()))


@pytest.fixture
def w(client, db_session, today_is):
    today_is(TODAY)
    return World(client, db_session)


def _dinner_and_sam(w):
    dinner = w.purchase("200.00", on=FRIDAY)
    sam = w.credit("60.00", on=FRIDAY + timedelta(days=2), merchant="SAM SMITH DINNER")
    return dinner, sam


# --- scoring (AC-9 to AC-12) -----------------------------------------------------------


def test_the_dinner_is_likely_medium_and_high_with_claudes_date(w):
    """AC-9: 20 (a share) + 0 (no shared words) + 25 (two days before) + 15
    (no marks) = 60; + 15 when `spend_date` is the spend's UK day."""
    dinner, sam = _dinner_and_sam(w)
    c = w.one()
    ids = w.as_user(lambda: (str(dinner.id), str(sam.id)))
    assert (c["credit_id"], c["amount_pounds"], c["unmarked_pounds"]) == (ids[1], "60.00", "60.00")
    likely = c["likely_spend"]
    assert (likely["spend_id"], likely["score"], likely["confidence"]) == (ids[0], 60, "medium")
    assert (likely["amount_pounds"], likely["remaining_pounds"], likely["category"]) == (
        "200.00", "200.00", "Eating out")
    assert likely["reasons"] and all(isinstance(r, str) for r in likely["reasons"])
    assert c["suggested_amount_pounds"] == "60.00" and c["blocked"] is None and c["warnings"] == []
    likely = w.one(spend_date=FRIDAY)["likely_spend"]
    assert (likely["score"], likely["confidence"]) == (75, "high")


def test_an_equal_split_and_an_about_word_score_higher(w):
    w.purchase("240.00", on=FRIDAY, merchant="Pizza Express")
    w.credit("60.00", on=FRIDAY + timedelta(days=2))  # a quarter of £240
    likely = w.one(about="pizza")["likely_spend"]
    assert likely["score"] == 35 + 10 + 25 + 15


def test_a_spend_smaller_than_the_credit_is_not_a_candidate(w):
    """AC-10: a £4 coffee can't be what £60 paid back."""
    w.purchase("4.00", on=FRIDAY + timedelta(days=1), merchant="Pret")
    dinner, _ = _dinner_and_sam(w)
    c = w.one()
    assert c["likely_spend"]["spend_id"] == w.as_user(lambda: str(dinner.id))
    assert c["alternatives"] == []


def test_two_close_spends_are_medium_with_the_other_as_an_alternative(w):
    """AC-11: the dinner scores 75 with Claude's date, but Dishoom (a shared
    word, "dinner") scores 70, so it isn't 15 ahead: medium, not high."""
    w.purchase("150.00", on=FRIDAY - timedelta(days=1), merchant="Dishoom Dinner")
    _dinner_and_sam(w)
    c = w.one(spend_date=FRIDAY)
    assert (c["likely_spend"]["label"], c["likely_spend"]["score"], c["likely_spend"]["confidence"]) == (
        "Pizza Express", 75, "medium")
    assert [(a["label"], a["score"]) for a in c["alternatives"]] == [("Dishoom Dinner", 70)]


def test_below_45_there_is_no_likely_spend_only_a_fallback_category(w):
    """AC-12: 20 + 0 + 4 (18 days before) + 15 = 39."""
    w.purchase("200.00", on=FRIDAY - timedelta(days=16))
    w.credit("60.00", on=FRIDAY + timedelta(days=2))
    c = w.one()
    assert c["likely_spend"] is None and c["fallback_category"] == "Eating out"


def test_a_fully_paid_back_spend_is_never_a_candidate_even_for_pennies(w):
    """eng-a on #280: below the £1 tolerance floor, a spend with £0 left used
    to pass the room check (and divide by zero)."""
    lunch = w.purchase("12.00", on=FRIDAY)
    w.mark(w.credit("7.00", on=FRIDAY, merchant="JO"), "7.00", spend=lunch)
    w.mark(w.credit("5.00", on=FRIDAY, merchant="AL"), "5.00", spend=lunch)
    w.credit("0.50", on=FRIDAY + timedelta(days=2))
    [c] = w.candidates()
    assert (c["amount_pounds"], c["likely_spend"], c["fallback_category"]) == ("0.50", None, None)


def test_with_no_eligible_spend_there_is_no_fallback(w):
    w.credit("60.00", on=FRIDAY)
    c = w.one()
    assert (c["likely_spend"], c["fallback_category"], c["suggested_amount_pounds"]) == (None, None, "60.00")


# --- what can be a candidate (AC-13, AC-14, AC-18) ------------------------------------------


def test_a_credit_typed_as_a_transfer_is_still_listed(w):
    """AC-13 / decision 4."""
    _, sam = _dinner_and_sam(w)
    w.counts_as(sam, "transfer")
    assert w.one()["likely_spend"] is not None


@pytest.mark.parametrize("reason", ["transfer", "card_payment", "commitment", "financed"])
def test_a_debit_not_counted_as_spending_is_never_the_likely_spend(w, reason):
    """AC-13 / decisions 5 and 10."""
    dinner, _ = _dinner_and_sam(w)
    if reason in ("transfer", "card_payment"):
        w.counts_as(dinner, reason)
    else:
        def add():
            if reason == "commitment":
                w.db.add(CommitmentRule(user_id=w.user.id, direction="expense", label="Pizza Express",
                                        amount=Decimal("200"), cadence="monthly", next_date=TODAY,
                                        source="manual", status="confirmed"))
            else:
                w.db.add(PlannedItem(user_id=w.user.id, name="Dinner plan", direction="expense", kind="plan",
                                     start_date=TODAY, amount=Decimal("50"), source_transaction_id=dinner.id))
            w.db.commit()
        w.as_user(add)
    assert w.one()["likely_spend"] is None


def test_a_credit_settling_a_planned_income_is_blocked(w):
    """AC-14."""
    _, sam = _dinner_and_sam(w)

    def plan():
        w.db.add(PlannedItem(user_id=w.user.id, name="Sam owes me", direction="income", kind="one_off",
                             start_date=FRIDAY + timedelta(days=2), amount=Decimal("60")))
        w.db.commit()
    w.as_user(plan)
    assert w.one()["blocked"] == "planned_income"


def test_a_payer_with_an_income_commitment_is_warned(w):
    """AC-14."""
    _dinner_and_sam(w)

    def income():
        w.db.add(CommitmentRule(user_id=w.user.id, direction="income", label="SAM SMITH", amount=Decimal("60"),
                                cadence="monthly", next_date=TODAY + timedelta(days=20), source="detected",
                                status="suggested", match_key="income:sam smith"))
        w.db.commit()
    w.as_user(income)
    assert w.one()["warnings"] == ["income_commitment_payer"]


def test_another_users_credits_are_never_listed(client, db_session, w):
    """AC-18."""
    _dinner_and_sam(w)
    other = World(client, db_session, email="other@example.com")
    assert other.candidates() == []


# --- filters, marks and order ---------------------------------------------------------------


def test_payer_filters_the_range_defaults_to_45_days_and_newest_is_first(w):
    _dinner_and_sam(w)
    w.credit("50.00", on=FRIDAY + timedelta(days=3), merchant="JO BLOGGS")
    assert [c["payer"] for c in w.candidates()] == ["jo bloggs", "sam smith"]
    assert [c["payer"] for c in w.candidates(payer="sam")] == ["sam smith"]
    assert len(w.candidates(limit=1)) == 1
    w.credit("40.00", on=TODAY - timedelta(days=46))  # outside the default 45 days
    assert len(w.candidates()) == 2 and len(w.candidates(frm=TODAY - timedelta(days=60))) == 3


def test_marked_credits_hide_unless_asked_and_marks_shrink_what_is_left(w):
    dinner, sam = _dinner_and_sam(w)
    w.mark(sam, "60.00", spend=dinner)
    assert w.candidates() == []
    c = w.one(include_marked=True)
    assert c["unmarked_pounds"] == "0.00"
    [mark] = c["marks"]
    assert (mark["amount_pounds"], mark["spend_id"], mark["category"], mark["applied"]) == (
        "60.00", w.as_user(lambda: str(dinner.id)), None, True)

    w.counts_as(dinner, "transfer")  # no longer counted as spending: the mark nets nothing (AC-29)
    assert w.one(include_marked=True)["marks"][0]["applied"] is False
    w.counts_as(dinner, None)

    jo = w.credit("50.00", on=FRIDAY + timedelta(days=3), merchant="JO")
    likely = w.as_user(lambda: [c for c in w.candidates() if c["credit_id"] == str(jo.id)][0])["likely_spend"]
    # An equal split reads the spend's full amount (£200 / £50 = 4), not what is left (T12).
    assert (likely["remaining_pounds"], likely["score"]) == ("140.00", 35 + 25 + 10)
