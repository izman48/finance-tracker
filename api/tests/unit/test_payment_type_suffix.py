"""Bank payment-type suffixes are not part of a payee's name (T-25-1).

Banks append how a payment moved (STO, FT, DDR, BGC, CPM, SO, DD, "FIRST
DDR PAYMENT") to the description, and it changes when the payment method
does. Only trailing tokens are dropped, never the whole name.
"""
import pytest

from app.services.analytics.commitments import _normalise_merchant


@pytest.mark.parametrize("raw,expected", [
    ("ACME LETTINGS RENT 12HIGHSTREE STO", "ACME LETTINGS RENT 12HIGHSTREE"),
    ("ACME LETTINGS RENT 12HIGHSTREE FT", "ACME LETTINGS RENT 12HIGHSTREE"),
    ("LENDCO BANK UUID-55500011122 FIRST DDR PAYMENT DDR", "LENDCO BANK"),
    ("LENDCO BANK UUID-55500011122 DDR", "LENDCO BANK"),
    ("LENDCO BANK FIRST PAYMENT", "LENDCO BANK"),
    ("SMITH J RENT BGC", "SMITH J RENT"),
    ("VEG BOX ON 11 NOV CPM", "VEG BOX"),
    ("GYMCO SO", "GYMCO"),
    ("WATERCO DD", "WATERCO"),
    ("watercO dd", "WATERCO"),
])
def test_trailing_payment_type_tokens_are_dropped(raw, expected):
    assert _normalise_merchant(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("DD SHOP LONDON", "DD SHOP LONDON"),          # only trailing tokens
    ("FT BOOKSHOP", "FT BOOKSHOP"),
    ("SO", "SO"),                                   # never strips the whole name
    ("DDR", "DDR"),
    ("STREAMCO.COM/UK LONDON", "STREAMCO COM/UK LONDON"),
    ("SOFT DRINKS CO", "SOFT DRINKS CO"),           # whole tokens only
])
def test_names_are_otherwise_left_alone(raw, expected):
    assert _normalise_merchant(raw) == expected
