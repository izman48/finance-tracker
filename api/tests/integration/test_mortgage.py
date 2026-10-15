"""A mortgage is a liability kind (T-12-6; ADR-002 section 8; sec T-12-6).

It is the loan form with `kind: "mortgage"`: an amortising debt in Loans and
finance whose repayment is one linked commitment, labelled "{lender}
mortgage payment" and guarded like a loan's, with its own "follows your
mortgage" message. Bounds (sec): balance up to £10m, APR 0 to 25%, paid off
within 40 years. A legacy `mortgage` asset converts by its id in one locked
transaction, so the debt counts once. Claude sees debt only as a total.

Synthetic fixture: Sample Bank, £120,000 at 4.5%, £780 a month.
"""
import time
import uuid
from datetime import timedelta
from decimal import Decimal

import pytest

from app.models import Asset, AuditEntry, Liability
from app.services.holdings.registry import kind_for
from tests.clock import TODAY
from tests.integration.test_linked_commitment_guards import API, NEXT, World, _bearer
from tests.integration.test_net_worth_liabilities import World as NetWorthWorld

MORTGAGE = {
    "kind": "mortgage", "lender": "Sample Bank", "balance": "120000.00",
    "balance_as_of": (TODAY - timedelta(days=3)).isoformat(), "apr": "4.50", "payment": "780.00",
    "start_date": NEXT.isoformat(),
}
FOLLOWS = {"code": "linked_to_liability",
           "message": "This payment follows your mortgage. Change it on Wealth, under Loans and finance."}


@pytest.fixture
def world(client, db_session):
    return World(client, db_session, email="mortgage@example.com")


def _add(world, **over):
    return world.client.post(f"{API}/liabilities", json={**MORTGAGE, **over}, headers=_bearer(world.web))


def _bill(world) -> uuid.UUID:
    res = _add(world)
    assert res.status_code == 201, res.text
    return uuid.UUID(res.json()["linked_commitment"]["id"])


# --- the kind -----------------------------------------------------------------

def test_the_registry_holds_a_mortgage_as_an_amortising_debt_with_a_repayment():
    kind = kind_for("liabilities", "mortgage")
    assert (kind.stored_type, kind.group, kind.model, kind.is_debt, kind.is_investment, kind.link_role) == (
        "mortgage", "debt", "amortisation", True, False, "repayment")


def test_adding_a_mortgage_links_its_payment_by_name(world):
    res = _add(world)
    assert res.status_code == 201, res.text
    body = res.json()
    assert (body["kind"], body["link_result"]) == ("mortgage", "created")
    assert body["linked_commitment"]["label"] == "Sample Bank mortgage payment"
    assert world.rule(uuid.UUID(body["linked_commitment"]["id"])).amount == Decimal("780.00")


def test_a_lender_rename_keeps_the_mortgage_label(world):
    bill = _bill(world)
    liability_id = world.db.query(Liability.id).scalar()
    res = world.client.patch(f"{API}/liabilities/{liability_id}", json={"lender": "Other Bank"},
                             headers=_bearer(world.web))
    assert res.status_code == 200, res.text
    assert world.rule(bill).label == "Other Bank mortgage payment"


def test_a_loans_payment_keeps_the_lender_as_its_label(world):
    assert world.loan()["linked_commitment"]["label"] == "Example Bank"


# --- bounds (sec T-12-6) --------------------------------------------------------

@pytest.mark.parametrize("over", [
    {"balance": "10000000.01"},
    {"apr": "25.01"},
    {"payment": "500.00"},
])
def test_out_of_bounds_mortgage_terms_are_422_and_write_nothing(world, over):
    assert _add(world, **over).status_code == 422
    assert world.db.query(Liability).count() == 0


def test_a_mortgage_must_clear_within_forty_years(world):
    # Interest is about £441 a month: £500 clears in about 48 years, inside
    # the general 50-year cap but past the mortgage's 40.
    res = _add(world, payment="500.00")
    assert res.status_code == 422
    assert "more than 40 years" in res.json()["detail"]


def test_a_mortgage_may_be_up_to_ten_million_but_a_loan_may_not(world):
    assert _add(world, balance="10000000.00", payment="1000000.00").status_code == 201
    loan = world.client.post(f"{API}/liabilities", json={**MORTGAGE, "kind": "loan", "balance": "1000000.01"},
                             headers=_bearer(world.web))
    assert loan.status_code == 422


def test_a_loans_apr_above_25_is_still_allowed(world):
    assert world.loan(apr="29.90")["kind"] == "loan"


def test_a_forty_year_mortgage_at_the_limits_amortises_in_under_a_second(world):
    # £10m at 25% (interest about £186,000 a month) with the largest payment.
    started = time.perf_counter()
    res = _add(world, balance="10000000.00", apr="25.00", payment="190000.00")
    assert res.status_code == 201, res.text
    assert world.client.get(f"{API}/liabilities", headers=_bearer(world.web)).status_code == 200
    assert time.perf_counter() - started < 1.0
    assert res.json()["payments_remaining"] <= 480


# --- net worth, projection, Claude ---------------------------------------------

def test_a_mortgage_counts_once_in_net_worth_and_total_owed(world):
    before = world.summary()
    _add(world)
    after = world.summary()
    assert Decimal(before["net_worth"]) - Decimal(after["net_worth"]) == Decimal("120000.00")
    assert Decimal(after["total_owed"]) - Decimal(before["total_owed"]) == Decimal("120000.00")


def test_the_projection_pays_the_mortgage_down(world):
    _add(world)
    p = world.client.get(f"{API}/analytics/net-worth-projection",
                         params={"monthly_contribution": "0", "annual_growth_pct": "0"}, headers=_bearer(world.web))
    owed = [Decimal(str(pt["liabilities"])) for pt in p.json()["timeline"][:4]]
    assert owed[0] == Decimal("120000.00")
    assert owed[0] > owed[1] > owed[2] > owed[3]


def test_claude_never_lists_a_mortgage(world):
    _add(world)
    body = world.client.get(f"{API}/holdings", headers=_bearer(world.mcp)).json()
    assert body["holdings"] == [] and "Sample Bank" not in str(body)


# --- converting a legacy mortgage asset ----------------------------------------

def test_a_legacy_mortgage_asset_converts_once(client, db_session):
    world = NetWorthWorld(client, db_session, email="mortgage-convert@example.com")
    asset_id = world.loan_asset(name="House loan", value="-120000", asset_type="mortgage")
    before = world.figures()["summary"]
    res = world.add_liability(**MORTGAGE, replaces_asset_id=asset_id)
    assert res.status_code == 201, res.text
    assert world.figures()["summary"] == before
    assert db_session.query(Asset).count() == 0
    assert world.add_liability(**MORTGAGE, replaces_asset_id=asset_id).status_code == 404
    assert db_session.query(Liability).count() == 1


# --- the payment follows the mortgage (one test per guard site) ----------------

@pytest.mark.parametrize("change", [{"amount": "700.00"}, {"next_date": (TODAY + timedelta(days=20)).isoformat()},
                                    {"status": "dismissed"}, {"cadence": "weekly"}])
def test_a_web_edit_of_the_mortgage_payment_is_409(world, change):
    bill = _bill(world)
    before = world.snapshot(bill)
    res = world.patch(bill, **change)
    assert (res.status_code, res.json()["detail"]) == (409, FOLLOWS)
    assert world.snapshot(bill) == before


def test_skipping_the_mortgage_payment_is_409(world):
    bill = _bill(world)
    res = world.client.post(f"{API}/analytics/commitments/{bill}/skip", headers=_bearer(world.web))
    assert (res.status_code, res.json()["detail"]) == (409, FOLLOWS)


@pytest.mark.parametrize("dry_run", [True, False])
def test_claude_cannot_update_or_dismiss_the_mortgage_payment(world, dry_run):
    bill = _bill(world)
    before, audits = world.snapshot(bill), world.audit_count()
    assert world.update(bill, dry_run=dry_run, amount="700.00").status_code == 409
    assert world.dismiss(bill, dry_run=dry_run).status_code == 409
    assert (world.snapshot(bill), world.audit_count()) == (before, audits)


def test_undoing_an_earlier_claude_change_cannot_rewrite_the_mortgage_payment(world, db_session):
    bill = world.commitment(label="Sample Bank DD", amount="700.00")
    assert world.update(bill, dry_run=False, amount="780.00").status_code == 200
    candidate = _add(world, commitment_choice=str(bill))
    assert candidate.status_code == 201, candidate.text
    audit_id = db_session.query(AuditEntry.id).filter(AuditEntry.target_id == bill).scalar()
    res = world.client.post(f"{API}/audit/{audit_id}/undo", headers=_bearer(world.web))
    assert res.status_code == 409
    assert world.rule(bill).amount == Decimal("780.00")


def test_renaming_the_mortgage_payment_is_allowed(world):
    assert world.patch(_bill(world), label="House").status_code == 200


def test_the_list_marks_the_payment_as_following_a_mortgage(world):
    bill = _bill(world)
    loan_bill = world.linked_bill()
    rows = {r["id"]: r for r in world.client.get(f"{API}/analytics/commitments", headers=_bearer(world.web)).json()}
    assert (rows[str(bill)]["linked_liability"], rows[str(bill)]["linked_mortgage"]) == (True, True)
    assert (rows[str(loan_bill)]["linked_liability"], rows[str(loan_bill)]["linked_mortgage"]) == (True, False)


def test_a_mortgage_named_after_a_card_is_never_tied_to_it(world):
    # "American Express mortgage payment" starts with a card descriptor:
    # link_card_commitments must skip it, or the card's repayment would
    # replace it in safe-to-spend.
    world.amex_card()
    before = Decimal(world.summary()["committed_before_payday"])
    res = _add(world, lender="American Express")
    bill = uuid.UUID(res.json()["linked_commitment"]["id"])
    assert world.rule(bill).card_account_id is None
    assert Decimal(world.summary()["committed_before_payday"]) - before == Decimal("780.00")
