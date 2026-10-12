"""Claude's budget tools (T-09-5; sec's T-09-5 criteria).

list_budgets reads GET /budgets. set_budgets, pause_budget, resume_budget
and remove_budget need the finance:budgets.write scope (a second layer; the
API enforces it), address a budget by its UUID only, and pass on only a
category and a whole-pound limit per entry. API errors become short fixed
messages.
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
BUDGET_ID = "11111111-2222-3333-4444-555555555555"


class FakeApi:
    def __init__(self, scope="finance:read finance:budgets.write", status=200, body=None):
        self.scope, self.status = scope, status
        self.body = {"dry_run": True, "results": []} if body is None else body
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path.endswith("/oauth/token-info"):
            return httpx.Response(200, json={"active": True, "client_id": "c", "scope": self.scope, "aud": RESOURCE})
        return httpx.Response(self.status, json=self.body)

    def calls(self):
        return [(r.method, r.url.path, json.loads(r.content) if r.content else None)
                for r in self.requests if "/budgets" in r.url.path]


def _call(api, name, arguments):
    settings = Settings.from_env({"MCP_TRANSPORT": "http", "MCP_PUBLIC_URL": PUBLIC})
    app = create_server(settings, api_transport=httpx.MockTransport(api)).streamable_http_app()
    with TestClient(app, base_url=PUBLIC) as c:
        r = c.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                 "params": {"name": name, "arguments": arguments}},
                   headers={**MCP_HEADERS, "Authorization": "Bearer good"})
    return r.json()["result"]


def _text(result) -> str:
    return result["content"][0]["text"]


def test_set_budgets_posts_the_set_with_a_preview_by_default():
    api = FakeApi()
    result = _call(api, "set_budgets", {"budgets": [{"category": "Eating out", "limit_pounds": 150}],
                                        "idempotency_key": "key-00000001"})
    assert result["isError"] is False
    assert api.calls() == [("POST", "/api/v1/planning/budgets/set",
                            {"budgets": [{"category": "Eating out", "limit_pounds": 150}],
                             "idempotency_key": "key-00000001", "dry_run": True})]


@pytest.mark.parametrize("entry", [
    {"category": "Eating out", "limit_pounds": 150, "paused": True},
    {"category": "Eating out", "limit_pounds": "150"},
    {"category": "Eating out", "limit_pounds": True},
    {"limit_pounds": 150},
    "Eating out",
])
def test_set_budgets_refuses_anything_but_a_category_and_whole_pounds(entry):
    api = FakeApi()
    result = _call(api, "set_budgets", {"budgets": [entry], "idempotency_key": "key-00000001"})
    assert result["isError"] is True
    assert api.calls() == []


@pytest.mark.parametrize("tool,action", [("pause_budget", "pause"), ("resume_budget", "resume"),
                                         ("remove_budget", "remove")])
def test_actions_post_by_id(tool, action):
    api = FakeApi()
    result = _call(api, tool, {"budget_id": BUDGET_ID, "idempotency_key": "key-00000001", "dry_run": False})
    assert result["isError"] is False
    assert api.calls() == [("POST", f"/api/v1/planning/budgets/{BUDGET_ID}/{action}",
                            {"idempotency_key": "key-00000001", "dry_run": False})]


@pytest.mark.parametrize("bad", ["Eating out", "../../audit/x/undo", ""])
def test_a_budget_is_addressed_by_its_uuid_only(bad):
    api = FakeApi()
    result = _call(api, "pause_budget", {"budget_id": bad, "idempotency_key": "key-00000001"})
    assert result["isError"] is True
    assert api.calls() == []


@pytest.mark.parametrize("tool,args", [
    ("set_budgets", {"budgets": [{"category": "Eating out", "limit_pounds": 150}], "idempotency_key": "key-00000001"}),
    ("pause_budget", {"budget_id": BUDGET_ID, "idempotency_key": "key-00000001"}),
])
def test_without_the_budgets_scope_nothing_is_called(tool, args):
    api = FakeApi(scope="finance:read finance:planning.write")
    result = _call(api, tool, args)
    assert result["isError"] is True and "finance:budgets.write" in _text(result)
    assert api.calls() == []


def test_list_budgets_needs_only_read():
    api = FakeApi(scope="finance:read", body={"budgets": []})
    result = _call(api, "list_budgets", {})
    assert result["isError"] is False
    assert api.calls() == [("GET", "/api/v1/budgets", None)]


@pytest.mark.parametrize("status,body,expected", [
    (404, {"detail": "Budget not found"}, "no active budget of yours"),
    (403, {"detail": "x"}, "permission to change budgets"),
    (422, {"detail": "That budget is already paused."}, "already paused"),
])
def test_api_errors_become_short_messages(status, body, expected):
    api = FakeApi(status=status, body=body)
    result = _call(api, "pause_budget", {"budget_id": BUDGET_ID, "idempotency_key": "key-00000001"})
    assert result["isError"] is True and expected in _text(result)
