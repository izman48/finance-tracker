"""add_planned_event / list_planned_events / remove_planned_event (T-08-6).

The API enforces scope, bounds, ownership, dry_run, idempotency and audit
(api/tests). Here: the tools send exactly what the API expects, default to a
preview, check the planning scope as a second layer, and turn API errors
into short messages with no URL or server detail beyond our own fixed text.
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
PREVIEW = {"dry_run": True, "duplicate": False, "audit_id": None, "target_kind": "planned_event",
           "target_id": None, "target_label": "Car insurance", "changes": []}


class FakeApi:
    def __init__(self, scope="finance:read finance:planning.write", status=200, body=None, headers=None):
        self.scope, self.status = scope, status
        self.body = PREVIEW if body is None else body
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
        return [r for r in self.requests if "/planning/" in r.url.path]


def _call(api, tool, args):
    settings = Settings.from_env({"MCP_TRANSPORT": "http", "MCP_PUBLIC_URL": PUBLIC})
    app = create_server(settings, api_transport=httpx.MockTransport(api)).streamable_http_app()
    with TestClient(app, base_url=PUBLIC) as c:
        r = c.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": args}},
            headers={**MCP_HEADERS, "Authorization": "Bearer good"},
        )
    return r.json()["result"]


ITEM = "6f1c0c4e-0000-4000-8000-0000000000aa"
ADD = {"name": "Car insurance", "amount": "200.00", "date": "2026-11-01", "direction": "expense",
       "idempotency_key": "add-car-insurance-1"}


def test_add_previews_by_default_and_sends_the_api_body():
    api = FakeApi()
    result = _call(api, "add_planned_event", ADD)
    assert not result.get("isError"), result
    [sent] = api.calls()
    assert (sent.method, sent.url.path) == ("POST", "/api/v1/planning/planned-events")
    assert json.loads(sent.content) == {**ADD, "dry_run": True}


def test_add_applies_only_when_asked_and_passes_an_account():
    api = FakeApi()
    _call(api, "add_planned_event", {**ADD, "dry_run": False, "account_id": "6f1c0c4e-0000-4000-8000-000000000001"})
    body = json.loads(api.calls()[0].content)
    assert body["dry_run"] is False and body["account_id"] == "6f1c0c4e-0000-4000-8000-000000000001"


def test_remove_previews_by_default_with_dry_run_in_the_body():
    api = FakeApi()
    _call(api, "remove_planned_event", {"item_id": ITEM, "idempotency_key": "remove-abc-0001"})
    [sent] = api.calls()
    assert (sent.method, sent.url.path) == ("POST", f"/api/v1/planning/planned-events/{ITEM}/remove")
    assert json.loads(sent.content) == {"dry_run": True, "idempotency_key": "remove-abc-0001"}


def test_list_reads_the_planning_route():
    api = FakeApi(body={"items": [], "truncated": False})
    _call(api, "list_planned_events", {})
    [sent] = api.calls()
    assert (sent.method, sent.url.path) == ("GET", "/api/v1/planning/planned-events")


@pytest.mark.parametrize("tool,args", [("add_planned_event", ADD), ("remove_planned_event", {"item_id": ITEM, "idempotency_key": "remove-x-00001"})])
def test_writes_need_the_planning_scope_here_too(tool, args):
    api = FakeApi(scope="finance:read")
    result = _call(api, tool, args)
    assert result["isError"] is True
    assert "planning" in result["content"][0]["text"]
    assert api.calls() == []


@pytest.mark.parametrize("status,body,headers,expected", [
    (404, {"detail": "Planned event not found"}, {}, "Not found"),
    (409, {"detail": "This idempotency_key was already used for a different request."}, {}, "already used"),
    (422, {"detail": [{"loc": ["body", "amount"], "msg": "Input should be greater than 0"}]}, {}, "amount: Input should be greater than 0"),
    (429, {"detail": "Too many attempts."}, {"Retry-After": "120"}, "120 seconds"),
    (500, {"detail": "Traceback at http://api:8000/secret"}, {}, "failed (500)"),
])
def test_api_errors_become_short_messages(status, body, headers, expected):
    api = FakeApi(status=status, body=body, headers=headers)
    result = _call(api, "add_planned_event", ADD)
    text = result["content"][0]["text"]
    assert result["isError"] is True and expected in text
    assert "http" not in text and "Traceback" not in text


@pytest.mark.parametrize("item_id", ["../../banking/disconnect", "abc", "1; drop", ""])
def test_remove_refuses_an_item_id_that_is_not_a_uuid(item_id):
    api = FakeApi()
    result = _call(api, "remove_planned_event", {"item_id": item_id, "idempotency_key": "remove-bad-0001"})
    assert result["isError"] is True and "list_planned_events" in result["content"][0]["text"]
    assert api.calls() == []
