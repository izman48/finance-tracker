"""refresh_banks: ask the API to fetch fresh data from every connected bank.

The API (api/tests/integration/test_bank_sync_api.py) enforces the
`finance:sync` scope, the daily limit and the one-at-a-time guard, and
decides what is returned. Here: the tool calls the one route, checks the
scope as a second layer, is marked as a write so clients ask first, and
turns API errors into short messages with no URL or server detail.
"""
import json

import httpx
import pytest
from starlette.testclient import TestClient

from config import Settings
from server import create_server

PUBLIC = "https://example.com"
RESOURCE = f"{PUBLIC}/mcp"
MCP_HEADERS = {"Accept": "application/json, text/event-stream"}
RESULT = {
    "accounts_synced": 2,
    "transactions_synced": 5,
    "connections": [{"connection_id": "c1", "provider": "MONZO", "status": "synced",
                     "accounts_synced": 2, "transactions_synced": 5}],
}


class FakeApi:
    def __init__(self, scope="finance:read finance:sync", status=200, body=None, headers=None):
        self.scope, self.status = scope, status
        self.body = RESULT if body is None else body
        self.headers = headers or {}
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path.endswith("/oauth/token-info"):
            return httpx.Response(200, json={"active": True, "client_id": "c", "scope": self.scope, "aud": RESOURCE})
        if path.endswith("/auth/login"):
            return httpx.Response(200, json={"access_token": "pw-token"})
        return httpx.Response(self.status, json=self.body, headers=self.headers)

    def calls(self):
        return [(r.method, r.url.path) for r in self.requests if "/banking/" in r.url.path]


def _remote(api):
    """Call the tool through the remote (http) server, as Claude does."""
    settings = Settings.from_env({"MCP_TRANSPORT": "http", "MCP_PUBLIC_URL": PUBLIC})
    app = create_server(settings, api_transport=httpx.MockTransport(api)).streamable_http_app()
    with TestClient(app, base_url=PUBLIC) as c:
        r = c.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "refresh_banks", "arguments": {}}},
            headers={**MCP_HEADERS, "Authorization": "Bearer good"},
        )
    return r.json()["result"]


def _text(result) -> str:
    return result["content"][0]["text"]


def _local(api):
    settings = Settings("stdio", "http://api.test/api/v1", email="e@example.com", password="pw")
    return create_server(settings, api_transport=httpx.MockTransport(api))


def test_posts_the_sync_route_and_returns_its_result():
    api = FakeApi()
    result = _remote(api)

    assert result["isError"] is False
    assert api.calls() == [("POST", "/api/v1/banking/sync")]
    assert json.loads(_text(result))["transactions_synced"] == 5


def test_without_the_sync_scope_nothing_is_called():
    api = FakeApi(scope="finance:read")
    result = _remote(api)

    assert result["isError"] is True
    assert "finance:sync" in _text(result)
    assert api.calls() == []


@pytest.mark.parametrize(
    "status,headers,expected",
    [
        (429, {"Retry-After": "3600"}, "Try again in 3600 seconds"),
        (403, {}, "Reconnect and approve"),
        (400, {}, "No bank is connected"),
        (500, {}, "Sync failed (500)"),
    ],
)
def test_api_errors_become_short_messages(status, headers, expected):
    api = FakeApi(status=status, headers=headers,
                  body={"detail": "https://api.truelayer.com/data/v1 Traceback SECRET"})
    result = _remote(api)

    assert result["isError"] is True
    text = _text(result)
    assert expected in text
    for leak in ("truelayer.com", "Traceback", "SECRET", "/api/v1"):
        assert leak not in text


@pytest.mark.anyio
async def test_local_mode_uses_the_password_session():
    api = FakeApi()
    await _local(api).call_tool("refresh_banks", {})

    assert api.calls() == [("POST", "/api/v1/banking/sync")]


@pytest.mark.anyio
async def test_is_a_non_destructive_write_and_explains_itself():
    tools = {t.name: t for t in await _local(FakeApi()).list_tools()}
    tool = tools["refresh_banks"]

    hints = tool.annotations
    assert hints.readOnlyHint is False
    assert hints.destructiveHint is False
    assert hints.idempotentHint is False
    text = tool.description
    assert "4" in text and "24 hours" in text
    assert "sync_status" in text
    assert "reconnect" in text
    assert "ask" in text.lower()


@pytest.mark.anyio
async def test_sync_status_now_points_at_refresh_banks():
    tools = {t.name: t for t in await _local(FakeApi()).list_tools()}

    assert "refresh_banks" in tools["sync_status"].description
