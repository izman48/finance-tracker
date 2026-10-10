"""Every account id a write accepts must belong to the caller (T-08-2).

Two parts:

* Behaviour: for each write route that takes an account id, user A naming
  user B's account (or an unknown id) gets 404 and the stored rows are
  byte-for-byte unchanged (raw SQL snapshot, so ciphertext is compared too).
* Enumeration: walk `app.routes` and find every write route whose path,
  query or body (including nested models) has a field ending in
  `account_id`. Each one must have a behavioural case below, so a new route
  or field can't skip the check unnoticed.
"""
import types
import typing
import uuid
from collections.abc import Callable
from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from pydantic import BaseModel
from sqlalchemy import text

from app.core import user_crypto
from app.main import app
from app.models import AccountSetting, CommitmentRule, User
from tests.integration.test_transactions_endpoint import _account, _dek_from_token

WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
API = "/api/v1"


# --- enumeration ---------------------------------------------------------


def _model_account_fields(annotation, prefix: str = "") -> set[str]:
    """Dotted names of every field ending in `account_id`, at any depth."""
    found: set[str] = set()
    origin = typing.get_origin(annotation)
    if origin is not None or isinstance(annotation, types.UnionType):
        for arg in typing.get_args(annotation):
            found |= _model_account_fields(arg, prefix)
        return found
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        for name, field in annotation.model_fields.items():
            path = f"{prefix}{name}"
            if name.endswith("account_id"):
                found.add(path)
            found |= _model_account_fields(field.annotation, f"{path}.")
    return found


def account_id_inputs(routes) -> set[tuple[str, str, str]]:
    """(method, path, field) for every write input named *account_id."""
    found: set[tuple[str, str, str]] = set()
    for route in routes:
        if not isinstance(route, APIRoute):
            continue
        dependant = route.dependant
        names = {
            p.name
            for p in dependant.path_params + dependant.query_params
            if p.name.endswith("account_id")
        }
        for body in dependant.body_params:
            names |= _model_account_fields(body.field_info.annotation)
        for method in route.methods & WRITE_METHODS:
            found |= {(method, route.path, name) for name in names}
    return found


# --- fixtures --------------------------------------------------------------


def _login(client, email: str) -> str:
    password = "securepassword123"
    assert client.post(
        f"{API}/auth/register", json={"email": email, "password": password}
    ).status_code == 201
    res = client.post(f"{API}/auth/login", data={"username": email, "password": password})
    assert res.status_code == 200
    return res.json()["access_token"]


class World:
    """User A (the caller) and user B (the victim), one account each."""

    def __init__(self, client, db):
        self.client = client
        self.db = db
        token_b = _login(client, "b@example.com")
        token_a = _login(client, "a@example.com")
        self.user_a = db.query(User).filter(User.email == "a@example.com").one()
        user_b = db.query(User).filter(User.email == "b@example.com").one()

        ctx = user_crypto.current_dek.set(_dek_from_token(token_b))
        try:
            self.b_account_id = _account(db, user_b.id, atype="CREDIT_CARD", name="B card").id
        finally:
            user_crypto.current_dek.reset(ctx)

        self.dek_a = _dek_from_token(token_a)
        ctx = user_crypto.current_dek.set(self.dek_a)
        try:
            user_a_id = self.user_a.id
            self.a_account_id = _account(db, user_a_id, name="A current").id
            self.a_card_id = _account(db, user_a_id, atype="CREDIT_CARD", name="A card").id
            commitment = CommitmentRule(
                user_id=user_a_id, direction="expense", label="Gym",
                amount=30, cadence="monthly", next_date=date(2026, 11, 1),
                account_id=self.a_account_id, source="manual", status="confirmed",
            )
            db.add(commitment)
            db.add(AccountSetting(
                user_id=user_a_id, account_id=self.a_card_id, role="credit",
                pay_from_account_id=self.a_account_id,
            ))
            db.commit()
            # Plain ids only: touching an expired ORM row outside A's DEK fails.
            self.commitment_id = commitment.id
        finally:
            user_crypto.current_dek.reset(ctx)
        client.headers["Authorization"] = f"Bearer {token_a}"

    def snapshot(self) -> dict[str, list]:
        """Raw rows (ciphertext included) of every table these routes write."""
        tables = [
            "commitment_rules", "planned_items", "account_settings",
            "repayment_schedule_items", "accounts", "audit_entries", "write_idempotency",
        ]
        return {
            t: sorted(map(tuple, self.db.execute(text(f"SELECT * FROM {t}")).fetchall()), key=str)
            for t in tables
        }


# Each case: (World, foreign account id) -> response. The body also changes a
# non-account field, so a partial write would show in the snapshot.
Case = Callable[[World, str], object]

CASES: dict[tuple[str, str, str], Case] = {
    ("POST", f"{API}/analytics/commitments", "account_id"): lambda w, acc: w.client.post(
        f"{API}/analytics/commitments",
        json={"direction": "expense", "label": "Netflix", "amount": "10",
              "next_date": "2026-11-05", "account_id": acc},
    ),
    ("PATCH", f"{API}/analytics/commitments/{{commitment_id}}", "account_id"): lambda w, acc: w.client.patch(
        f"{API}/analytics/commitments/{w.commitment_id}",
        json={"label": "Renamed", "amount": "99", "account_id": acc},
    ),
    ("PATCH", f"{API}/analytics/commitments/{{commitment_id}}", "card_account_id"): lambda w, acc: w.client.patch(
        f"{API}/analytics/commitments/{w.commitment_id}",
        json={"label": "Renamed", "amount": "99", "card_account_id": acc},
    ),
    ("POST", f"{API}/analytics/planned-items", "account_id"): lambda w, acc: w.client.post(
        f"{API}/analytics/planned-items",
        json={"name": "Holiday", "kind": "one_off", "start_date": "2026-12-01",
              "amount": "500", "account_id": acc},
    ),
    ("PATCH", f"{API}/analytics/accounts/{{account_id}}/settings", "account_id"): lambda w, acc: w.client.patch(
        f"{API}/analytics/accounts/{acc}/settings", json={"role": "excluded"},
    ),
    ("PATCH", f"{API}/analytics/accounts/{{account_id}}/settings", "pay_from_account_id"): lambda w, acc: w.client.patch(
        f"{API}/analytics/accounts/{w.a_card_id}/settings",
        json={"repayment_strategy": "fixed", "pay_from_account_id": acc},
    ),
    ("POST", f"{API}/analytics/accounts/{{account_id}}/repayments", "account_id"): lambda w, acc: w.client.post(
        f"{API}/analytics/accounts/{acc}/repayments",
        json={"due_date": "2026-11-20", "amount": "100"},
    ),
    ("DELETE", f"{API}/analytics/accounts/{{account_id}}/repayments/{{item_id}}", "account_id"): lambda w, acc: w.client.delete(
        f"{API}/analytics/accounts/{acc}/repayments/{uuid.uuid4()}",
    ),
    ("POST", f"{API}/planning/planned-events", "account_id"): lambda w, acc: w.client.post(
        f"{API}/planning/planned-events",
        json={"name": "Holiday", "amount": "500.00", "date": date.today().isoformat(), "direction": "expense",
              "account_id": acc, "dry_run": False, "idempotency_key": "ownership-case-1"},
    ),
}


def test_every_write_route_taking_an_account_id_has_an_ownership_case():
    found = account_id_inputs(app.routes)
    # Precondition: the walk sees the routes sec listed, so an empty or broken
    # walk can't pass by finding nothing.
    assert ("PATCH", f"{API}/analytics/accounts/{{account_id}}/settings", "pay_from_account_id") in found
    assert ("POST", f"{API}/analytics/planned-items", "account_id") in found
    unchecked = found - CASES.keys()
    assert not unchecked, f"write routes with an account id but no ownership case: {unchecked}"
    stale = CASES.keys() - found
    assert not stale, f"ownership cases for routes that no longer exist: {stale}"


def test_enumeration_self_test_flags_an_unchecked_nested_field():
    class Inner(BaseModel):
        pay_from_account_id: uuid.UUID | None = None

    class Body(BaseModel):
        name: str
        nested: list[Inner] = []

    dummy = FastAPI()

    @dummy.post("/dummy/{source_account_id}")
    def _dummy(source_account_id: str, body: Body) -> dict:  # pragma: no cover
        return {}

    @dummy.get("/read-only/{account_id}")
    def _read(account_id: str) -> dict:  # pragma: no cover
        return {}

    assert account_id_inputs(dummy.routes) == {
        ("POST", "/dummy/{source_account_id}", "source_account_id"),
        ("POST", "/dummy/{source_account_id}", "nested.pay_from_account_id"),
    }


# --- behaviour -------------------------------------------------------------


@pytest.mark.parametrize("key", sorted(CASES), ids=lambda k: f"{k[0]} {k[1]} {k[2]}")
@pytest.mark.parametrize("whose", ["other_user", "unknown"])
def test_foreign_or_unknown_account_id_is_404_and_writes_nothing(client, db_session, key, whose):
    world = World(client, db_session)
    target = str(world.b_account_id) if whose == "other_user" else str(uuid.uuid4())
    before = world.snapshot()

    res = CASES[key](world, target)

    assert res.status_code == 404, res.text
    db_session.expire_all()
    assert world.snapshot() == before


def test_malformed_account_id_in_path_is_rejected_before_any_write(client, db_session):
    world = World(client, db_session)
    before = world.snapshot()
    res = client.patch(f"{API}/analytics/accounts/not-a-uuid/settings", json={"role": "excluded"})
    assert res.status_code == 422
    assert world.snapshot() == before


def test_own_account_ids_are_still_accepted(client, db_session):
    world = World(client, db_session)
    own = str(world.a_account_id)

    res = client.post(
        f"{API}/analytics/planned-items",
        json={"name": "Holiday", "kind": "one_off", "start_date": "2026-12-01",
              "amount": "500", "account_id": own},
    )
    assert res.status_code == 201, res.text
    res = client.patch(
        f"{API}/analytics/commitments/{world.commitment_id}", json={"account_id": own}
    )
    assert res.status_code == 200, res.text
    res = client.patch(
        f"{API}/analytics/accounts/{world.a_card_id}/settings",
        json={"pay_from_account_id": own},
    )
    assert res.status_code == 200, res.text
    # Clearing an account link (null) is not an ownership question.
    res = client.patch(
        f"{API}/analytics/commitments/{world.commitment_id}", json={"account_id": None}
    )
    assert res.status_code == 200, res.text
