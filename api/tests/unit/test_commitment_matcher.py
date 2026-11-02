"""Which transactions are a confirmed commitment's payments (T-19-1).

A merchant bills one-off purchases under the same descriptor as its
subscription, so the description key alone tags a large one-off as the
commitment and hides it from Spending. A transaction matches only when its
key matches and its amount is within max(25% of the commitment amount, GBP 5)
of some commitment with that key.
"""
import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.services.analytics.commitments import NO_COMMITMENTS, build_commitment_matcher

KEY = "expense:streamco com/uk london"


def _rule(amount, match_key=KEY, label="StreamCo", direction="expense"):
    return SimpleNamespace(
        id=uuid.uuid4(), direction=direction, label=label, match_key=match_key,
        amount=Decimal(amount),
    )


def _tx(amount, description="STREAMCO.COM/UK LONDON", ttype="debit"):
    return SimpleNamespace(
        transaction_type=ttype, merchant_name=None, description=description, amount=Decimal(amount),
    )


@pytest.mark.parametrize("commitment,paid,matches", [
    ("9.99", "9.99", True),
    ("9.99", "10.49", True),      # a price rise
    ("9.99", "14.99", True),      # GBP 5 floor (25% would be 2.50)
    ("9.99", "15.00", False),
    ("9.99", "4.99", True),
    ("9.99", "4.98", False),
    ("100.00", "125.00", True),   # 25% of 100 = 25 (more than GBP 5)
    ("100.00", "125.01", False),
    ("100.00", "75.00", True),
    ("100.00", "74.99", False),
    ("9.99", "1499.00", False),   # a one-off purchase under the same descriptor
])
def test_amount_tolerance_is_max_of_five_pounds_and_a_quarter(commitment, paid, matches):
    matcher = build_commitment_matcher([_rule(commitment)], linked_ids=set())
    assert matcher.matches(_tx(paid)) is matches


def test_the_amount_sign_of_the_transaction_does_not_matter():
    matcher = build_commitment_matcher([_rule("9.99")], linked_ids=set())
    assert matcher.matches(_tx("-9.99"))


def test_a_different_description_never_matches_whatever_the_amount():
    matcher = build_commitment_matcher([_rule("9.99")], linked_ids=set())
    assert not matcher.matches(_tx("9.99", description="OTHERCO LONDON"))


def test_two_commitments_on_one_key_each_match_their_own_amount():
    matcher = build_commitment_matcher([_rule("9.99"), _rule("59.99")], linked_ids=set())
    assert matcher.matches(_tx("9.99"))
    assert matcher.matches(_tx("59.99"))
    assert not matcher.matches(_tx("30.00"))  # between the two, outside both tolerances


def test_a_rule_without_an_amount_matches_on_its_key_alone():
    matcher = build_commitment_matcher([_rule("0")], linked_ids=set())
    assert matcher.matches(_tx("1499.00"))


def test_a_rule_linked_to_a_holding_or_loan_matches_on_its_key_alone():
    """A mortgage overpayment or an ISA lump sum under the bill's descriptor
    moves money into the holding; it is not spending."""
    linked = _rule("500.00")
    matcher = build_commitment_matcher([linked], linked_ids={linked.id})
    assert matcher.matches(_tx("5000.00"))


def test_a_label_derived_key_still_matches_with_the_amount_check():
    matcher = build_commitment_matcher([_rule("9.99", match_key=None, label="STREAMCO.COM/UK LONDON")], linked_ids=set())
    assert matcher.matches(_tx("9.99"))
    assert not matcher.matches(_tx("1499.00"))


def test_no_commitments_matches_nothing():
    assert not NO_COMMITMENTS.matches(_tx("9.99"))
    assert not build_commitment_matcher([], linked_ids=set()).matches(_tx("9.99"))
