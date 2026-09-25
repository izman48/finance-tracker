"""The remote (streamable HTTP) server end to end, with the REST API mocked."""
import json

import httpx
import pytest
from starlette.testclient import TestClient

from auth import SCOPE_READ, SCOPE_RULES_WRITE
from config import Settings
from server import create_server

PUBLIC = "https://example.com"
RESOURCE = f"{PUBLIC}/mcp"
METADATA = f"{PUBLIC}/.well-known/oauth-protected-resource/mcp"
MCP_HEADERS = {"Accept": "application/json, text/event-stream"}


class FakeApi:
    """Stands in for the REST API: token-info plus whatever a test routes."""

    def __init__(self, scopes=(SCOPE_READ,)):
        self.scopes = " ".join(scopes)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path.endswith("/oauth/token-info"):
            if request.headers.get("authorization") != "Bearer good":
                return httpx.Response(401)
            return httpx.Response(
                200,
                json={"active": True, "client_id": "c", "scope": self.scopes, "aud": RESOURCE},
            )
        if request.url.path.endswith("/analytics/summary"):
            return httpx.Response(200, json={"safe_to_spend": "12.34"})
        return httpx.Response(200, json={"created": True})

    def data_requests(self):
        return [r for r in self.requests if not r.url.path.endswith("/oauth/token-info")]


@pytest.fixture
def api():
    return FakeApi()


@pytest.fixture
def client(api):
    settings = Settings.from_env({"MCP_TRANSPORT": "http", "MCP_PUBLIC_URL": PUBLIC})
    app = create_server(settings, api_transport=httpx.MockTransport(api)).streamable_http_app()
    with TestClient(app, base_url=PUBLIC) as c:
        yield c


def _rpc(method, params=None, id_=1):
    return {"jsonrpc": "2.0", "id": id_, "method": method, "params": params or {}}


def _call(client, tool, args=None, token="good"):
    return client.post(
        "/mcp",
        json=_rpc("tools/call", {"name": tool, "arguments": args or {}}),
        headers={**MCP_HEADERS, "Authorization": f"Bearer {token}"},
    )


def test_protected_resource_metadata_points_at_the_issuer(client):
    r = client.get("/.well-known/oauth-protected-resource/mcp")
    assert r.status_code == 200
    body = r.json()
    assert body["resource"] == RESOURCE
    assert [s.rstrip("/") for s in body["authorization_servers"]] == [PUBLIC]


def test_no_token_is_401_with_discovery_hint(client, api):
    r = client.post("/mcp", json=_rpc("tools/list"), headers=MCP_HEADERS)
    assert r.status_code == 401
    assert f'resource_metadata="{METADATA}"' in r.headers["www-authenticate"]
    assert api.data_requests() == []


def test_rejected_token_is_401(client, api):
    r = client.post(
        "/mcp", json=_rpc("tools/list"), headers={**MCP_HEADERS, "Authorization": "Bearer bad"}
    )
    assert r.status_code == 401
    assert api.data_requests() == []


def test_foreign_host_header_is_refused(client):
    r = client.post(
        "/mcp",
        json=_rpc("tools/list"),
        headers={**MCP_HEADERS, "Authorization": "Bearer good", "Host": "evil.example"},
    )
    assert r.status_code in (400, 421)


def test_tools_are_listed_for_a_valid_token(client):
    r = client.post(
        "/mcp", json=_rpc("tools/list"), headers={**MCP_HEADERS, "Authorization": "Bearer good"}
    )
    assert r.status_code == 200
    names = {t["name"] for t in r.json()["result"]["tools"]}
    assert {"cashflow_summary", "spending", "create_rule_pack"} <= names


def test_tool_call_forwards_the_callers_token(client, api):
    r = _call(client, "cashflow_summary")
    assert r.status_code == 200
    result = r.json()["result"]
    assert not result.get("isError")
    assert json.loads(result["content"][0]["text"]) == {"safe_to_spend": "12.34"}
    [sent] = api.data_requests()
    assert sent.headers["authorization"] == "Bearer good"


def test_rule_pack_needs_the_write_scope(client, api):
    r = _call(client, "create_rule_pack", {"name": "p", "rules": []})
    result = r.json()["result"]
    assert result["isError"] is True
    assert SCOPE_RULES_WRITE in result["content"][0]["text"]
    assert api.data_requests() == []


def test_rule_pack_with_the_write_scope_is_created(api):
    api.scopes = f"{SCOPE_READ} {SCOPE_RULES_WRITE}"
    settings = Settings.from_env({"MCP_TRANSPORT": "http", "MCP_PUBLIC_URL": PUBLIC})
    app = create_server(settings, api_transport=httpx.MockTransport(api)).streamable_http_app()
    with TestClient(app, base_url=PUBLIC) as c:
        r = _call(c, "create_rule_pack", {"name": "p", "rules": []})
    assert not r.json()["result"].get("isError")
    [sent] = api.data_requests()
    assert sent.url.path.endswith("/rules/packs/bulk")
