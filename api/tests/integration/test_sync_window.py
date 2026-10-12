"""Long history only on the first sync after connecting (T-08-28).

Prod log (2026-10-12): every sync asked Monzo for 1825 days (the app's
Refresh) or 90 (`/banking/sync`), got `403 sca_exceeded` for each account,
then retried with 88: two calls per account per sync, doubling the bank
quota spent on unattended syncs. Banks give more than 90 days only in the
first minutes after consent, so long history is asked for only on the
first sync after connecting (the OAuth callback). Every other sync asks
for the last FALLBACK_DAYS of the London date straight away: one call per
account.
"""
import asyncio
import logging
from datetime import date, datetime, timezone

import httpx

from app.core import user_crypto
from app.models import BankConnection
from app.services import truelayer as truelayer_module
from app.services.truelayer import truelayer_service
from tests.integration.test_sync_per_account import TX, _connection_with_card

FROZEN = datetime(2026, 10, 12, 10, 0, tzinfo=timezone.utc)
WINDOW_START = date(2026, 7, 16)  # 12 Oct less 88 days


def _monzo(monkeypatch):
    """Monzo after the first minutes of consent: 403 sca_exceeded beyond 90 days."""
    monkeypatch.setattr(truelayer_module, "_utcnow", lambda: FROZEN)
    calls = []
    real_client = httpx.AsyncClient

    def handler(request):
        path = request.url.path
        if path.endswith("/transactions"):
            frm = date.fromisoformat(request.url.params["from"])
            calls.append((path, frm))
            if (FROZEN.date() - frm).days >= 90:
                return httpx.Response(403, json={"error": "sca_exceeded"})
            if "/accounts/" in path:
                return httpx.Response(200, json={"results": [TX] if "cur-1" in path else []})
            return httpx.Response(200, json={"results": []})
        return httpx.Response(404)

    monkeypatch.setattr(truelayer_module.httpx, "AsyncClient",
                        lambda *a, **k: real_client(*a, transport=httpx.MockTransport(handler), **k))
    return calls


def _per_account(calls):
    """Transactions calls per account (a card's 404 on /accounts then /cards counts as one fetch)."""
    fetched = {}
    for path, frm in calls:
        ext = path.split("/")[-2]
        fetched.setdefault(ext, set()).add(frm)
    return fetched


def test_a_refresh_from_the_app_asks_for_88_days_once(client, db_session, monkeypatch):
    _connection_with_card(client, db_session)
    calls = _monzo(monkeypatch)
    r = client.post("/api/v1/banking/sync/transactions", json={"days": 1825})  # the app's Refresh
    assert r.status_code == 200, r.text
    assert _per_account(calls) == {"cur-1": {WINDOW_START}, "card-1": {WINDOW_START}}
    assert "last 88 days" in r.json()["message"]


def test_an_mcp_refresh_asks_for_88_days_once(client, db_session, monkeypatch):
    _connection_with_card(client, db_session)
    calls = _monzo(monkeypatch)

    async def no_account_refresh(connection, db, skip_token_refresh=False):
        return []

    monkeypatch.setattr(truelayer_service, "sync_accounts", no_account_refresh)
    r = client.post("/api/v1/banking/sync")
    assert r.status_code == 200, r.text
    assert _per_account(calls) == {"cur-1": {WINDOW_START}, "card-1": {WINDOW_START}}
    assert not any((FROZEN.date() - frm).days >= 90 for _, frm in calls)


def test_the_first_sync_after_connecting_asks_for_long_history(client, db_session, monkeypatch):
    """The callback's sync (history=True) asks for 730 days first; if the
    bank refuses with 403, it falls back to the 88-day window."""
    conn_id, dek = _connection_with_card(client, db_session)
    calls = _monzo(monkeypatch)

    async def run():
        ctx = user_crypto.current_dek.set(dek)
        try:
            conn = db_session.get(BankConnection, conn_id)
            return await truelayer_service.sync_transactions(conn, db_session, days=730, skip_token_refresh=True,
                                                             history=True)
        finally:
            user_crypto.current_dek.reset(ctx)

    assert asyncio.run(run()) == 1
    asked = _per_account(calls)["cur-1"]
    assert min(asked) == date(2024, 10, 12) and WINDOW_START in asked  # 730 days, then the fallback


def test_a_cards_only_bank_is_not_offered_accounts_logged_quietly(client, db_session, monkeypatch, caplog):
    """Amex is cards-only: /accounts answering 501 is expected, not a failure."""
    _connection_with_card(client, db_session)
    real_client = httpx.AsyncClient

    def handler(request):
        path = request.url.path
        if path.endswith("/data/v1/accounts"):
            return httpx.Response(501, json={"error": "endpoint_not_supported"})
        if path.endswith("/data/v1/cards"):
            return httpx.Response(200, json={"results": [{"account_id": "card-1", "display_name": "Amex"}]})
        if path.endswith("/cards/card-1/balance"):
            return httpx.Response(200, json={"results": [{"current": 5, "available": 5}]})
        return httpx.Response(404)

    monkeypatch.setattr(truelayer_module.httpx, "AsyncClient",
                        lambda *a, **k: real_client(*a, transport=httpx.MockTransport(handler), **k))
    with caplog.at_level(logging.INFO, logger="app.services.truelayer"):
        r = client.post("/api/v1/banking/sync/accounts")
    assert r.status_code == 200, r.text
    lines = [rec for rec in caplog.records if "accounts" in rec.getMessage().lower() and "connection" in rec.getMessage()]
    assert lines and all(rec.levelno == logging.INFO for rec in lines)
    assert any("not offered" in rec.getMessage() for rec in lines)
