"""Claude's paid-back tools (T-03-5 P9; PRD "MCP contract", ACs 18-23 at the
tool layer, error table).

list_repayment_candidates reads POST /repayments/candidates with finance:read.
mark_paid_back and unmark_paid_back need finance:repayments.write (a second
layer; the API enforces it), preview by default, parse every id as a UUID,
pass on only the contract's fields, and turn API errors into the PRD's short
sentences. Bank text is data.
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
CREDIT = "11111111-2222-3333-4444-555555555555"
SPEND = "66666666-7777-8888-9999-000000000000"
WRITE = "finance:read finance:repayments.write"


class FakeApi:
    def __init__(self, scope=WRITE, status=200, body=None):
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
                for r in self.requests if "/repayments" in r.url.path]


def _call(api, name, arguments):
    settings = Settings.from_env({"MCP_TRANSPORT": "http", "MCP_PUBLIC_URL": PUBLIC})
    app = create_server(settings, api_transport=httpx.MockTransport(api)).streamable_http_app()
    with TestClient(app, base_url=PUBLIC) as c:
        r = c.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                 "params": {"name": name, "arguments": arguments}},
                   headers={**MCP_HEADERS, "Authorization": "Bearer good"})
    return r.json()["result"]


def _text(result) -> str:
    # FastMCP prefixes a tool error with "Error executing tool …"; the sentence after it is ours.
    return result["content"][0]["text"]


# --- list_repayment_candidates -------------------------------------------------------------


def test_candidates_need_only_read_and_send_only_the_hints_given():
    api = FakeApi(scope="finance:read", body={"candidates": []})
    result = _call(api, "list_repayment_candidates", {"payer": "Sam", "spend_date": "2026-11-07"})
    assert result["isError"] is False
    assert api.calls() == [("POST", "/api/v1/repayments/candidates",
                            {"payer": "Sam", "spend_date": "2026-11-07", "include_marked": False, "limit": 20})]


def test_candidate_validation_errors_are_summarised():
    api = FakeApi(scope="finance:read", status=422,
                  body={"detail": [{"loc": ["body", "limit"], "msg": "must be at most 50"}]})
    result = _call(api, "list_repayment_candidates", {"limit": 51})
    assert result["isError"] is True and _text(result).endswith("Invalid input: limit: must be at most 50")


# --- mark_paid_back -------------------------------------------------------------------------


def test_mark_previews_by_default_and_passes_only_the_contracts_fields():
    api = FakeApi()
    result = _call(api, "mark_paid_back", {
        "marks": [{"credit_id": CREDIT, "spend_id": SPEND, "amount_pounds": "60.00"},
                  {"credit_id": CREDIT, "category": "Eating out"}],
        "idempotency_key": "key-00000001"})
    assert result["isError"] is False
    assert api.calls() == [("POST", "/api/v1/planning/repayments/mark", {
        "marks": [{"credit_id": CREDIT, "spend_id": SPEND, "amount_pounds": "60.00"},
                  {"credit_id": CREDIT, "category": "Eating out"}],
        "idempotency_key": "key-00000001", "dry_run": True, "accept_warnings": False})]


@pytest.mark.parametrize("mark", [
    {"credit_id": "Sam", "category": "Eating out"},
    {"credit_id": CREDIT, "spend_id": "../../audit/x/undo"},
    {"credit_id": CREDIT, "category": "Eating out", "user_id": CREDIT},
    {"credit_id": CREDIT, "amount_pounds": 60},
    "Sam £60",
])
def test_mark_refuses_anything_outside_the_contract(mark):
    api = FakeApi()
    result = _call(api, "mark_paid_back", {"marks": [mark], "idempotency_key": "key-00000001"})
    assert result["isError"] is True
    assert api.calls() == []


def test_mark_takes_one_to_eight():
    api = FakeApi()
    result = _call(api, "mark_paid_back", {"marks": [{"credit_id": CREDIT, "category": "Eating out"}] * 9,
                                           "idempotency_key": "key-00000001"})
    assert result["isError"] is True and api.calls() == []


@pytest.mark.parametrize("tool,args", [
    ("mark_paid_back", {"marks": [{"credit_id": CREDIT, "category": "Eating out"}], "idempotency_key": "key-00000001"}),
    ("unmark_paid_back", {"mark_id": CREDIT, "idempotency_key": "key-00000001"}),
])
def test_without_the_scope_nothing_is_called_and_the_power_is_named(tool, args):
    api = FakeApi(scope="finance:read finance:budgets.write")
    result = _call(api, tool, args)
    assert result["isError"] is True
    assert _text(result).endswith("This connection wasn't granted permission to mark payments as paid back. "
                                  "Reconnect and approve it.")
    assert api.calls() == []


@pytest.mark.parametrize("tool,args,status,body,expected", [
    ("mark_paid_back", {"marks": [{"credit_id": CREDIT, "category": "Eating out"}]}, 404, {"detail": "Not found"},
     "Not found: no payment of yours has that id."),
    ("unmark_paid_back", {"mark_id": CREDIT}, 404, {"detail": "Not found"},
     "Not found: no active mark of yours that Claude made has that id."),
    ("mark_paid_back", {"marks": [{"credit_id": CREDIT, "category": "Eating out"}]}, 422,
     {"detail": "That is more than this payment. Up to £0.00 is unmarked."},
     "That is more than this payment. Up to £0.00 is unmarked."),
    ("mark_paid_back", {"marks": [{"credit_id": CREDIT, "category": "Eating out"}]}, 403, {"detail": "x"},
     "This connection wasn't granted permission to mark payments as paid back. Reconnect and approve it."),
    ("mark_paid_back", {"marks": [{"credit_id": CREDIT, "category": "Eating out"}]}, 500, {"detail": "boom"},
     "The change failed (500)."),
])
def test_api_errors_become_the_prds_sentences(tool, args, status, body, expected):
    api = FakeApi(status=status, body=body)
    result = _call(api, tool, {**args, "idempotency_key": "key-00000001"})
    assert result["isError"] is True and _text(result).endswith(expected)


# --- unmark_paid_back -----------------------------------------------------------------------


def test_unmark_posts_by_id_with_a_preview_by_default():
    api = FakeApi()
    result = _call(api, "unmark_paid_back", {"mark_id": CREDIT, "idempotency_key": "key-00000001"})
    assert result["isError"] is False
    assert api.calls() == [("POST", f"/api/v1/planning/repayments/{CREDIT}/unmark",
                            {"idempotency_key": "key-00000001", "dry_run": True})]


@pytest.mark.parametrize("bad", ["Sam", "../../audit/x/undo", ""])
def test_a_mark_is_addressed_by_its_uuid_only(bad):
    api = FakeApi()
    result = _call(api, "unmark_paid_back", {"mark_id": bad, "idempotency_key": "key-00000001"})
    assert result["isError"] is True and api.calls() == []
