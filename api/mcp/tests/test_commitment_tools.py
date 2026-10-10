"""update_commitment / dismiss_commitment (T-08-9).

The API enforces scope, bounds, ownership, dry_run, idempotency and audit
(api/tests/integration/test_commitment_writes_api.py). Here: the tools send
exactly the fields asked for, preview by default, check the planning scope as
a second layer, and never let a model-supplied id shape the URL path.
"""
import json

import pytest

from test_planned_events_tools import FakeApi, _call

RULE = "6f1c0c4e-0000-4000-8000-0000000000bb"
CARD = "6f1c0c4e-0000-4000-8000-0000000000cc"
BATCH = "6f1c0c4e-0000-4000-8000-0000000000dd"
KEY = {"idempotency_key": "upd-netflix-0001"}


def _sent(api):
    [sent] = [r for r in api.requests if "/planning/" in r.url.path]
    return sent.method, sent.url.path, json.loads(sent.content)


def test_update_previews_by_default_and_sends_only_the_given_fields():
    api = FakeApi()
    result = _call(api, "update_commitment", {"commitment_id": RULE, "amount": "12.99", **KEY})
    assert not result.get("isError"), result
    assert _sent(api) == (
        "POST", f"/api/v1/planning/commitments/{RULE}/update",
        {"amount": "12.99", "dry_run": True, **KEY},
    )


def test_update_passes_every_allowed_field_when_given():
    api = FakeApi()
    _call(api, "update_commitment", {
        "commitment_id": RULE, "label": "Rent", "cadence": "every_n_months", "interval_months": 3,
        "next_date": "2026-11-01", "status": "confirmed", "card_account_id": CARD, "batch_id": BATCH,
        "dry_run": False, **KEY,
    })
    _, _, body = _sent(api)
    assert body == {
        "label": "Rent", "cadence": "every_n_months", "interval_months": 3, "next_date": "2026-11-01",
        "status": "confirmed", "card_account_id": CARD, "batch_id": BATCH, "dry_run": False, **KEY,
    }


def test_clear_card_sends_an_explicit_null_link():
    api = FakeApi()
    _call(api, "update_commitment", {"commitment_id": RULE, "clear_card": True, **KEY})
    _, _, body = _sent(api)
    assert body == {"card_account_id": None, "dry_run": True, **KEY}


def test_dismiss_previews_by_default_and_can_join_a_batch():
    api = FakeApi()
    _call(api, "dismiss_commitment", {"commitment_id": RULE, "batch_id": BATCH, **KEY})
    assert _sent(api) == (
        "POST", f"/api/v1/planning/commitments/{RULE}/dismiss", {"batch_id": BATCH, "dry_run": True, **KEY},
    )


@pytest.mark.parametrize("tool", ["update_commitment", "dismiss_commitment"])
def test_writes_need_the_planning_scope_here_too(tool):
    api = FakeApi(scope="finance:read")
    result = _call(api, tool, {"commitment_id": RULE, "amount": "1", **KEY} if tool == "update_commitment"
                   else {"commitment_id": RULE, **KEY})
    assert result["isError"] is True and "planning" in result["content"][0]["text"]
    assert [r for r in api.requests if "/planning/" in r.url.path] == []


TRAVERSAL = ["../../audit/x/undo", "..%2F..%2Fbanking", "abc", "", f"{RULE}/../../x"]


@pytest.mark.parametrize("bad", TRAVERSAL)
@pytest.mark.parametrize("tool", ["update_commitment", "dismiss_commitment"])
def test_a_commitment_id_that_is_not_a_uuid_never_reaches_the_api(tool, bad):
    api = FakeApi()
    args = {"commitment_id": bad, **KEY, **({"amount": "1"} if tool == "update_commitment" else {})}
    result = _call(api, tool, args)
    assert result["isError"] is True and "commitments tool" in result["content"][0]["text"]
    # The only request is the bearer check every remote call makes first.
    assert [r.url.path for r in api.requests] == ["/api/v1/oauth/token-info"]


@pytest.mark.parametrize("field", ["card_account_id", "batch_id"])
def test_ids_in_the_body_must_be_uuids_too(field):
    api = FakeApi()
    result = _call(api, "update_commitment", {"commitment_id": RULE, field: "../x", **KEY})
    assert result["isError"] is True
    assert [r.url.path for r in api.requests] == ["/api/v1/oauth/token-info"]


def test_not_found_names_commitments_not_planned_events():
    api = FakeApi(status=404, body={"detail": "Not found"})
    text = _call(api, "dismiss_commitment", {"commitment_id": RULE, **KEY})["content"][0]["text"]
    assert "commitment" in text and "planned" not in text
