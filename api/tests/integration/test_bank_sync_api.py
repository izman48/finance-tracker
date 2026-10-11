"""On-demand bank sync for MCP clients (`POST /banking/sync`).

The DEK lives only for the length of a request, so a sync cannot run as a
background job: the caller waits while every connection syncs. The route is
reachable from a web session or from an MCP token that holds the opt-in
`finance:sync` scope; `finance:read` alone is not enough, and the older
`/banking/sync/accounts` and `/banking/sync/transactions` routes stay web-only.

The response says, per connection, whether it synced, needs reconnecting,
or failed. It never carries exception text, URLs, tokens or provider ids.
A user gets one sync at a time, and a new sync starts at least
SYNC_COOLDOWN_SECONDS after the last one, so an assistant cannot call it in
a loop. A bank that refuses a read only marks that connection `failed`.

TrueLayer is replaced by fakes of the two service calls; the TrueLayer
client itself is tested in test_bank_reauth.py and the truelayer unit tests.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.core import rate_limit, user_crypto
from app.core.rate_limit import user_in_flight
from app.models import BankConnection, User
from app.routers.banking import SYNC_COOLDOWN_SECONDS, sync_in_flight_key
from app.services.truelayer import ReauthRequired, TrueLayerError, truelayer_service
from tests.integration.test_oauth import READ, _bearer, _connect
from tests.integration.test_transactions_endpoint import _dek_from_token

SYNC = "finance:sync"
URL = "/api/v1/banking/sync"
SECRETS = ("SECRET", "connect/token", "truelayer.com", "Traceback")


class FakeTrueLayer:
    """Stands in for truelayer_service.sync_accounts / sync_transactions.

    `fail` maps a provider name to the exception its connection raises."""

    def __init__(self, fail: dict[str, Exception] | None = None, txns: int = 3):
        self.fail = fail or {}
        self.txns = txns
        self.calls: list[tuple[str, str, int | None]] = []

    async def sync_accounts(self, connection, db, skip_token_refresh=False):
        self.calls.append(("accounts", connection.provider_name, None))
        if connection.provider_name in self.fail:
            raise self.fail[connection.provider_name]
        return ["acct-1", "acct-2"]

    async def sync_transactions(self, connection, db, days=90, skip_token_refresh=False, report=None):
        self.calls.append(("transactions", connection.provider_name, days))
        return self.txns


@pytest.fixture
def truelayer(monkeypatch):
    fake = FakeTrueLayer()
    monkeypatch.setattr(truelayer_service, "sync_accounts", fake.sync_accounts)
    monkeypatch.setattr(truelayer_service, "sync_transactions", fake.sync_transactions)
    return fake


class World:
    def __init__(self, client, db, scopes=(READ, SYNC), email="banksync@example.com"):
        self.client, self.db = client, db
        self.web, _, tokens = _connect(client, scopes=scopes, email=email)
        self.mcp = tokens["access_token"]
        self.dek = _dek_from_token(self.web)
        self.user = db.query(User).filter(User.email == email).one()

    def connection(self, name: str) -> str:
        ctx = user_crypto.current_dek.set(self.dek)
        try:
            conn = BankConnection(
                user_id=self.user.id, provider_id=f"ob-{name}-SECRET-PROVIDER", provider_name=name,
                access_token="at-SECRET-ACCESS", refresh_token="rt-SECRET-REFRESH",
                token_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )
            self.db.add(conn)
            self.db.commit()
            return str(conn.id)
        finally:
            user_crypto.current_dek.reset(ctx)

    def sync(self, token=None):
        return self.client.post(URL, headers=_bearer(token or self.mcp))


def _no_secrets(text: str) -> None:
    for secret in SECRETS:
        assert secret not in text


# --------------------------------------------------------------------------- #
# Who may sync
# --------------------------------------------------------------------------- #
def test_read_scope_alone_cannot_sync(client, db_session, truelayer):
    w = World(client, db_session, scopes=(READ,))
    w.connection("MONZO")

    r = w.sync()

    assert r.status_code == 403
    assert SYNC in r.headers["WWW-Authenticate"]
    assert truelayer.calls == []


def test_sync_scope_syncs_every_connection(client, db_session, truelayer):
    w = World(client, db_session)
    w.connection("MONZO")
    w.connection("AMEX")

    r = w.sync()

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["accounts_synced"] == 4
    assert body["transactions_synced"] == 6
    assert sorted((c["provider"], c["status"]) for c in body["connections"]) == [
        ("AMEX", "synced"), ("MONZO", "synced"),
    ]
    _no_secrets(r.text)


def test_a_web_session_can_sync_too(client, db_session, truelayer):
    w = World(client, db_session)
    w.connection("MONZO")

    assert w.sync(token=w.web).status_code == 200


def test_accounts_sync_before_transactions_over_the_default_window(client, db_session, truelayer):
    w = World(client, db_session)
    w.connection("MONZO")

    w.sync()

    assert truelayer.calls == [("accounts", "MONZO", None), ("transactions", "MONZO", 90)]


@pytest.mark.parametrize("path", ["/api/v1/banking/sync/accounts", "/api/v1/banking/sync/transactions"])
def test_the_older_sync_routes_stay_web_only(client, db_session, truelayer, path):
    w = World(client, db_session)
    w.connection("MONZO")

    r = client.post(path, json={"days": 90}, headers=_bearer(w.mcp))

    assert r.status_code == 401
    assert truelayer.calls == []


def test_no_connections_is_a_400(client, db_session, truelayer):
    w = World(client, db_session)

    r = w.sync()

    assert r.status_code == 400
    assert "connect a bank" in r.json()["detail"].lower()


# --------------------------------------------------------------------------- #
# Failures are reported per connection, without detail
# --------------------------------------------------------------------------- #
def test_expired_consent_says_reconnect_and_skips_transactions(client, db_session, truelayer):
    truelayer.fail["MONZO"] = ReauthRequired("invalid_grant")
    w = World(client, db_session)
    w.connection("MONZO")
    w.connection("AMEX")

    r = w.sync()

    assert r.status_code == 200, r.text
    statuses = {c["provider"]: c for c in r.json()["connections"]}
    assert statuses["MONZO"]["status"] == "reconnect"
    assert statuses["MONZO"]["transactions_synced"] == 0
    assert statuses["AMEX"]["status"] == "synced"
    assert ("transactions", "MONZO", 90) not in truelayer.calls


def test_other_errors_say_failed_and_never_leak_the_message(client, db_session, truelayer):
    truelayer.fail["MONZO"] = TrueLayerError(
        "temporarily_unavailable at https://auth.truelayer.com/connect/token rt-SECRET-REFRESH"
    )
    w = World(client, db_session)
    w.connection("MONZO")

    r = w.sync()

    assert r.status_code == 200
    assert r.json()["connections"][0]["status"] == "failed"
    assert "temporarily_unavailable" not in r.text
    _no_secrets(r.text)


def test_unexpected_exceptions_are_failed_not_500(client, db_session, truelayer):
    truelayer.fail["MONZO"] = RuntimeError("boom SECRET")
    w = World(client, db_session)
    w.connection("MONZO")

    r = w.sync()

    assert r.status_code == 200
    assert r.json()["connections"][0]["status"] == "failed"
    _no_secrets(r.text)


def test_response_names_only_the_documented_fields(client, db_session, truelayer):
    w = World(client, db_session)
    w.connection("MONZO")

    body = w.sync().json()

    assert set(body) == {"connections", "accounts_synced", "transactions_synced"}
    assert set(body["connections"][0]) == {
        "connection_id", "provider", "status", "accounts_synced", "transactions_synced",
        "accounts_skipped",  # a count only, never which account (T-08-24)
    }


# --------------------------------------------------------------------------- #
# Limits
# --------------------------------------------------------------------------- #
@pytest.fixture
def clock(monkeypatch):
    """The cooldown's clock (held in the DB since T-08-22), moved by hand in seconds."""
    from app.services import sync_lock

    now = [0.0]
    start = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(sync_lock, "utcnow", lambda: start + timedelta(seconds=now[0]))
    return now


def test_the_cooldown_is_ten_minutes():
    assert SYNC_COOLDOWN_SECONDS == 600


def test_a_second_sync_inside_the_cooldown_is_refused(client, db_session, truelayer, clock):
    w = World(client, db_session)
    w.connection("MONZO")

    assert w.sync().status_code == 200
    clock[0] += SYNC_COOLDOWN_SECONDS - 1
    r = w.sync()

    assert r.status_code == 429
    assert 0 < int(r.headers["Retry-After"]) <= SYNC_COOLDOWN_SECONDS
    assert len([c for c in truelayer.calls if c[0] == "accounts"]) == 1


def test_a_sync_after_the_cooldown_runs(client, db_session, truelayer, clock):
    w = World(client, db_session)
    w.connection("MONZO")

    for _ in range(5):
        assert w.sync().status_code == 200
        clock[0] += SYNC_COOLDOWN_SECONDS


def test_web_and_mcp_share_one_cooldown(client, db_session, truelayer, clock):
    w = World(client, db_session)
    w.connection("MONZO")

    assert w.sync(token=w.web).status_code == 200

    assert w.sync().status_code == 429


def test_the_cooldown_is_per_user(client, db_session, truelayer, clock):
    a = World(client, db_session, email="a@example.com")
    a.connection("MONZO")
    a.sync()

    b = World(client, db_session, email="b@example.com")
    b.connection("MONZO")

    assert b.sync().status_code == 200


def test_one_sync_at_a_time_and_a_refused_one_costs_nothing(client, db_session, truelayer, clock):
    w = World(client, db_session)
    w.connection("MONZO")

    with user_in_flight.hold(sync_in_flight_key(w.user.id)):
        r = w.sync()
    assert r.status_code == 429
    assert "sync" in r.json()["detail"].lower()
    assert truelayer.calls == []

    assert w.sync().status_code == 200



# --------------------------------------------------------------------------- #
# The cooldown is held in the database (T-08-22, owner "A + address")
# --------------------------------------------------------------------------- #
def test_the_cooldown_survives_a_restart(client, db_session, truelayer, clock):
    """Held in the DB: a restart (the in-process limiter reset) can't clear it."""
    w = World(client, db_session)
    w.connection("MONZO")
    assert w.sync().status_code == 200
    rate_limit.user_rate_limiter.reset()
    clock[0] += 60
    assert w.sync().status_code == 429


def test_the_other_worker_sees_the_cooldown(client, db_session, truelayer, clock):
    """Another session (the other worker) reads the same row."""
    from app.services import sync_lock
    from tests.conftest import TestingSessionLocal

    w = World(client, db_session)
    w.connection("MONZO")
    assert w.sync().status_code == 200
    other = TestingSessionLocal()
    try:
        assert sync_lock.cooldown_left(other, w.user.id) > 0
    finally:
        other.close()


def test_a_sync_refused_for_no_connections_starts_no_cooldown(client, db_session, truelayer, clock):
    w = World(client, db_session)
    assert w.sync().status_code == 400
    w.connection("MONZO")
    assert w.sync().status_code == 200


def test_a_sync_refused_while_another_runs_starts_no_cooldown(client, db_session, truelayer, clock):
    from app.services import sync_lock
    from tests.conftest import TestingSessionLocal

    w = World(client, db_session)
    w.connection("MONZO")
    other = TestingSessionLocal()
    try:
        with sync_lock.sync_lease(other, w.user.id):
            assert w.sync().status_code == 429
    finally:
        other.close()
    assert w.sync().status_code == 200
