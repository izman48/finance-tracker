"""The write framework every Claude planning write goes through (T-08-3b).

`run_write` is what the dedicated MCP write routes (T-08-6, T-08-9) call. It:
  - computes the diff by running the real change and rolling it back
    (dry_run writes no row, audit row or idempotency record);
  - stores an append-only audit row per applied write, DEK-encrypted, with
    the grant and client taken from the verified Caller;
  - makes a repeated idempotency key return the first result (same key and
    a different payload is refused), safely across two DB sessions;
  - loads update targets by id AND user_id.
"""
import threading
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.core import user_crypto
from app.core.database import Base
from app.core.oauth_tokens import Caller
from app.models import AuditEntry, CommitmentRule, PlannedItem, User, WriteIdempotency
from app.schemas import PlanningWriteRequest
from app.services.planning_writes import DisallowedChange, WriteRequest, run_write

KEY = "key-0001"


def _user(db, email="w@example.com") -> User:
    user = User(email=email, hashed_password="x")
    db.add(user)
    db.commit()
    return user


def _add_planned(user_id, name="Holiday deposit", amount="250.00", on=date(2026, 12, 1), delay=0.0):
    def apply(db, _target):
        if delay:
            time.sleep(delay)
        item = PlannedItem(
            user_id=user_id, name=name, direction="expense", kind="one_off",
            start_date=on, amount=Decimal(amount),
        )
        db.add(item)
        return item

    req = WriteRequest(tool="add_planned_event", target_kind="planned_event", target_id=None, apply=apply)
    return req, {"name": name, "amount": amount, "date": on.isoformat()}


def _set_amount(commitment_id, amount):
    def apply(db, rule):
        rule.amount = Decimal(amount)
        return rule

    req = WriteRequest(tool="update_commitment", target_kind="commitment", target_id=commitment_id, apply=apply)
    return req, {"amount": amount}


def _commitment(db, user, label="Gym", amount="30.00") -> uuid.UUID:
    rule = CommitmentRule(
        user_id=user.id, direction="expense", label=label, amount=Decimal(amount),
        cadence="monthly", next_date=date(2026, 11, 1), source="manual", status="confirmed",
    )
    db.add(rule)
    db.commit()
    return rule.id


def _counts(db) -> tuple[int, int, int]:
    return tuple(
        db.execute(text(f"SELECT count(*) FROM {t}")).scalar()
        for t in ("planned_items", "audit_entries", "write_idempotency")
    )


def _caller(user, grant_id=None, client_id=None) -> Caller:
    return Caller(user=user, grant_id=grant_id, client_id=client_id)


class _Body(PlanningWriteRequest):
    """A write route's validated body: the flags plus the tool's own fields."""

    fields: dict = {}


def _write(db, caller, req_and_fields, dry_run, key=KEY):
    req, fields = req_and_fields
    return run_write(db, caller, req, _Body(dry_run=dry_run, idempotency_key=key, fields=fields))


# --- dry run --------------------------------------------------------------------


def test_dry_run_returns_the_diff_and_writes_nothing(db_session):
    user = _user(db_session)
    before = _counts(db_session)

    result = _write(db_session, _caller(user), _add_planned(user.id), True)

    assert result["dry_run"] is True and result["audit_id"] is None
    assert {"field": "name", "before": None, "after": "Holiday deposit"} in result["changes"]
    assert {"field": "amount", "before": None, "after": "250.00"} in result["changes"]
    assert _counts(db_session) == before


def test_applying_after_a_dry_run_gives_the_previewed_diff(db_session):
    user = _user(db_session)
    preview = _write(db_session, _caller(user), _add_planned(user.id), True)
    applied = _write(db_session, _caller(user), _add_planned(user.id), False)
    assert applied["changes"] == preview["changes"]
    assert applied["target_label"] == preview["target_label"] == "Holiday deposit"
    assert applied["dry_run"] is False and applied["audit_id"]


def test_dry_run_of_an_update_leaves_the_target_unchanged(db_session):
    user = _user(db_session)
    cid = _commitment(db_session, user)
    result = _write(db_session, _caller(user), _set_amount(cid, "45.00"), True)
    assert result["changes"] == [{"field": "amount", "before": "30.00", "after": "45.00"}]
    db_session.expire_all()
    assert db_session.get(CommitmentRule, cid).amount == Decimal("30.00")


# --- audit ------------------------------------------------------------------------


def test_an_applied_write_stores_one_audit_row_from_the_callers_claims(db_session):
    user = _user(db_session)
    grant = uuid.uuid4()
    result = _write(db_session, _caller(user, grant_id=grant, client_id="client-abc"), _add_planned(user.id), False)

    entry = db_session.get(AuditEntry, uuid.UUID(result["audit_id"]))
    assert entry.user_id == user.id and entry.kind == "write"
    assert entry.tool == "add_planned_event" and entry.target_kind == "planned_event"
    assert str(entry.target_id) == result["target_id"]
    assert entry.grant_id == grant and entry.client_id == "client-abc"
    assert entry.target_label == "Holiday deposit"
    assert entry.undone_at is None


def test_the_raw_audit_row_holds_no_plaintext_label_or_amount(db_session):
    user = _user(db_session)
    _write(db_session, _caller(user), _add_planned(user.id, name="Secret Clinic", amount="987.65"), False)
    raw = " ".join(str(v) for row in db_session.execute(text("SELECT * FROM audit_entries")) for v in row)
    assert "Secret Clinic" not in raw and "987.65" not in raw
    idem = " ".join(str(v) for row in db_session.execute(text("SELECT * FROM write_idempotency")) for v in row)
    assert "Secret Clinic" not in idem and "987.65" not in idem


def test_an_update_audits_only_the_fields_that_changed(db_session):
    user = _user(db_session)
    cid = _commitment(db_session, user)
    result = _write(db_session, _caller(user), _set_amount(cid, "45.00"), False)
    assert result["changes"] == [{"field": "amount", "before": "30.00", "after": "45.00"}]
    assert result["target_label"] == "Gym"


def test_another_users_target_is_404_and_nothing_is_audited(db_session):
    owner = _user(db_session, "owner@example.com")
    cid = _commitment(db_session, owner)
    intruder = _user(db_session, "intruder@example.com")
    before = _counts(db_session)
    with pytest.raises(HTTPException) as exc:
        _write(db_session, _caller(intruder), _set_amount(cid, "1.00"), False)
    assert exc.value.status_code == 404
    assert _counts(db_session) == before
    db_session.expire_all()
    assert db_session.get(CommitmentRule, cid).amount == Decimal("30.00")


# --- idempotency ------------------------------------------------------------------


def test_a_repeated_key_returns_the_first_result_without_writing_again(db_session):
    user = _user(db_session)
    first = _write(db_session, _caller(user), _add_planned(user.id), False)
    counts = _counts(db_session)
    again = _write(db_session, _caller(user), _add_planned(user.id), False)
    assert again == first
    assert _counts(db_session) == counts


def test_a_repeated_key_with_a_different_payload_is_refused(db_session):
    user = _user(db_session)
    _write(db_session, _caller(user), _add_planned(user.id), False)
    counts = _counts(db_session)
    with pytest.raises(HTTPException) as exc:
        _write(db_session, _caller(user), _add_planned(user.id, amount="999.00"), False)
    assert exc.value.status_code == 409
    assert _counts(db_session) == counts


def test_keys_are_per_user(db_session):
    a, b = _user(db_session, "a@example.com"), _user(db_session, "b@example.com")
    ra = _write(db_session, _caller(a), _add_planned(a.id), False)
    rb = _write(db_session, _caller(b), _add_planned(b.id), False)
    assert ra["audit_id"] != rb["audit_id"]


def test_a_key_older_than_24_hours_has_expired(db_session):
    user = _user(db_session)
    first = _write(db_session, _caller(user), _add_planned(user.id), False)
    db_session.execute(
        text("UPDATE write_idempotency SET created_at = :t"),
        {"t": datetime.now(timezone.utc) - timedelta(hours=25)},
    )
    db_session.commit()
    second = _write(db_session, _caller(user), _add_planned(user.id, amount="1.00"), False)
    assert second["audit_id"] != first["audit_id"]
    assert db_session.execute(text("SELECT count(*) FROM write_idempotency")).scalar() == 1


def test_the_stored_response_holds_only_ids(db_session):
    user = _user(db_session)
    result = _write(db_session, _caller(user), _add_planned(user.id), False)
    record = db_session.query(WriteIdempotency).one()
    assert record.audit_id == uuid.UUID(result["audit_id"])
    assert set(WriteIdempotency.__table__.columns.keys()) == {
        "id", "user_id", "key", "request_hash", "audit_id", "created_at",
    }


def test_two_sessions_racing_on_one_key_write_once(tmp_path):
    """Two uvicorn workers = two DB sessions. The unique (user_id, key) row is
    claimed before the change, so the loser waits, then replays."""
    engine = create_engine(
        f"sqlite:///{tmp_path / 'race.db'}", connect_args={"check_same_thread": False, "timeout": 10},
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False)
    dek = user_crypto.generate_dek()
    with Session() as s:
        token = user_crypto.current_dek.set(dek)
        user = _user(s)
        user_id = user.id
        user_crypto.current_dek.reset(token)

    results: list = []
    errors: list = []

    def worker(delay):
        token = user_crypto.current_dek.set(dek)
        try:
            with Session() as s:
                me = s.get(User, user_id)
                results.append(_write(s, _caller(me), _add_planned(user_id, delay=delay), False))
        except Exception as exc:  # pragma: no cover - surfaced below
            errors.append(exc)
        finally:
            user_crypto.current_dek.reset(token)

    slow = threading.Thread(target=worker, args=(0.5,))
    fast = threading.Thread(target=worker, args=(0,))
    slow.start()
    time.sleep(0.1)
    fast.start()
    slow.join()
    fast.join()

    assert not errors, errors
    assert len(results) == 2 and results[0] == results[1]
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM planned_items")).scalar() == 1
        assert c.execute(text("SELECT count(*) FROM audit_entries")).scalar() == 1
    engine.dispose()


# --- request schema -------------------------------------------------------------


class _NamedBody(PlanningWriteRequest):
    name: str


def test_requests_default_to_dry_run():
    assert _NamedBody(name="x", idempotency_key=KEY).dry_run is True


@pytest.mark.parametrize("key", ["short", "x" * 65, "has space1", "semi;colon", "ünïcode1"])
def test_idempotency_key_format_is_enforced(key):
    with pytest.raises(ValidationError):
        _NamedBody(name="x", idempotency_key=key)


@pytest.mark.parametrize("extra", ["user_id", "source", "match_key", "client_id", "grant_id"])
def test_unknown_fields_are_refused(extra):
    with pytest.raises(ValidationError):
        _NamedBody(name="x", idempotency_key=KEY, **{extra: "x"})


def test_dry_run_must_be_a_real_boolean():
    with pytest.raises(ValidationError):
        _NamedBody(name="x", idempotency_key=KEY, dry_run="false")


# --- the existing web write routes stay web-only ---------------------------------

WEB_ONLY_WRITES = [
    ("patch", f"/api/v1/analytics/commitments/{uuid.uuid4()}", {"amount": "1"}),
    ("post", "/api/v1/analytics/commitments", {"direction": "expense", "label": "x", "amount": "1", "next_date": "2026-11-01"}),
    ("post", "/api/v1/analytics/planned-items", {"name": "x", "kind": "one_off", "start_date": "2026-11-01", "amount": "1"}),
    ("delete", f"/api/v1/analytics/planned-items/{uuid.uuid4()}", None),
]


@pytest.mark.parametrize("method,path,body", WEB_ONLY_WRITES)
def test_an_mcp_token_with_the_planning_scope_cannot_use_the_web_write_routes(client, method, path, body):
    """Claude's writes go only through the dedicated routes (audit, dry_run,
    idempotency, strict schemas); the app's own routes refuse its token."""
    from tests.integration.test_oauth import READ, _bearer, _connect

    _, _, tokens = _connect(client, scopes=(READ, "finance:planning.write"))
    kwargs = {"headers": _bearer(tokens["access_token"])}
    if body is not None:
        kwargs["json"] = body
    assert getattr(client, method)(path, **kwargs).status_code == 401


# --- every change is audited ----------------------------------------------------


@pytest.mark.parametrize("column,value", [
    ("match_key", "expense:something-else"),
    ("is_payday", True),
    ("direction", "income"),
    ("source", "detected"),
])
@pytest.mark.parametrize("dry_run", [True, False])
def test_an_apply_that_touches_a_column_outside_the_allow_list_is_refused(db_session, column, value, dry_run):
    """The audit trail is the control against injected edits, so the
    framework refuses a change it can't show, whatever the tool's apply does."""
    user = _user(db_session)
    cid = _commitment(db_session, user)
    before = db_session.execute(text("SELECT * FROM commitment_rules")).fetchall()
    counts = _counts(db_session)

    def bad_apply(db, rule):
        rule.label = "Gym renamed"  # allow-listed
        setattr(rule, column, value)  # not allow-listed
        return rule

    req = WriteRequest(tool="update_commitment", target_kind="commitment", target_id=cid, apply=bad_apply)
    with pytest.raises(DisallowedChange) as exc:
        _write(db_session, _caller(user), (req, {"label": "Gym renamed"}), dry_run)
    assert column in str(exc.value)
    db_session.expire_all()
    assert db_session.execute(text("SELECT * FROM commitment_rules")).fetchall() == before
    assert _counts(db_session) == counts


# --- one source for dry_run -----------------------------------------------------


def test_dry_run_comes_only_from_the_validated_body(client, db_session):
    """A route passes its validated body to run_write; a query parameter (or
    anything else) can't turn a preview into a write."""
    from fastapi import APIRouter

    from app.core.planning_write import PlanningWriter
    from app.main import app
    from tests.integration.test_oauth import READ, _bearer, _connect

    class ProbeBody(PlanningWriteRequest):
        name: str

    router = APIRouter()

    @router.post("/api/v1/__test__/add-planned")
    def probe(body: ProbeBody, caller: PlanningWriter) -> dict:
        req, _ = _add_planned(caller.user.id, name=body.name)
        return run_write(db_session, caller, req, body)

    saved = list(app.router.routes)
    app.include_router(router)
    try:
        _, _, tokens = _connect(client, scopes=(READ, "finance:planning.write"))
        counts = _counts(db_session)
        res = client.post(
            "/api/v1/__test__/add-planned?dry_run=false",
            json={"idempotency_key": KEY, "name": "Holiday"},
            headers=_bearer(tokens["access_token"]),
        )
    finally:
        app.router.routes[:] = saved
    assert res.status_code == 200, res.text
    assert res.json()["dry_run"] is True and res.json()["audit_id"] is None
    assert _counts(db_session) == counts


# --- a write that changes nothing --------------------------------------------------


def _set_status(commitment_id, status, tool):
    def apply(db, rule):
        rule.status = status
        return rule

    req = WriteRequest(tool=tool, target_kind="commitment", target_id=commitment_id, apply=apply)
    return req, {"status": status}


@pytest.mark.parametrize("status,tool", [
    ("dismissed", "dismiss_commitment"),   # dismissing an already-dismissed commitment
    ("confirmed", "update_commitment"),    # re-confirming a confirmed one
])
@pytest.mark.parametrize("dry_run", [True, False])
def test_a_write_that_changes_nothing_records_nothing(db_session, status, tool, dry_run):
    """No audit row, no idempotency record and nothing to undo; the result is
    not an error, so the assistant doesn't retry."""
    user = _user(db_session)
    cid = _commitment(db_session, user)
    db_session.execute(text("UPDATE commitment_rules SET status = :s"), {"s": status})
    db_session.commit()
    counts = _counts(db_session)

    result = _write(db_session, _caller(user), _set_status(cid, status, tool), dry_run)

    assert result["unchanged"] is True
    assert result["changes"] == [] and result["audit_id"] is None
    assert result["dry_run"] is dry_run
    assert result["target_id"] == str(cid) and result["target_label"] == "Gym"
    assert _counts(db_session) == counts


def test_a_real_change_is_not_marked_unchanged(db_session):
    user = _user(db_session)
    cid = _commitment(db_session, user)
    assert _write(db_session, _caller(user), _set_amount(cid, "45.00"), False)["unchanged"] is False
    assert _write(db_session, _caller(user), _add_planned(user.id), False, key="key-0002")["unchanged"] is False
