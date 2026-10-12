"""Consent for Claude's budget writes (T-09-12; HQ design
nilu-s08-claude-changes.md section 5, K9-K11; sec's consent criteria).

`finance:budgets.write` is granted only when the user ticks its box, which
sends it in the consent decision. The server grants exactly the scopes in
that decision, so nothing else implies it (planning.write least of all).
An existing grant can't gain it (a refresh can't widen), and revoking a
grant, or a password change, stops the next budget write, as for
planning.write. Calls the real route, POST /planning/budgets/set, as a dry
run.
"""
from datetime import datetime, timezone

import pytest

from app.models import OAuthGrant
from tests.integration.test_oauth import PASSWORD, READ, WRITE as RULES, _bearer, _connect, _refresh

BUDGETS = "finance:budgets.write"
PLANNING = "finance:planning.write"
SYNC = "finance:sync"
SET = "/api/v1/planning/budgets/set"


PAST_AUTH = 422  # through the scope check, then refused: the user has no such category


def _set(client, token):
    body = {"budgets": [{"category": "Groceries", "limit_pounds": 100}], "dry_run": True,
            "idempotency_key": "consent-probe-1"}
    return client.post(SET, json=body, headers=_bearer(token))


@pytest.mark.parametrize("scopes", [(READ,), (READ, PLANNING), (READ, RULES, PLANNING, SYNC)])
def test_without_the_box_there_is_no_budgets_scope(client, scopes):
    _, _, tokens = _connect(client, scopes=scopes)
    assert BUDGETS not in tokens["scope"].split()
    r = _set(client, tokens["access_token"])
    assert r.status_code == 403
    assert BUDGETS in r.headers["www-authenticate"]


def test_the_box_grants_exactly_read_and_budgets(client):
    _, _, tokens = _connect(client, scopes=(READ, BUDGETS))
    assert tokens["scope"].split() == [READ, BUDGETS]
    assert _set(client, tokens["access_token"]).status_code == PAST_AUTH


def test_every_box_ticked_grants_each_scope_once(client):
    _, _, tokens = _connect(client, scopes=(READ, RULES, PLANNING, SYNC, BUDGETS))
    assert sorted(tokens["scope"].split()) == sorted([READ, RULES, PLANNING, SYNC, BUDGETS])


def test_budgets_never_implies_planning(client):
    _, _, tokens = _connect(client, scopes=(READ, BUDGETS))
    r = client.post("/api/v1/planning/planned-events", json={"dry_run": True, "idempotency_key": "consent-probe-2"},
                    headers=_bearer(tokens["access_token"]))
    assert r.status_code == 403


def test_an_existing_grant_cannot_gain_the_budgets_scope_on_refresh(client):
    _, client_id, tokens = _connect(client, scopes=(READ, RULES, PLANNING, SYNC))
    widened = _refresh(client, tokens["refresh_token"], client_id, scope=f"{READ} {BUDGETS}")
    assert widened.status_code == 400 and widened.json()["error"] == "invalid_scope"
    kept = _refresh(client, tokens["refresh_token"], client_id)
    assert kept.status_code == 200, kept.text
    assert BUDGETS not in kept.json()["scope"].split()


def test_a_revoked_grant_stops_the_next_budget_write(client, db_session):
    _, _, tokens = _connect(client, scopes=(READ, BUDGETS))
    assert _set(client, tokens["access_token"]).status_code == PAST_AUTH
    grant = db_session.query(OAuthGrant).one()
    grant.revoked_at = datetime.now(timezone.utc)
    db_session.commit()
    assert _set(client, tokens["access_token"]).status_code == 401


def test_a_password_change_stops_the_next_budget_write(client):
    web, _, tokens = _connect(client, scopes=(READ, BUDGETS))
    r = client.post("/api/v1/auth/change-password",
                    json={"current_password": PASSWORD, "new_password": "anotherpassword456"}, headers=_bearer(web))
    assert r.status_code == 200
    assert _set(client, tokens["access_token"]).status_code == 401
