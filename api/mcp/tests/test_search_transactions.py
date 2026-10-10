"""search_transactions over both transports, with the REST API faked.

http goes through the real TokenInfoVerifier (the token is checked against
the API's token-info, as in production), stdio through password login. The
API itself (authz, validation, limits) is tested in api/tests.
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
RESULT = {"items": [], "total": 0, "total_amount": "0", "page": 1, "page_size": 50, "frm": "2026-07-01", "to": "2026-09-30"}


class FakeApi:
    def __init__(self, status=200, body=None):
        self.status, self.body = status, body if body is not None else RESULT
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path.endswith("/oauth/token-info"):
            if request.headers.get("authorization") != "Bearer good":
                return httpx.Response(401)
            return httpx.Response(200, json={"active": True, "client_id": "c", "scope": "finance:read", "aud": RESOURCE})
        if path.endswith("/auth/login"):
            return httpx.Response(200, json={"access_token": "pw-token"})
        headers = {"Retry-After": "17"} if self.status == 429 else {}
        return httpx.Response(self.status, json=self.body, headers=headers)

    def searches(self):
        return [r for r in self.requests if r.url.path.endswith("/banking/transactions/search")]


def _http_call(api, args):
    settings = Settings.from_env({"MCP_TRANSPORT": "http", "MCP_PUBLIC_URL": PUBLIC})
    app = create_server(settings, api_transport=httpx.MockTransport(api)).streamable_http_app()
    with TestClient(app, base_url=PUBLIC) as c:
        r = c.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                  "params": {"name": "search_transactions", "arguments": args}},
            headers={**MCP_HEADERS, "Authorization": "Bearer good"},
        )
    return r.json()["result"]


def _stdio_server(api):
    settings = Settings.from_env({"FINANCE_EMAIL": "a@b.c", "FINANCE_PASSWORD": "pw"})
    return create_server(settings, api_transport=httpx.MockTransport(api))


class TestHttp:
    def test_posts_the_search_with_the_callers_token(self):
        api = FakeApi()
        result = _http_call(api, {"query": "tesco", "frm": "2026-07-01", "to": "2026-09-30", "page": 2})
        assert not result.get("isError")
        assert json.loads(result["content"][0]["text"]) == RESULT
        [sent] = api.searches()
        assert sent.method == "POST"
        assert sent.headers["authorization"] == "Bearer good"
        assert json.loads(sent.content) == {
            "query": "tesco", "frm": "2026-07-01", "to": "2026-09-30",
            "include_transfers": False, "page": 2, "page_size": 50,
        }
        # The term travels in the body, never in the URL (access logs).
        assert "tesco" not in str(sent.url)

    def test_omitted_dates_are_left_to_the_api(self):
        api = FakeApi()
        _http_call(api, {"query": "tesco"})
        body = json.loads(api.searches()[0].content)
        assert "frm" not in body and "to" not in body

    def test_validation_error_is_short_and_has_no_url(self):
        detail = [{"loc": ["body", "query"], "msg": "Value error, must be 2-100 characters", "input": "x"}]
        result = _http_call(FakeApi(422, {"detail": detail}), {"query": "x"})
        assert result["isError"] is True
        text = result["content"][0]["text"]
        assert "query: Value error, must be 2-100 characters" in text
        assert "http" not in text and "/banking" not in text

    def test_rate_limit_says_when_to_retry(self):
        result = _http_call(FakeApi(429, {"detail": "Too many attempts."}), {"query": "tesco"})
        assert result["isError"] is True
        assert "17" in result["content"][0]["text"]


class TestStdio:
    @pytest.mark.anyio
    async def test_runs_with_password_login(self):
        api = FakeApi()
        server = _stdio_server(api)
        await server.call_tool("search_transactions", {"query": "tesco"})
        [sent] = api.searches()
        assert sent.headers["authorization"] == "Bearer pw-token"
        assert json.loads(sent.content)["query"] == "tesco"


class TestDescriptions:
    @pytest.mark.anyio
    async def test_search_is_read_only_and_describes_results_as_bank_data(self):
        tools = {t.name: t for t in await _stdio_server(FakeApi()).list_tools()}
        tool = tools["search_transactions"]
        assert tool.annotations.readOnlyHint is True
        assert "bank feeds" in tool.description
        assert "total_amount" in tool.description and "credits" in tool.description

    @pytest.mark.anyio
    async def test_forecast_says_a_zero_floor_means_no_overdraft_limit(self):
        tools = {t.name: t for t in await _stdio_server(FakeApi()).list_tools()}
        text = tools["forecast"].description
        assert "floor" in text and "no overdraft limit" in text
