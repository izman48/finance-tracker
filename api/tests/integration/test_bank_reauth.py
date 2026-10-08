"""Expired bank consent: a refresh token TrueLayer rejects must surface as
"reconnect this bank", not as a raw 400 from the token endpoint.

TrueLayer refresh tokens stop working when the user's consent lapses (90 days
by default for UK banks) or is revoked at the bank; the token endpoint then
answers 400 {"error": "invalid_grant"}. Retrying can never succeed, so the
connection is flagged for re-authorization and the dead refresh token dropped.

TrueLayer is stubbed with httpx.MockTransport; requests go through the API so
the DEK flows from the bearer token, as in production.
"""
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from jose import jwt

from app.core import user_crypto
from app.core.config import get_settings
from app.models import BankConnection, User
from app.services import truelayer as truelayer_module
from app.services.truelayer import ReauthRequired, TrueLayerError, truelayer_service

SECRET = get_settings().secret_key
EMAIL, PASSWORD = "reauth@example.com", "securepassword123"
TOKEN_URL = f"{get_settings().truelayer_auth_url}/connect/token"


@pytest.fixture
def truelayer(monkeypatch):
    """Route the service's httpx clients to a stub; records every request."""
    state = {"handler": None, "requests": []}

    def handler(request: httpx.Request) -> httpx.Response:
        state["requests"].append(request)
        return state["handler"](request)

    real_client = httpx.AsyncClient

    def client_factory(*args, **kwargs):
        return real_client(*args, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(truelayer_module.httpx, "AsyncClient", client_factory)
    return state


def _invalid_grant(_request):
    return httpx.Response(400, json={"error": "invalid_grant"})


def _seed_expired_connection(client, db_session, refresh_token="dead-refresh"):
    """Register + login, then store a connection whose access token expired."""
    client.post("/api/v1/auth/register", json={"email": EMAIL, "password": PASSWORD})
    token = client.post(
        "/api/v1/auth/login", data={"username": EMAIL, "password": PASSWORD}
    ).json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    dek = user_crypto.unwrap_session_dek(jwt.decode(token, SECRET, algorithms=["HS256"])["dk"])
    user = db_session.query(User).filter(User.email == EMAIL).first()

    ctx = user_crypto.current_dek.set(dek)
    try:
        conn = BankConnection(
            user_id=user.id, provider_id="ob-monzo", provider_name="MONZO",
            access_token="expired-access", refresh_token=refresh_token,
            token_expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        db_session.add(conn)
        db_session.commit()
        conn_id = conn.id
    finally:
        user_crypto.current_dek.reset(ctx)
    return conn_id, dek


def _load(db_session, conn_id, dek) -> BankConnection:
    db_session.expire_all()
    ctx = user_crypto.current_dek.set(dek)
    try:
        conn = db_session.get(BankConnection, conn_id)
        _ = conn.refresh_token, conn.access_token  # decrypt while the DEK is set
        return conn
    finally:
        user_crypto.current_dek.reset(ctx)


@pytest.mark.asyncio
class TestRefreshAccessToken:
    async def test_invalid_grant_raises_reauth_required(self, truelayer):
        truelayer["handler"] = _invalid_grant

        with pytest.raises(ReauthRequired):
            await truelayer_service.refresh_access_token("dead-refresh")

    async def test_other_token_errors_name_truelayers_error_code(self, truelayer):
        truelayer["handler"] = lambda _r: httpx.Response(
            400, json={"error": "invalid_client", "error_description": "bad secret"}
        )

        with pytest.raises(TrueLayerError) as exc_info:
            await truelayer_service.refresh_access_token("some-refresh")

        assert not isinstance(exc_info.value, ReauthRequired)
        assert "invalid_client" in str(exc_info.value)

    async def test_error_message_never_contains_secrets(self, truelayer):
        truelayer["handler"] = lambda _r: httpx.Response(400, json={"error": "invalid_client"})

        with pytest.raises(TrueLayerError) as exc_info:
            await truelayer_service.refresh_access_token("secret-refresh-value")

        assert "secret-refresh-value" not in str(exc_info.value)
        if truelayer_service.client_secret:
            assert truelayer_service.client_secret not in str(exc_info.value)

    async def test_missing_refresh_token_needs_reauth_without_calling_truelayer(self, truelayer):
        with pytest.raises(ReauthRequired):
            await truelayer_service.refresh_access_token(None)

        assert truelayer["requests"] == []


class TestSyncWithExpiredConsent:
    def test_sync_accounts_asks_user_to_reconnect(self, client, db_session, truelayer):
        _seed_expired_connection(client, db_session)
        truelayer["handler"] = _invalid_grant

        response = client.post("/api/v1/banking/sync/accounts")

        assert response.status_code == 409
        detail = response.json()["detail"]
        assert "MONZO" in detail
        assert "reconnect" in detail.lower()
        assert "connect/token" not in detail

    def test_sync_transactions_asks_user_to_reconnect(self, client, db_session, truelayer):
        _seed_expired_connection(client, db_session)
        truelayer["handler"] = _invalid_grant

        response = client.post("/api/v1/banking/sync/transactions", json={"days": 90})

        assert response.status_code == 409
        assert "reconnect" in response.json()["detail"].lower()

    def test_dead_refresh_token_is_dropped(self, client, db_session, truelayer):
        conn_id, dek = _seed_expired_connection(client, db_session)
        truelayer["handler"] = _invalid_grant

        client.post("/api/v1/banking/sync/accounts")

        assert _load(db_session, conn_id, dek).refresh_token is None

    def test_status_flags_connection_as_needing_reconnection(self, client, db_session, truelayer):
        _seed_expired_connection(client, db_session)
        truelayer["handler"] = _invalid_grant
        client.post("/api/v1/banking/sync/accounts")

        connections = client.get("/api/v1/banking/status").json()["connections"]

        assert [c["is_expired"] for c in connections] == [True]

    def test_later_syncs_do_not_retry_the_dead_token(self, client, db_session, truelayer):
        _seed_expired_connection(client, db_session)
        truelayer["handler"] = _invalid_grant
        client.post("/api/v1/banking/sync/accounts")
        calls_after_first_sync = len(truelayer["requests"])

        response = client.post("/api/v1/banking/sync/accounts")

        assert response.status_code == 409
        assert len(truelayer["requests"]) == calls_after_first_sync

    def test_transient_token_errors_keep_the_refresh_token(self, client, db_session, truelayer):
        conn_id, dek = _seed_expired_connection(client, db_session)
        truelayer["handler"] = lambda _r: httpx.Response(503, json={"error": "temporarily_unavailable"})

        response = client.post("/api/v1/banking/sync/accounts")

        assert response.status_code == 500
        assert "temporarily_unavailable" in response.json()["detail"]
        assert _load(db_session, conn_id, dek).refresh_token == "dead-refresh"


class TestReconnectLink:
    """GET /banking/connections/{id}/reconnect: a fresh TrueLayer auth link that
    skips the bank picker. The callback then updates the existing connection
    (matched on provider_id), keeping its accounts and transactions."""

    def test_link_preselects_the_connections_bank(self, client, db_session):
        conn_id, _ = _seed_expired_connection(client, db_session)

        response = client.get(f"/api/v1/banking/connections/{conn_id}/reconnect")

        assert response.status_code == 200
        query = parse_qs(urlparse(response.json()["auth_url"]).query)
        assert query["provider_id"] == ["ob-monzo"]
        assert query["state"]  # signed state, as for a new connection

    def test_unknown_provider_falls_back_to_the_bank_picker(self, client, db_session):
        conn_id, dek = _seed_expired_connection(client, db_session)
        ctx = user_crypto.current_dek.set(dek)
        try:
            db_session.get(BankConnection, conn_id).provider_id = "unknown"
            db_session.commit()
        finally:
            user_crypto.current_dek.reset(ctx)

        response = client.get(f"/api/v1/banking/connections/{conn_id}/reconnect")

        assert response.status_code == 200
        assert "provider_id" not in parse_qs(urlparse(response.json()["auth_url"]).query)

    def test_another_users_connection_is_not_found(self, client, db_session):
        conn_id, _ = _seed_expired_connection(client, db_session)
        client.post("/api/v1/auth/register", json={"email": "other@example.com", "password": PASSWORD})
        other = client.post(
            "/api/v1/auth/login", data={"username": "other@example.com", "password": PASSWORD}
        ).json()["access_token"]

        response = client.get(
            f"/api/v1/banking/connections/{conn_id}/reconnect",
            headers={"Authorization": f"Bearer {other}"},
        )

        assert response.status_code == 404

    def test_requires_authentication(self, client, db_session):
        conn_id, _ = _seed_expired_connection(client, db_session)
        client.headers.pop("Authorization")

        response = client.get(f"/api/v1/banking/connections/{conn_id}/reconnect")

        assert response.status_code == 401
