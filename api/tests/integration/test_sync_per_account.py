"""One account's failure no longer aborts its connection's sync (T-08-24).

Production, 2026-10-11: Monzo's card transactions endpoint answered 403 and
Revolut's 501 (Revolut via TrueLayer has no card transactions). One card
failing aborted the whole connection's transaction sync, so the current
account and savings got nothing and last_synced_at stuck; and a timeout
(an httpx error with no message) surfaced as a 500.

Now each account is fetched on its own. An account whose endpoint fails
(403, 404, 501, a timeout, any error) is skipped, logged by type and status
only, and counted in `accounts_skipped`; the others sync and the
connection is `synced` with last_synced_at stamped. Only if every account
fails is the connection `failed`. No sync route returns 500: a total
upstream failure is a 502 in fixed words.
"""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx
import pytest

from app.core import user_crypto
from app.models import Account, BankConnection, Transaction
from app.services import truelayer as truelayer_module
from app.services.truelayer import truelayer_service
from tests.integration.test_bank_reauth import _seed_expired_connection

TX = {"transaction_id": "tx-cur-1", "transaction_type": "DEBIT", "amount": -12.5, "currency": "GBP",
      "description": "SHOP", "timestamp": "2026-10-10T10:00:00Z"}


def _connection_with_card(client, db_session):
    conn_id, dek = _seed_expired_connection(client, db_session)
    ctx = user_crypto.current_dek.set(dek)
    try:
        conn = db_session.get(BankConnection, conn_id)
        conn.access_token = "live-access"
        conn.token_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
        for ext, kind in (("cur-1", "TRANSACTION"), ("card-1", "CREDIT_CARD")):
            db_session.add(Account(
                user_id=conn.user_id, bank_connection_id=conn.id, external_id=ext, provider_name="MONZO",
                account_type=kind, display_name=ext, current_balance=Decimal("0"),
            ))
        conn.last_synced_at = None
        db_session.commit()
    finally:
        user_crypto.current_dek.reset(ctx)
    return conn_id, dek


def _bank(monkeypatch, card_failure):
    """The current account works; the card's endpoints fail with `card_failure`
    (an HTTP status, or an exception to raise)."""
    real_client = httpx.AsyncClient

    def handler(request):
        path = request.url.path
        if path.endswith("/accounts/cur-1/transactions"):
            return httpx.Response(200, json={"results": [TX]})
        if "card-1" in path:
            if isinstance(card_failure, int):
                return httpx.Response(card_failure, json={"error": "nope"})
            raise card_failure
        return httpx.Response(404)

    def factory(*args, **kwargs):
        return real_client(*args, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(truelayer_module.httpx, "AsyncClient", factory)


def _last_synced(db_session, conn_id, dek):
    db_session.expire_all()
    ctx = user_crypto.current_dek.set(dek)
    try:
        return db_session.get(BankConnection, conn_id).last_synced_at
    finally:
        user_crypto.current_dek.reset(ctx)


CARD_FAILURES = [
    pytest.param(403, id="monzo-card-403"),
    pytest.param(501, id="revolut-card-501"),
    pytest.param(httpx.ReadTimeout(""), id="timeout-no-message"),
]


@pytest.mark.parametrize("card_failure", CARD_FAILURES)
def test_web_sync_keeps_the_current_account_when_the_card_fails(client, db_session, monkeypatch, card_failure):
    conn_id, dek = _connection_with_card(client, db_session)
    _bank(monkeypatch, card_failure)
    r = client.post("/api/v1/banking/sync/transactions", json={"days": 365})
    assert r.status_code == 200, r.text
    assert r.json()["transactions_synced"] == 1
    assert "1 account" in r.json()["message"]  # says one was skipped
    assert _last_synced(db_session, conn_id, dek) is not None


@pytest.mark.parametrize("card_failure", CARD_FAILURES)
def test_refresh_reports_the_connection_synced_with_the_skip(client, db_session, monkeypatch, card_failure):
    conn_id, dek = _connection_with_card(client, db_session)
    _bank(monkeypatch, card_failure)

    async def no_account_refresh(connection, db, skip_token_refresh=False):
        return []

    monkeypatch.setattr(truelayer_service, "sync_accounts", no_account_refresh)
    r = client.post("/api/v1/banking/sync")
    assert r.status_code == 200, r.text
    [conn] = r.json()["connections"]
    assert (conn["status"], conn["transactions_synced"], conn["accounts_skipped"]) == ("synced", 1, 1)


def test_every_account_failing_is_failed_never_a_500(client, db_session, monkeypatch):
    conn_id, dek = _connection_with_card(client, db_session)
    real_client = httpx.AsyncClient

    def handler(request):
        raise httpx.ReadTimeout("")

    monkeypatch.setattr(truelayer_module.httpx, "AsyncClient",
                        lambda *a, **k: real_client(*a, transport=httpx.MockTransport(handler), **k))
    r = client.post("/api/v1/banking/sync/transactions", json={})
    assert r.status_code == 502, r.text
    assert "couldn't sync right now" in r.json()["detail"]
    assert _last_synced(db_session, conn_id, dek) is None


def test_monzo_403_on_the_long_fetch_retries_inside_the_90_day_window(client, db_session, monkeypatch):
    """Lead's hint: after the first minutes of consent Monzo serves only the
    last 90 days; asking for exactly 90 can fall just outside. The fallback
    asks for 89 and gets the data."""
    from datetime import date

    conn_id, dek = _connection_with_card(client, db_session)
    real_client = httpx.AsyncClient
    asked = []

    card_tx = {**TX, "transaction_id": "tx-card-1"}

    def handler(request):
        path = request.url.path
        if path.endswith("/accounts/cur-1/transactions"):
            return httpx.Response(200, json={"results": [TX]})
        if path.endswith("/cards/card-1/transactions"):
            frm = date.fromisoformat(request.url.params["from"])
            asked.append(frm)
            if (date.today() - frm).days >= 90:
                return httpx.Response(403, json={"error": "access_denied"})
            return httpx.Response(200, json={"results": [card_tx]})
        return httpx.Response(404)  # a card isn't under /accounts

    monkeypatch.setattr(truelayer_module.httpx, "AsyncClient",
                        lambda *a, **k: real_client(*a, transport=httpx.MockTransport(handler), **k))
    r = client.post("/api/v1/banking/sync/transactions", json={"days": 365})
    assert r.status_code == 200, r.text
    assert r.json()["transactions_synced"] == 2  # the card's too, via the 89-day retry
    assert (date.today() - asked[-1]).days == 89


def test_a_501_card_is_skipped_quietly(client, db_session, monkeypatch, caplog):
    """Revolut card transactions aren't offered via TrueLayer: not a warning."""
    import logging

    _connection_with_card(client, db_session)
    _bank(monkeypatch, 501)
    with caplog.at_level(logging.INFO, logger="app.services.truelayer"):
        client.post("/api/v1/banking/sync/transactions", json={})
    skips = [r for r in caplog.records if "Skipped an account" in r.getMessage()]
    assert skips and all(r.levelno == logging.INFO for r in skips)
    assert all("card-1" not in r.getMessage() and "live-access" not in r.getMessage() for r in caplog.records)


def test_a_failing_fallback_no_longer_aborts_the_other_accounts(client, db_session, monkeypatch):
    """Lead's hint: the 90-day fallback call wasn't wrapped, so its failure
    left the account loop and aborted every account in the connection."""
    conn_id, dek = _connection_with_card(client, db_session)
    real_client = httpx.AsyncClient

    def handler(request):
        if "card-1" in request.url.path:
            raise httpx.ReadTimeout("")  # both the long fetch and the fallback
        if request.url.path.endswith("/accounts/cur-1/transactions"):
            return httpx.Response(200, json={"results": [TX]})
        return httpx.Response(404)

    monkeypatch.setattr(truelayer_module.httpx, "AsyncClient",
                        lambda *a, **k: real_client(*a, transport=httpx.MockTransport(handler), **k))
    r = client.post("/api/v1/banking/sync/transactions", json={"days": 365})
    assert r.status_code == 200, r.text
    assert r.json()["transactions_synced"] == 1


# --------------------------------------------------------------------------- #
# sec's multi-user criteria (2026-10-12)
# --------------------------------------------------------------------------- #
PLANTED = "PLANTED-BODY-detail"
SECRET_NAME = "Joint SECRETNAME"


def _second_user(client, db_session):
    """User B (an MCP token with finance:sync) with a working current account and card."""
    from tests.integration.test_bank_sync_api import World

    w = World(client, db_session, email="userb@example.com")
    conn_id = w.connection("REVOLUT")
    ctx = user_crypto.current_dek.set(w.dek)
    try:
        conn = db_session.get(BankConnection, uuid.UUID(conn_id))
        conn.access_token = "b-access"
        for ext in ("b-cur", "b-card"):
            db_session.add(Account(
                user_id=w.user.id, bank_connection_id=conn.id, external_id=ext, provider_name="REVOLUT",
                account_type="TRANSACTION", display_name=ext, current_balance=Decimal("10"),
            ))
        db_session.commit()
    finally:
        user_crypto.current_dek.reset(ctx)
    return w, conn_id


def _two_user_bank(monkeypatch):
    """A's card fails with a planted error body; everything of B's works."""
    real_client = httpx.AsyncClient

    def handler(request):
        path, token = request.url.path, request.headers.get("Authorization", "")
        if "card-1" in path:
            return httpx.Response(403, json={"error": "access_denied", "error_description": PLANTED})
        for ext in ("cur-1", "b-cur", "b-card"):
            if path.endswith(f"/accounts/{ext}/transactions"):
                tx = {**TX, "transaction_id": f"tx-{ext}", "description": SECRET_NAME}
                return httpx.Response(200, json={"results": [tx]})
        return httpx.Response(404)

    monkeypatch.setattr(truelayer_module.httpx, "AsyncClient",
                        lambda *a, **k: real_client(*a, transport=httpx.MockTransport(handler), **k))

    async def no_account_refresh(connection, db, skip_token_refresh=False):
        return []

    monkeypatch.setattr(truelayer_service, "sync_accounts", no_account_refresh)


def _tx_count(db_session, user_id):
    return (
        db_session.query(Transaction).join(Account)
        .filter(Account.user_id == user_id).count()
    )


def test_user_as_failing_card_leaves_user_b_alone(client, db_session, monkeypatch):
    a_conn, a_dek = _connection_with_card(client, db_session)
    b, b_conn = _second_user(client, db_session)
    _two_user_bank(monkeypatch)
    before_b = _tx_count(db_session, b.user.id)

    a = client.post("/api/v1/banking/sync/transactions", json={})  # A's web session
    assert a.status_code == 200, a.text
    assert _tx_count(db_session, b.user.id) == before_b  # B's rows untouched by A's sync

    r = b.sync()  # then B: B's card is not treated as skipped
    assert r.status_code == 200, r.text
    [conn] = r.json()["connections"]
    assert (conn["connection_id"], conn["status"], conn["accounts_skipped"], conn["transactions_synced"]) == (
        b_conn, "synced", 0, 2,
    )
    assert str(a_conn) not in r.text


def test_logs_carry_only_the_callers_ids_provider_and_status(client, db_session, monkeypatch, caplog):
    import logging

    a_conn, a_dek = _connection_with_card(client, db_session)
    b, b_conn = _second_user(client, db_session)
    _two_user_bank(monkeypatch)
    with caplog.at_level(logging.DEBUG):
        client.post("/api/v1/banking/sync/transactions", json={})
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "Skipped an account's transactions" in text and "403" in text
    for leaked in (PLANTED, SECRET_NAME, "live-access", "b-access", "card-1", str(b.user.id), b_conn):
        assert leaked not in text, leaked


def test_a_skipped_card_keeps_its_transactions_and_balance(client, db_session, monkeypatch):
    """Fail safe: a card that didn't sync keeps its previous data; its
    balance is never zeroed (that would understate debt)."""
    conn_id, dek = _connection_with_card(client, db_session)
    ctx = user_crypto.current_dek.set(dek)
    try:
        card = db_session.query(Account).filter(Account.external_id == "card-1").one()
        card.current_balance = Decimal("-450.00")
        db_session.add(Transaction(
            account_id=card.id, external_id="tx-card-old", transaction_type="debit", amount=Decimal("30"),
            currency="GBP", description="OLD", transaction_date=datetime(2026, 9, 1, tzinfo=timezone.utc),
        ))
        db_session.commit()
        card_id = card.id
    finally:
        user_crypto.current_dek.reset(ctx)
    _bank(monkeypatch, 403)
    client.post("/api/v1/banking/sync/transactions", json={})
    db_session.expire_all()
    ctx = user_crypto.current_dek.set(dek)
    try:
        assert db_session.query(Transaction).filter(Transaction.account_id == card_id).count() == 1
        assert db_session.get(Account, card_id).current_balance == Decimal("-450.00")
    finally:
        user_crypto.current_dek.reset(ctx)


def test_a_card_whose_balance_fails_keeps_its_balance_and_stays_stale(client, db_session, monkeypatch):
    """sync_accounts used to set the balance to None and stamp
    balance_updated_at when the balance call failed."""
    conn_id, dek = _connection_with_card(client, db_session)
    old = datetime(2026, 10, 1, tzinfo=timezone.utc)
    ctx = user_crypto.current_dek.set(dek)
    try:
        card = db_session.query(Account).filter(Account.external_id == "card-1").one()
        card.current_balance, card.balance_updated_at = Decimal("-450.00"), old
        db_session.commit()
        card_id = card.id
    finally:
        user_crypto.current_dek.reset(ctx)
    real_client = httpx.AsyncClient

    def handler(request):
        path = request.url.path
        if path.endswith("/data/v1/accounts"):
            return httpx.Response(200, json={"results": [{"account_id": "cur-1", "display_name": "Current"}]})
        if path.endswith("/data/v1/cards"):
            return httpx.Response(200, json={"results": [{"account_id": "card-1", "display_name": SECRET_NAME}]})
        if path.endswith("/accounts/cur-1/balance"):
            return httpx.Response(200, json={"results": [{"current": 100, "available": 100}]})
        if "card-1" in path:
            return httpx.Response(403, json={"error": "access_denied", "error_description": PLANTED})
        return httpx.Response(404)

    monkeypatch.setattr(truelayer_module.httpx, "AsyncClient",
                        lambda *a, **k: real_client(*a, transport=httpx.MockTransport(handler), **k))
    r = client.post("/api/v1/banking/sync/accounts")
    assert r.status_code == 200, r.text
    db_session.expire_all()
    ctx = user_crypto.current_dek.set(dek)
    try:
        card = db_session.get(Account, card_id)
        assert card.current_balance == Decimal("-450.00")
        assert card.balance_updated_at.replace(tzinfo=timezone.utc) == old
    finally:
        user_crypto.current_dek.reset(ctx)
