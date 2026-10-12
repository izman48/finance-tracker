"""Revolut and Amex after #141 (T-08-27, prod log 2026-10-12 00:03 UTC).

Revolut: the connection failed with only "TrueLayerError" in the log and no
skip line; a 501 skip is logged at INFO, so the likely cause is that every
Revolut account answered 501 (transactions not offered via TrueLayer) and
"every account failed" was raised. An account the bank doesn't offer
transactions for isn't a failure: if that's every account, the connection
still syncs (balances already did), reporting them in accounts_skipped. A
connection-level failure now logs the HTTP status and TrueLayer error code,
the same safe fields as the skip line. A /cards list that answers 501 is
just "no cards".

Amex: its transactions call hit the 10 s per-call timeout on a second sync.
A transactions fetch now gets TRANSACTIONS_TIMEOUT_SECONDS (25 s); the
other calls keep 10 s. The budget and start margin are sized to match.
"""
import logging

import httpx

from app.routers import banking
from app.services import sync_lock
from app.services import truelayer as truelayer_module
from tests.integration.test_sync_per_account import TX, _connection_with_card, _last_synced


def _mock(monkeypatch, handler, timeouts=None):
    real_client = httpx.AsyncClient

    def factory(*args, **kwargs):
        if timeouts is not None:
            timeouts.append(kwargs.get("timeout"))
        return real_client(*args, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(truelayer_module.httpx, "AsyncClient", factory)


def test_a_bank_that_offers_no_transactions_still_syncs(client, db_session, monkeypatch):
    """Every account answers 501: not a failure. Synced, all skipped."""
    conn_id, dek = _connection_with_card(client, db_session)
    _mock(monkeypatch, lambda r: httpx.Response(501, json={"error": "endpoint_not_supported"}))
    r = client.post("/api/v1/banking/sync/transactions", json={})
    assert r.status_code == 200, r.text
    assert "Skipped 2 account" in r.json()["message"]
    assert _last_synced(db_session, conn_id, dek) is not None


def test_every_account_really_failing_is_still_a_failure(client, db_session, monkeypatch):
    conn_id, dek = _connection_with_card(client, db_session)
    _mock(monkeypatch, lambda r: httpx.Response(403, json={"error": "access_denied"}))
    r = client.post("/api/v1/banking/sync/transactions", json={})
    assert r.status_code == 502
    assert _last_synced(db_session, conn_id, dek) is None


def test_a_connection_failure_logs_the_status_and_code(client, db_session, monkeypatch, caplog):
    """'TrueLayerError' alone couldn't be diagnosed."""
    _connection_with_card(client, db_session)
    _mock(monkeypatch, lambda r: httpx.Response(403, json={"error": "access_denied", "error_description": "PLANTED"}))
    with caplog.at_level(logging.INFO):
        client.post("/api/v1/banking/sync/transactions", json={})
    lines = [r.getMessage() for r in caplog.records if "Failed to sync transactions for" in r.getMessage()]
    assert lines and "403" in lines[0] and "access_denied" in lines[0]
    assert "PLANTED" not in "\n".join(r.getMessage() for r in caplog.records)


def test_a_token_refresh_failure_logs_its_status_and_code(client, db_session, monkeypatch, caplog):
    from tests.integration.test_bank_reauth import _seed_expired_connection

    _seed_expired_connection(client, db_session)
    _mock(monkeypatch, lambda r: httpx.Response(503, json={"error": "temporarily_unavailable"}))
    with caplog.at_level(logging.INFO):
        client.post("/api/v1/banking/sync/transactions", json={})
    lines = [r.getMessage() for r in caplog.records if "Failed to sync transactions for" in r.getMessage()]
    assert lines and "503" in lines[0] and "temporarily_unavailable" in lines[0]


def test_a_501_cards_list_is_just_no_cards(client, db_session, monkeypatch):
    conn_id, dek = _connection_with_card(client, db_session)

    def handler(request):
        path = request.url.path
        if path.endswith("/data/v1/accounts"):
            return httpx.Response(200, json={"results": [{"account_id": "cur-1", "display_name": "Current"}]})
        if path.endswith("/data/v1/cards"):
            return httpx.Response(501, json={"error": "endpoint_not_supported"})
        if path.endswith("/accounts/cur-1/balance"):
            return httpx.Response(200, json={"results": [{"current": 5, "available": 5}]})
        return httpx.Response(404)

    _mock(monkeypatch, handler)
    r = client.post("/api/v1/banking/sync/accounts")
    assert r.status_code == 200, r.text
    assert r.json()["accounts_synced"] == 1


def test_a_transactions_fetch_gets_the_longer_timeout(client, db_session, monkeypatch):
    """Amex: a transactions call gets TRANSACTIONS_TIMEOUT_SECONDS."""
    _connection_with_card(client, db_session)
    timeouts = []

    def handler(request):
        if request.url.path.endswith("/accounts/cur-1/transactions"):
            return httpx.Response(200, json={"results": [TX]})
        return httpx.Response(501)

    _mock(monkeypatch, handler, timeouts)
    client.post("/api/v1/banking/sync/transactions", json={})
    assert truelayer_module.TRANSACTIONS_TIMEOUT_SECONDS == 25
    assert timeouts and all(t.read == 25 for t in timeouts)


def test_other_calls_keep_the_short_timeout(client, db_session, monkeypatch):
    _connection_with_card(client, db_session)
    timeouts = []
    _mock(monkeypatch, lambda r: httpx.Response(200, json={"results": []}), timeouts)
    client.post("/api/v1/banking/sync/accounts")
    assert timeouts and all(t.read == truelayer_module.TRUELAYER_TIMEOUT_SECONDS == 10 for t in timeouts)


def test_the_budget_lease_and_margin_still_fit():
    """A bank only starts with enough budget for a token refresh and one
    transactions call; once started it runs to the end, so the worst case is
    the budget plus one bank. Sized for a bank of 4 accounts, each with a
    long fetch and a 403 retry, well inside the 5-minute lease."""
    tl = truelayer_module
    assert banking.SYNC_BUDGET_SECONDS == 45
    assert banking.SYNC_START_MARGIN_SECONDS >= tl.TRUELAYER_TIMEOUT_SECONDS + tl.TRANSACTIONS_TIMEOUT_SECONDS
    assert banking.SYNC_START_MARGIN_SECONDS <= banking.SYNC_BUDGET_SECONDS  # the first bank always starts
    one_bank = tl.TRUELAYER_TIMEOUT_SECONDS + 4 * 2 * tl.TRANSACTIONS_TIMEOUT_SECONDS
    assert banking.SYNC_BUDGET_SECONDS + one_bank < sync_lock.LEASE.total_seconds()
