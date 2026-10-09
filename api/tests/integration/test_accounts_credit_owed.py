"""GET /banking/accounts reports money owed with one sign (T-07-3).

`current_balance` stays raw (as the provider reported it); `credit_owed` is
positive for money owed on every provider, and null for non-credit accounts.
"""
from decimal import Decimal

from app.core import user_crypto
from app.models import Account
from tests.integration.test_transactions_endpoint import _account, _setup


def _card(db, user_id, provider, raw):
    acc = _account(db, user_id, atype="CREDIT_CARD", name=provider, balance=raw)
    acc.provider_name = provider
    db.commit()
    return acc


def test_credit_owed_is_positive_for_amex_monzo_and_barclaycard(client, db_session):
    user, ctx = _setup(client, db_session)
    try:
        _account(db_session, user.id, name="Current", balance="1000.00")
        _card(db_session, user.id, "AMEX", "600.00")
        _card(db_session, user.id, "MONZO", "-400.00")
        _card(db_session, user.id, "BARCLAYCARD", "200.00")
    finally:
        user_crypto.current_dek.reset(ctx)

    res = client.get("/api/v1/banking/accounts")
    assert res.status_code == 200, res.text
    rows = {a["display_name"]: a for a in res.json()}
    assert Decimal(rows["AMEX"]["credit_owed"]) == Decimal("600.00")
    assert Decimal(rows["MONZO"]["credit_owed"]) == Decimal("400.00")
    assert Decimal(rows["BARCLAYCARD"]["credit_owed"]) == Decimal("200.00")
    assert rows["Current"]["credit_owed"] is None
    # Raw balance untouched: nothing stored or reported is rewritten.
    assert rows["MONZO"]["current_balance"] == -400.0


def test_raw_balance_is_never_rewritten_by_reading(client, db_session):
    """Reading (any number of times) normalises in memory only: the stored
    value is still the provider's raw number, so the next sync cannot meet an
    already-flipped value and flip it again."""
    user, ctx = _setup(client, db_session)
    try:
        card = _card(db_session, user.id, "MONZO", "-400.00")
    finally:
        user_crypto.current_dek.reset(ctx)

    for _ in range(2):
        assert client.get("/api/v1/banking/accounts").status_code == 200
        assert client.get("/api/v1/analytics/summary").status_code == 200

    ctx = user_crypto.current_dek.set(_dek(client))
    try:
        db_session.expire_all()
        assert db_session.get(Account, card.id).current_balance == Decimal("-400.00")
    finally:
        user_crypto.current_dek.reset(ctx)


def _dek(client):
    from tests.integration.test_transactions_endpoint import _dek_from_token

    return _dek_from_token(client.headers["Authorization"].removeprefix("Bearer "))
