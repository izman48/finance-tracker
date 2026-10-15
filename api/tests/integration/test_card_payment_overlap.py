"""The card-payment overlap is shown (T-12-4b; ux T-12-1 O-2, O-3, O-4).

When flagged planned card payments and projected card bills fall in the same
pay window, the planned row says so (`card_payment_overlap`) and a nudge
gives the aggregate figures from the API: "Your planned card payments
(£1,500.00) overlap your projected card bills (£640.00). nilu counts the
larger, £1,500.00, once." No overlap, no flag and no nudge. An unflagged
item is never warned about. Synthetic figures only.
"""
from datetime import timedelta

import pytest

from tests.clock import TODAY
from tests.integration.test_card_payment_once import Cards
from tests.integration.test_linked_commitment_guards import API, _bearer


@pytest.fixture
def w(client, db_session):
    world = Cards(client, db_session, email="card-overlap@example.com")
    world.setup()
    return world


def _rows(w):
    return {r["id"]: r for r in w.client.get(f"{API}/analytics/planned-items", headers=_bearer(w.web)).json()}


def _overlap_nudges(w):
    nudges = w.client.get(f"{API}/analytics/nudges", headers=_bearer(w.web)).json()
    return [n for n in nudges if n["id"].startswith("card_payment_overlap")]


def test_a_larger_planned_payment_is_flagged_and_the_nudge_says_so(w):
    item = w.planned("1500.00")
    assert _rows(w)[item["id"]]["card_payment_overlap"] is True
    (nudge,) = _overlap_nudges(w)
    assert nudge["body"] == ("Your planned card payments (£1,500.00) overlap your projected card bills (£640.00). "
                             "nilu counts the larger, £1,500.00, once.")
    assert nudge["source"] is None


def test_a_smaller_one_says_the_projection_counts(w):
    w.planned("400.00")
    (nudge,) = _overlap_nudges(w)
    assert nudge["body"] == ("Your planned card payments (£400.00) overlap your projected card bills (£640.00). "
                             "nilu counts the larger, £640.00, once.")


def test_no_overlap_no_flag_no_nudge(w):
    # After payday: a window with no projected bill.
    item = w.planned("300.00", days=15)
    assert _rows(w)[item["id"]]["card_payment_overlap"] is False
    assert _overlap_nudges(w) == []


def test_an_unflagged_item_is_never_warned_about(w):
    item = w.planned("1500.00", card=False)
    assert _rows(w)[item["id"]]["card_payment_overlap"] is False
    assert _overlap_nudges(w) == []


def test_the_nudge_id_changes_with_the_window(w):
    w.planned("1500.00")
    (nudge,) = _overlap_nudges(w)
    assert nudge["id"] == f"card_payment_overlap_{(TODAY + timedelta(days=1)).isoformat()}"
