"""Rate limits on account and decrypt-heavy routes, health 503, and the flows
cap (T-12-10b; sec T-12-10b; sec-2 on #239).

- change-password and delete-account: per user AND per IP, 429 past either
  (a password guess must not be free from many accounts or one).
- MCP-reachable reads that decrypt a user's whole ledger (rules preview and
  impact, the transactions list) and the bulk pack write: per user, never
  per IP, since every MCP call arrives from the MCP container's address.
  Two users each have their own budget.
- Health: 503 with a fixed body when the database is down; no error text.
- At most 1,000 flows per holding: 409, nothing written.

Limits are monkeypatched small so each test makes a few calls.
"""
import pytest
from sqlalchemy.exc import OperationalError

from app.core import rate_limit
from app.core.database import get_db
from app.main import app
from app.models import AssetFlow
from app.routers import assets as assets_router
from tests.integration.test_oauth import _bearer, _web_login

API = "/api/v1"
PASSWORD = "securepassword123"


@pytest.fixture
def small(monkeypatch):
    def set_limit(scope, n):
        monkeypatch.setitem(rate_limit.LIMITS, scope, (n, 60))
    return set_limit


def _login(client, email):
    return _bearer(_web_login(client, email))


@pytest.mark.parametrize("path,body", [
    ("/auth/change-password", {"current_password": "wrong-password-1", "new_password": "whatever-new-1"}),
    ("/auth/delete-account", {"password": "wrong-password-1"}),
])
def test_account_routes_are_limited_per_user(client, small, path, body):
    scope = path.rsplit("/", 1)[1]
    small(scope, 2)
    alice, bob = _login(client, "lim-alice@example.com"), _login(client, "lim-bob@example.com")
    assert [client.post(f"{API}{path}", json=body, headers=alice).status_code for _ in range(2)] == [403, 403]
    res = client.post(f"{API}{path}", json=body, headers=alice)
    assert res.status_code == 429 and "Retry-After" in res.headers
    assert client.post(f"{API}{path}", json=body, headers=bob).status_code == 403  # Bob's own budget


@pytest.mark.parametrize("path,body", [
    ("/auth/change-password", {"current_password": "wrong-password-1", "new_password": "whatever-new-1"}),
    ("/auth/delete-account", {"password": "wrong-password-1"}),
])
def test_account_routes_are_limited_per_ip_across_accounts(client, small, path, body):
    scope = path.rsplit("/", 1)[1]
    small(f"{scope}-ip", 3)
    users = [_login(client, f"lim-ip-{n}@example.com") for n in range(4)]
    codes = [client.post(f"{API}{path}", json=body, headers=h).status_code for h in users]
    assert codes == [403, 403, 403, 429]


@pytest.mark.parametrize("method,path,scope,body", [
    ("post", "/rules/preview", "rules-preview", {"pattern": "COFFEE", "match_type": "contains", "match_field": "any"}),
    ("get", "/rules/impact", "rules-impact", None),
    ("get", "/banking/transactions", "transactions", None),
])
def test_decrypt_heavy_reads_are_limited_per_user(client, small, method, path, scope, body):
    small(scope, 2)
    alice, bob = _login(client, "read-alice@example.com"), _login(client, "read-bob@example.com")
    def call(h):
        return getattr(client, method)(f"{API}{path}", headers=h, **({"json": body} if body else {}))
    assert [call(alice).status_code for _ in range(2)] == [200, 200]
    assert call(alice).status_code == 429
    assert call(bob).status_code == 200


def test_bulk_pack_creation_is_limited_per_user(client, small):
    small("packs-bulk", 1)
    alice = _login(client, "bulk-alice@example.com")
    body = {"name": "Mine", "rules": [{"pattern": "TESCO", "category": "Groceries"}]}
    assert client.post(f"{API}/rules/packs/bulk", json=body, headers=alice).status_code == 201
    assert client.post(f"{API}/rules/packs/bulk", json=body, headers=alice).status_code == 429


def test_health_is_503_with_a_fixed_body_when_the_database_is_down(client):
    class Down:
        def execute(self, *a, **k):
            raise OperationalError("SELECT 1", {}, Exception("could not connect to server at db.internal:5432"))

    app.dependency_overrides[get_db] = lambda: Down()
    try:
        res = client.get(f"{API}/health")
    finally:
        app.dependency_overrides.pop(get_db, None)
    assert res.status_code == 503
    assert res.json() == {"status": "degraded", "database": "unhealthy"}
    assert "db.internal" not in res.text and "connect" not in res.text


def test_health_is_200_when_the_database_answers(client):
    res = client.get(f"{API}/health")
    assert (res.status_code, res.json()) == (200, {"status": "healthy", "database": "healthy"})


def test_flows_per_holding_are_capped(client, db_session, monkeypatch):
    monkeypatch.setattr(assets_router, "FLOWS_PER_ASSET_MAX", 2)
    h = _login(client, "flows@example.com")
    asset_id = client.post(f"{API}/assets", json={"name": "Fund", "asset_type": "investment", "value": "10"},
                           headers=h).json()["id"]
    flow = {"amount": "50"}
    assert [client.post(f"{API}/assets/{asset_id}/flows", json=flow, headers=h).status_code for _ in range(2)] == [201, 201]
    res = client.post(f"{API}/assets/{asset_id}/flows", json=flow, headers=h)
    assert res.status_code == 409
    assert res.json()["detail"] == "This holding has 2 recorded movements already. Delete an old one to add another."
    assert db_session.query(AssetFlow).count() == 2


def test_the_flows_cap_is_1000():
    assert assets_router.FLOWS_PER_ASSET_MAX == 1000
