"""Liabilities API (T-10-7a; liabilities spec stage 1; sec S-1 to S-5).

A liability is a debt the user enters by hand (TrueLayer has no loan data):
a loan, retail finance or buy-now-pay-later. Lender, balance, APR and payment
are DEK-encrypted. The start date is the first payment and sets the payment
day (ux spec A6). Next payment, payoff date, interest left and total cost are
computed on read from the balance "as of" a date and are never accepted from
the client. "I repay this loan irregularly" (`opted_out`) makes the payment
optional and the schedule figures null.

Until a liability is linked to a commitment (T-10-8) nothing proves a payment
was made, so today's balance is the entered balance (fail-safe: never assume
payments that may not have happened). Every route is web session only and
loads by id and user; another user's id gets the same 404 as an unknown one.
A Claude token is refused (test_oauth.py, test_mcp_token_is_refused_everywhere_else).

Synthetic fixture (public repo): £9,000 at £200 a month, 11% APR, which the
hand-checked schedule in tests/unit/test_amortisation.py clears in 58
payments with £2,483.22 interest.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select, text

from app.models import Liability, User
from app.routers import liabilities as liabilities_router
from app.services import liabilities as liabilities_service
from app.services.analytics.common import _add_months
from tests.clock import TODAY
from tests.integration.test_oauth import PASSWORD, _bearer, _web_login

API = "/api/v1"
AS_OF = TODAY - timedelta(days=5)
# Payments start in 10 days, so that is the next payment.
START = TODAY + timedelta(days=10)


def loan(**overrides) -> dict:
    body = {
        "kind": "loan",
        "lender": "Example Bank",
        "balance": "9000.00",
        "balance_as_of": AS_OF.isoformat(),
        "apr": "11.00",
        "payment": "200.00",
        "start_date": START.isoformat(),
    }
    body.update(overrides)
    return {k: v for k, v in body.items() if v is not None}


class User_:
    def __init__(self, client, email):
        self.client = client
        self.token = _web_login(client, email)

    def create(self, **overrides):
        return self.client.post(f"{API}/liabilities", json=loan(**overrides), headers=_bearer(self.token))

    def list(self):
        return self.client.get(f"{API}/liabilities", headers=_bearer(self.token))

    def get(self, liability_id):
        return self.client.get(f"{API}/liabilities/{liability_id}", headers=_bearer(self.token))

    def patch(self, liability_id, **body):
        return self.client.patch(f"{API}/liabilities/{liability_id}", json=body, headers=_bearer(self.token))

    def delete(self, liability_id):
        return self.client.delete(f"{API}/liabilities/{liability_id}", headers=_bearer(self.token))


@pytest.fixture
def alice(client):
    return User_(client, "alice@example.com")


@pytest.fixture
def bob(client):
    return User_(client, "bob@example.com")


def _rows(db) -> int:
    return db.execute(select(func.count()).select_from(Liability)).scalar()


# --------------------------------------------------------------------------- #
# Create and read
# --------------------------------------------------------------------------- #
def test_create_returns_the_terms_and_the_derived_figures(alice):
    res = alice.create()
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["kind"] == "loan"
    assert body["lender"] == "Example Bank"
    assert Decimal(body["balance"]) == Decimal("9000.00")
    assert body["balance_as_of"] == AS_OF.isoformat()
    assert Decimal(body["apr"]) == Decimal("11.00")
    assert Decimal(body["payment"]) == Decimal("200.00")
    assert body["cadence"] == "monthly"
    assert body["start_date"] == START.isoformat()
    assert body["end_date"] is None
    assert body["opted_out"] is False
    assert body["next_payment_date"] == START.isoformat()
    assert body["payments_remaining"] == 58
    assert body["payoff_date"] == _add_months(START, 57).isoformat()
    assert Decimal(body["interest_remaining"]) == Decimal("2483.22")
    assert Decimal(body["total_cost"]) == Decimal("11483.22")
    assert body["balance_stale"] is False


def test_todays_balance_is_the_entered_balance_until_payments_are_linked(alice):
    # No linked commitment yet (T-10-8), so no payment is assumed to have
    # been made since the as-of date: the debt is never understated.
    body = alice.create(balance_as_of=(TODAY - timedelta(days=60)).isoformat(),
                        start_date=(TODAY - timedelta(days=400)).isoformat()).json()
    assert Decimal(body["current_balance"]) == Decimal("9000.00")


def test_the_next_payment_is_the_first_on_the_start_dates_cycle_after_the_as_of_date(alice):
    start = _add_months(TODAY, -14)
    as_of = TODAY - timedelta(days=1)
    body = alice.create(start_date=start.isoformat(), balance_as_of=as_of.isoformat()).json()
    expected = next(d for d in (_add_months(start, n) for n in range(30)) if d > as_of)
    assert body["next_payment_date"] == expected.isoformat()


def test_an_old_balance_never_shows_a_next_payment_in_the_past(alice):
    # eng-a on #174: T-10-8 seeds the linked commitment from this date. The
    # schedule runs from today's balance (the entered one until payments are
    # linked), so payments_remaining and payoff date count from today too.
    start = _add_months(TODAY, -14)
    body = alice.create(start_date=start.isoformat(), balance_as_of=(TODAY - timedelta(days=40)).isoformat()).json()
    expected = next(d for d in (_add_months(start, n) for n in range(30)) if d >= TODAY)
    assert body["next_payment_date"] == expected.isoformat()
    assert body["payments_remaining"] == 58
    assert body["payoff_date"] == _add_months(expected, 57).isoformat()


def test_a_row_whose_schedule_no_longer_clears_shows_null_figures_not_a_500(alice, db_session, monkeypatch):
    alice.create(lender="A")
    alice.create(lender="B")
    # If the cap or rounding ever changes, a stored row could stop clearing.
    monkeypatch.setattr(liabilities_service, "MAX_SCHEDULE_YEARS", 1)
    res = alice.list()
    assert res.status_code == 200
    rows = res.json()
    assert [r["payoff_date"] for r in rows] == [None, None]
    assert all(Decimal(r["current_balance"]) == Decimal("9000.00") for r in rows)


def test_creating_past_the_per_user_cap_is_409_and_writes_nothing(alice, db_session, monkeypatch):
    monkeypatch.setattr(liabilities_router, "LIABILITIES_PER_USER_MAX", 2)
    assert alice.create().status_code == 201
    assert alice.create().status_code == 201
    res = alice.create()
    assert res.status_code == 409
    assert _rows(db_session) == 2


def test_the_per_user_cap_is_50():
    assert liabilities_router.LIABILITIES_PER_USER_MAX == 50


def test_irregular_repayment_needs_no_payment_and_has_no_schedule(alice):
    res = alice.create(payment=None, opted_out=True)
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["opted_out"] is True
    assert body["payment"] is None
    assert Decimal(body["current_balance"]) == Decimal("9000.00")
    for figure in ("next_payment_date", "payments_remaining", "payoff_date", "interest_remaining", "total_cost"):
        assert body[figure] is None, figure


def test_a_payment_is_required_unless_repaid_irregularly(alice, db_session):
    res = alice.create(payment=None)
    assert res.status_code == 422
    assert "I repay this loan irregularly" in res.text
    assert _rows(db_session) == 0


@pytest.mark.parametrize("cadence, step", [("weekly", 7), ("fortnightly", 14), ("four_weekly", 28)])
def test_weekly_cadences_step_from_the_start_date(alice, cadence, step):
    body = alice.create(cadence=cadence, payment="100.00").json()
    assert body["cadence"] == cadence
    assert body["next_payment_date"] == START.isoformat()
    assert body["payoff_date"] == (START + timedelta(days=step * (body["payments_remaining"] - 1))).isoformat()


@pytest.mark.parametrize("days_old, stale", [(90, False), (91, True)])
def test_a_balance_older_than_90_days_asks_for_an_update(alice, days_old, stale):
    as_of = TODAY - timedelta(days=days_old)
    body = alice.create(balance_as_of=as_of.isoformat()).json()
    assert body["balance_stale"] is stale


def test_list_holds_only_the_callers_liabilities_highest_apr_first(alice, bob):
    # ux L-1: APR high to low; equal APR, higher balance first; then lender A to Z.
    alice.create(lender="Low", apr="4.50")
    alice.create(lender="high", apr="29.90", payment="400.00")
    alice.create(lender="Mid small b", apr="11.00", balance="1500.00")
    alice.create(lender="Mid small a", apr="11.00", balance="1500.00")
    alice.create(lender="Mid big", apr="11.00")
    bob.create(lender="Not yours")

    res = alice.list()
    assert res.status_code == 200
    assert [x["lender"] for x in res.json()] == ["high", "Mid big", "Mid small a", "Mid small b", "Low"]


def test_get_one(alice):
    created = alice.create().json()
    res = alice.get(created["id"])
    assert res.status_code == 200
    assert res.json() == created


def test_kinds_this_sprint_are_loan_finance_and_bnpl(alice):
    for kind in ("loan", "finance", "bnpl"):
        assert alice.create(kind=kind).status_code == 201, kind


# --------------------------------------------------------------------------- #
# Edit and delete
# --------------------------------------------------------------------------- #
def test_edit_recomputes_the_derived_figures(alice):
    created = alice.create().json()
    res = alice.patch(created["id"], payment="400.00", lender="Renamed")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["lender"] == "Renamed"
    assert Decimal(body["payment"]) == Decimal("400.00")
    assert body["payments_remaining"] < 58
    assert Decimal(body["interest_remaining"]) < Decimal("2483.22")


def test_edit_cannot_clear_a_required_term(alice, db_session):
    created = alice.create().json()
    for field in ("lender", "balance", "apr", "payment", "balance_as_of", "kind", "cadence", "start_date", "opted_out"):
        assert alice.patch(created["id"], **{field: None}).status_code == 422, field
    assert alice.get(created["id"]).json() == created


def test_edit_checks_the_dates_against_the_stored_terms(alice):
    created = alice.create(start_date=(TODAY - timedelta(days=400)).isoformat()).json()
    res = alice.patch(created["id"], end_date=(TODAY - timedelta(days=500)).isoformat())
    assert res.status_code == 422
    assert alice.get(created["id"]).json() == created


def test_opting_out_by_edit_clears_the_schedule_and_opting_back_in_needs_a_payment(alice):
    created = alice.create().json()
    opted = alice.patch(created["id"], opted_out=True, payment=None)
    assert opted.status_code == 200, opted.text
    assert opted.json()["payoff_date"] is None

    res = alice.patch(created["id"], opted_out=False)
    assert res.status_code == 422
    assert alice.get(created["id"]).json() == opted.json()


def test_delete(alice, db_session):
    created = alice.create().json()
    assert alice.delete(created["id"]).status_code == 204
    assert alice.get(created["id"]).status_code == 404
    assert _rows(db_session) == 0


# --------------------------------------------------------------------------- #
# Payments that never clear the balance
# --------------------------------------------------------------------------- #
def test_a_payment_that_does_not_cover_the_interest_is_refused_with_a_clear_message(alice, db_session):
    res = alice.create(payment="78.61")
    assert res.status_code == 422
    assert res.json()["detail"] == (
        "A payment of £78.61 doesn't cover the interest of £78.61 it would be charged. Increase the payment."
    )
    assert _rows(db_session) == 0


def test_a_payment_of_interest_plus_a_penny_is_refused_not_looped(alice, db_session):
    res = alice.create(payment="78.62")
    assert res.status_code == 422
    assert "more than 50 years" in res.json()["detail"]
    assert _rows(db_session) == 0


def test_an_edit_that_stops_the_balance_clearing_is_refused_and_writes_nothing(alice):
    created = alice.create().json()
    res = alice.patch(created["id"], apr="30.00", payment="100.00")
    assert res.status_code == 422
    assert alice.get(created["id"]).json() == created


# --------------------------------------------------------------------------- #
# Input validation (S-5) and mass assignment (S-4)
# --------------------------------------------------------------------------- #
INVALID = [
    ("balance", 9000.5),            # a JSON float can't hold money exactly
    ("balance", "9000.005"),        # more than 2 decimal places
    ("balance", "0"),
    ("balance", "-1.00"),
    ("balance", "1000000.01"),
    ("payment", "0.00"),
    ("payment", 200.0),
    ("payment", "1000000.01"),
    ("apr", "-0.01"),
    ("apr", "100.01"),
    ("apr", 11.0),
    ("kind", "card_plan"),          # waits for stage 5
    ("kind", "mortgage"),           # later
    ("kind", "revolving"),
    ("cadence", "yearly"),
    ("cadence", "custom_days"),
    ("opted_out", "yes"),
    ("lender", ""),
    ("lender", "x" * 101),
    ("balance_as_of", (TODAY + timedelta(days=1)).isoformat()),
    ("start_date", None),
    ("start_date", (TODAY + timedelta(days=367)).isoformat()),
]


@pytest.mark.parametrize("field, value", INVALID, ids=[f"{f}-{i}" for i, (f, _) in enumerate(INVALID)])
def test_invalid_input_is_refused(alice, db_session, field, value):
    assert alice.create(**{field: value}).status_code == 422
    assert _rows(db_session) == 0


def test_end_date_must_be_after_start_date(alice, db_session):
    assert alice.create(end_date=START.isoformat()).status_code == 422
    assert _rows(db_session) == 0


@pytest.mark.parametrize("field, value", [
    ("user_id", "00000000-0000-0000-0000-000000000001"),
    ("id", "00000000-0000-0000-0000-000000000002"),
    ("linked_commitment_id", "00000000-0000-0000-0000-000000000003"),
    ("payoff_date", "2030-01-01"),
    ("next_payment_date", "2030-01-01"),
    ("interest_remaining", "1.00"),
    ("total_cost", "1.00"),
    ("current_balance", "1.00"),
])
def test_server_owned_and_derived_fields_are_refused(alice, db_session, field, value):
    assert alice.create(**{field: value}).status_code == 422
    created = alice.create().json()
    assert alice.patch(created["id"], **{field: value}).status_code == 422
    assert alice.get(created["id"]).json() == created


# --------------------------------------------------------------------------- #
# Ownership (S-3) and auth
# --------------------------------------------------------------------------- #
def test_another_users_liability_is_a_404_like_an_unknown_one_and_nothing_changes(alice, bob):
    theirs = bob.create(lender="Bob's loan").json()
    unknown = "00000000-0000-0000-0000-0000000000ff"

    for liability_id in (theirs["id"], unknown):
        assert alice.get(liability_id).status_code == 404
        assert alice.patch(liability_id, payment="300.00").status_code == 404
        assert alice.delete(liability_id).status_code == 404
    assert alice.get(theirs["id"]).json() == alice.get(unknown).json()

    assert bob.get(theirs["id"]).json() == theirs


def test_every_route_needs_a_web_session(client, alice):
    created = alice.create().json()
    calls = [
        ("get", "/liabilities", None),
        ("post", "/liabilities", loan()),
        ("get", f"/liabilities/{created['id']}", None),
        ("patch", f"/liabilities/{created['id']}", {"payment": "300.00"}),
        ("delete", f"/liabilities/{created['id']}", None),
    ]
    for method, path, body in calls:
        kwargs = {"json": body} if body is not None else {}
        assert getattr(client, method)(f"{API}{path}", **kwargs).status_code == 401, (method, path)


# --------------------------------------------------------------------------- #
# Data protection (S-1, S-2)
# --------------------------------------------------------------------------- #
def test_money_and_lender_are_encrypted_at_rest(alice, db_session):
    alice.create(lender="Example Bank")
    row = db_session.execute(text("SELECT lender, balance, apr, payment FROM liabilities")).one()
    for stored in row:
        assert "Example" not in stored and "9000" not in stored and "11.00" not in stored and "200.00" not in stored


def test_deleting_the_account_removes_its_liabilities_and_keeps_other_users(client, alice, bob, db_session):
    alice.create()
    bob.create()
    db_session.commit()
    # Test SQLite doesn't enforce foreign keys unless asked; production
    # Postgres does. Turn them on so the ON DELETE CASCADE is what's tested.
    connection = db_session.connection()
    connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    try:
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1  # the control is on
        res = client.post(f"{API}/auth/delete-account", json={"password": PASSWORD}, headers=_bearer(alice.token))
        assert res.status_code == 200, res.text
        alice_id = db_session.execute(select(User.id).where(User.email == "alice@example.com")).scalar()
        assert alice_id is None
        bob_id = db_session.execute(select(User.id).where(User.email == "bob@example.com")).scalar()
        owners = db_session.execute(select(Liability.user_id)).scalars().all()
        assert owners == [bob_id]
    finally:
        db_session.commit()
        db_session.connection().exec_driver_sql("PRAGMA foreign_keys=OFF")
