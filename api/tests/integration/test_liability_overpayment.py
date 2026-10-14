"""Overpayment calculator (T-10-11; liabilities spec stage 4).

Read-only: nothing is stored. A lump sum paid off today, with the payment
unchanged, shortens the schedule and cuts the interest. The settlement figure
(paying the whole loan off early) adds up to 58 days' interest, the most a
UK lender may charge under the early settlement rules, at the effective APR.
The lump sum must be more than £0 and at most the settlement figure. The
copy states facts only and never recommends a choice (no advice).

Synthetic fixture: £9,000 at £200 a month, 11% APR. Hand-checked:
no overpayment, 58 payments and £2,483.22 interest; after a £2,000 lump sum,
42 payments and £1,390.96 interest, so 16 payments and £1,092.26 saved.
Settlement: 9,000 x 1.11^(58/365) = £9,150.49 (£150.49 interest).
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.models import CommitmentRule, Liability
from app.services.analytics.common import _add_months
from tests.clock import TODAY
from tests.integration.test_oauth import _bearer, _web_login

API = "/api/v1"
START = TODAY + timedelta(days=10)
LOAN = {
    "kind": "loan", "lender": "Example Bank", "balance": "9000.00",
    "balance_as_of": (TODAY - timedelta(days=5)).isoformat(), "apr": "11.00", "payment": "200.00",
    "start_date": START.isoformat(),
}


@pytest.fixture
def user(client):
    token = _web_login(client, "overpay@example.com")
    created = client.post(f"{API}/liabilities", json=LOAN, headers=_bearer(token))
    assert created.status_code == 201, created.text
    return token, created.json()["id"]


def _overpay(client, token, liability_id, lump_sum):
    return client.get(f"{API}/liabilities/{liability_id}/overpayment",
                      params={"lump_sum": lump_sum}, headers=_bearer(token))


def test_overpayment_reduces_term_and_interest(client, user):
    token, lid = user
    res = _overpay(client, token, lid, "2000.00")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["lump_sum"] == "2000.00"
    assert (body["payments_before"], body["payments_after"], body["payments_saved"]) == (58, 42, 16)
    assert Decimal(body["interest_before"]) == Decimal("2483.22")
    assert Decimal(body["interest_after"]) == Decimal("1390.96")
    assert Decimal(body["interest_saved"]) == Decimal("1092.26")
    assert body["payoff_date_before"] == _add_months(START, 57).isoformat()
    assert body["payoff_date_after"] == _add_months(START, 41).isoformat()


def test_settlement_figure_includes_up_to_58_days_interest(client, user):
    token, lid = user
    body = _overpay(client, token, lid, "100.00").json()
    assert Decimal(body["settlement_figure"]) == Decimal("9150.49")
    assert Decimal(body["settlement_interest"]) == Decimal("150.49")


def test_paying_the_settlement_figure_clears_the_loan(client, user):
    token, lid = user
    body = _overpay(client, token, lid, "9150.49").json()
    assert body["payments_after"] == 0
    assert Decimal(body["interest_saved"]) == Decimal("2483.22")
    assert body["payoff_date_after"] is None


@pytest.mark.parametrize("lump_sum", ["0", "-5.00", "9150.50", "100.001", "abc"])
def test_a_lump_sum_must_be_above_zero_and_at_most_the_settlement_figure(client, user, lump_sum):
    token, lid = user
    assert _overpay(client, token, lid, lump_sum).status_code == 422


def test_it_writes_nothing(client, user, db_session):
    token, lid = user
    def counts():
        return (db_session.execute(select(func.count()).select_from(Liability)).scalar(),
                db_session.execute(select(func.count()).select_from(CommitmentRule)).scalar())
    before = counts()
    _overpay(client, token, lid, "2000.00")
    assert counts() == before
    assert client.get(f"{API}/liabilities/{lid}", headers=_bearer(token)).json()["balance"] == "9000.00"


def test_another_users_liability_is_a_404(client, user):
    _, lid = user
    other = _web_login(client, "other-overpay@example.com")
    assert _overpay(client, other, lid, "100.00").status_code == 404
    assert _overpay(client, other, "00000000-0000-0000-0000-0000000000ab", "100.00").status_code == 404


def test_an_irregular_loan_has_no_schedule_to_shorten(client):
    token = _web_login(client, "irregular-overpay@example.com")
    lid = client.post(f"{API}/liabilities", json={**LOAN, "payment": None, "opted_out": True},
                      headers=_bearer(token)).json()["id"]
    res = _overpay(client, token, lid, "100.00")
    assert res.status_code == 422
    assert res.json()["detail"] == "This loan has no repayment schedule, so there is nothing to work out."


def test_the_answer_states_facts_and_never_recommends(client, user):
    token, lid = user
    body = _overpay(client, token, lid, "2000.00").json()
    assert body["note"] == (
        "Money kept in savings could earn interest instead. nilu shows the figures; the choice is yours."
    )
    assert "should" not in body["note"].lower() and "recommend" not in body["note"].lower()
