"""The first sync after connecting logs only safe fields (T-08-22 follow-up, sec on #145).

The OAuth callback's first sync logged `str(e)`. For an HTTP error that's
the request URL, naming the provider's account or card id. It now logs the
error type and status, as T-08-24 does for every other sync path.
"""
import logging

import httpx

from app.core.security import create_oauth_state
from app.services.truelayer import truelayer_service
from tests.integration.test_bank_sync_api import World

PROVIDER_IDS = ("acc-PROVIDER-SECRET", "card-PROVIDER-SECRET")


def _http_error(status, path):
    request = httpx.Request("GET", f"https://api.truelayer.com/data/v1/{path}/transactions?from=2024-01-01")
    return httpx.HTTPStatusError("boom", request=request, response=httpx.Response(status, request=request))


def test_the_callback_sync_logs_no_urls_or_provider_ids(client, db_session, monkeypatch, caplog):
    w = World(client, db_session, email="callback@example.com")

    async def exchange(code):
        return {"access_token": "new-access", "refresh_token": "new-refresh", "expires_in": 3600}

    async def provider(token):
        return {"provider_id": "ob-monzo", "display_name": "MONZO"}

    async def accounts(connection, db, skip_token_refresh=False):
        raise _http_error(403, f"accounts/{PROVIDER_IDS[0]}")

    async def transactions(connection, db, days=90, skip_token_refresh=False, report=None):
        raise _http_error(403, f"cards/{PROVIDER_IDS[1]}")

    for name, fake in (("exchange_code_for_token", exchange), ("get_provider_info", provider),
                       ("sync_accounts", accounts), ("sync_transactions", transactions)):
        monkeypatch.setattr(truelayer_service, name, fake)
    state = create_oauth_state(str(w.user.id), w.dek)
    with caplog.at_level(logging.DEBUG):
        r = client.get("/api/v1/banking/callback", params={"code": "c", "state": state}, follow_redirects=False)
    assert r.status_code in (302, 303, 307), r.text
    text = "\n".join(rec.getMessage() for rec in caplog.records)
    assert "HTTPStatusError 403" in text
    for leaked in (*PROVIDER_IDS, "truelayer.com", "from=2024"):
        assert leaked not in text, leaked
