"""Repayment settings validation (T-10-4a).

- `scheduled` only on a card the user marked as instalment-type; a card
  already on `scheduled` keeps working and is flagged "fix this".
- Role, strategy and cadence are enums on write; legacy free text still
  reads (200) and computes fail-safe.
- Repayment fields are for credit accounts only.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.models import AccountSetting
from app.services import analytics_service as svc
from app.services.analytics.common import _add_months
from tests.clock import TODAY
from tests.integration.test_card_statements_api import API, Person


@pytest.fixture
def alice(client, db_session):
    return Person(client, db_session, "alice@example.com")


def _settings(person, account_id=None, **body):
    return person.client.patch(f"{API}/analytics/accounts/{account_id or person.card_id}/settings",
                               json=body, headers=person.headers)


def _stored(db, person, account_id=None):
    return db.execute(
        text("SELECT * FROM account_settings WHERE account_id = :a"),
        {"a": (account_id or person.card_id).hex},
    ).fetchall()


def _seed(person, db, account_id=None, **fields):
    with person.key():
        db.add(AccountSetting(user_id=person.user_id, account_id=account_id or person.card_id, **fields))
        db.commit()


def _summary_account(person, account_id=None):
    accounts = person.client.get(f"{API}/analytics/summary", headers=person.headers).json()["accounts"]
    return next(a for a in accounts if a["id"] == str(account_id or person.card_id))


# --- scheduled only on instalment-type credit -------------------------------------


def test_scheduled_strategy_rejected_for_standard_credit_card(alice, db_session):
    _seed(alice, db_session, role="credit", repayment_strategy="full_balance", repayment_cadence="end_of_month")
    before = _stored(db_session, alice)

    res = _settings(alice, repayment_strategy="scheduled")

    assert res.status_code == 422
    assert _stored(db_session, alice) == before


def test_a_card_marked_instalment_type_may_use_scheduled(alice):
    assert _settings(alice, instalment_card=True, repayment_strategy="scheduled").status_code == 200
    assert _summary_account(alice)["instalment_card"] is True


def test_instalment_type_is_off_by_default(alice):
    assert _settings(alice, repayment_strategy="full_balance").status_code == 200
    assert _summary_account(alice)["instalment_card"] is False


def test_a_standard_card_already_on_scheduled_keeps_working_and_is_flagged(alice, db_session):
    _seed(alice, db_session, role="credit", repayment_strategy="scheduled")

    unchanged = _settings(alice, repayment_strategy="scheduled", pay_from_account_id=str(alice.current_id))
    other = _settings(alice, repayment_day=5)

    assert (unchanged.status_code, other.status_code) == (200, 200)
    assert _summary_account(alice)["repayment_fix_needed"] is True


def test_moving_off_scheduled_clears_the_flag(alice, db_session):
    _seed(alice, db_session, role="credit", repayment_strategy="scheduled")

    assert _settings(alice, repayment_strategy="statement_balance").status_code == 200
    assert _summary_account(alice)["repayment_fix_needed"] is False


def test_unmarking_an_instalment_card_that_is_on_scheduled_is_refused(alice, db_session):
    _seed(alice, db_session, role="credit", repayment_strategy="scheduled", instalment_card=True)
    before = _stored(db_session, alice)

    assert _settings(alice, instalment_card=False).status_code == 422
    assert _stored(db_session, alice) == before


# --- enums on write ------------------------------------------------------------------


@pytest.mark.parametrize("body", [
    {"role": "owner"},
    {"repayment_strategy": "mystery"},
    {"repayment_strategy": "FULL_BALANCE"},
    {"repayment_strategy": None},
    {"repayment_cadence": "fortnightly"},
    {"repayment_cadence": "Monthly"},
], ids=lambda b: f"{next(iter(b))}={next(iter(b.values()))}")
def test_role_strategy_and_cadence_are_enums_on_write(alice, db_session, body):
    _seed(alice, db_session, role="credit")
    before = _stored(db_session, alice)

    assert _settings(alice, **body).status_code == 422
    assert _stored(db_session, alice) == before


@pytest.mark.parametrize("strategy", ["full_balance", "fixed", "installments", "minimum_percent", "statement_balance"])
@pytest.mark.parametrize("cadence", ["monthly", "end_of_month", "every_n_months", "weekly", "card_due_date"])
def test_every_known_strategy_and_cadence_is_accepted(alice, strategy, cadence):
    assert _settings(alice, repayment_strategy=strategy, repayment_cadence=cadence).status_code == 200


# --- repayment fields are for credit accounts only -------------------------------------


@pytest.mark.parametrize("body", [
    {"repayment_strategy": "fixed"},
    {"repayment_cadence": "monthly"},
    {"repayment_day": 5},
    {"repayment_installments": 3},
    {"repayment_fixed_amount": "100.00"},
    {"instalment_card": True},
], ids=lambda b: next(iter(b)))
def test_non_credit_account_has_no_repayment_plan(alice, db_session, body):
    """The API half: a current account can't be given repayment settings
    (T-10-4b clears the ones stored today)."""
    before = _stored(db_session, alice, alice.current_id)

    assert _settings(alice, alice.current_id, **body).status_code == 422
    assert _stored(db_session, alice, alice.current_id) == before


def test_moving_a_card_to_another_role_with_repayment_fields_is_refused(alice, db_session):
    assert _settings(alice, role="spending", repayment_cadence="monthly").status_code == 422


def test_non_credit_settings_without_repayment_fields_still_save(alice):
    assert _settings(alice, alice.current_id, role="spending", overdraft_limit="500").status_code == 200
    assert _settings(alice, alice.current_id, role="savings").status_code == 200


# --- legacy free text reads and computes fail-safe ---------------------------------------


def test_legacy_free_text_settings_still_read(alice, db_session):
    _seed(alice, db_session, role="owner", repayment_strategy="weird", repayment_cadence="fortnightly")

    for path in ("/analytics/summary", "/analytics/forecast", "/banking/accounts", "/analytics/net-worth-position"):
        assert alice.client.get(f"{API}{path}", headers=alice.headers).status_code == 200, path
    # An unknown role falls back to the account type's default: a card stays credit.
    assert _summary_account(alice)["role"] == "credit"


@pytest.mark.parametrize("strategy, first_payment", [
    ("full_balance", Decimal("6000")), ("weird", Decimal("6000")), ("fixed", Decimal("100")),
])
def test_an_unknown_cadence_on_a_credit_card_pays_at_month_end(alice, db_session, strategy, first_payment):
    """Lead decision (#175): fail-safe, overstates. Before, no payment at all."""
    from app.models import User

    _seed(alice, db_session, role="credit", repayment_strategy=strategy, repayment_cadence="fortnightly",
          repayment_fixed_amount=Decimal("100"))
    with alice.key():
        events = svc.repayment_events(db_session, db_session.get(User, alice.user_id), TODAY, TODAY + timedelta(days=40))

    month_end = _add_months(TODAY.replace(day=1), 1) - timedelta(days=1)
    assert (events[0]["due_date"], events[0]["amount"]) == (month_end, first_payment)
