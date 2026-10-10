"""Claude can update or dismiss a commitment over MCP (T-08-9).

`POST /planning/commitments/{id}/update` and `.../dismiss` take
`PlanningWriter` (finance:planning.write, per-user limits) and go through
`run_write`: dry_run by default, idempotency, encrypted audit, undo. Only
allow-listed fields can change, every value is bounded, and an edited
commitment is never re-keyed or re-added by `sync_suggestions`.
"""
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.core import user_crypto
from app.models import AuditEntry, CommitmentRule, Transaction, User
from app.services import analytics_service as svc
from tests.integration.test_oauth import READ, _bearer, _connect, _web_login
from tests.integration.test_transactions_endpoint import _account, _dek_from_token

PLANNING = "finance:planning.write"
API = "/api/v1"


class World:
    """A user with a web session and an MCP token holding the planning scope."""

    def __init__(self, client, db, scopes=(READ, PLANNING), email="cw@example.com"):
        self.client, self.db = client, db
        self.web, _, tokens = _connect(client, scopes=scopes, email=email)
        self.mcp = tokens["access_token"]
        self.dek = _dek_from_token(self.web)
        self.user = db.query(User).filter(User.email == email).one()

    def as_user(self):
        return _Dek(self.dek)

    def commitment(self, label="Netflix", amount="10.99", status="confirmed", source="manual",
                   match_key=None, next_date=None, direction="expense") -> uuid.UUID:
        with self.as_user():
            rule = CommitmentRule(
                user_id=self.user.id, direction=direction, label=label, amount=Decimal(amount),
                cadence="monthly", next_date=next_date or svc._today() + timedelta(days=5),
                source=source, status=status, match_key=match_key,
            )
            self.db.add(rule)
            self.db.commit()
            return rule.id

    def rule(self, rule_id) -> CommitmentRule:
        self.db.expire_all()
        with self.as_user():
            rule = self.db.get(CommitmentRule, rule_id)
            # Touch the encrypted columns while the key is set.
            _ = (rule.label, rule.amount, rule.match_key)
            return rule

    def update(self, rule_id, token=None, **body):
        body.setdefault("idempotency_key", f"k-{uuid.uuid4().hex[:12]}")
        return self.client.post(
            f"{API}/planning/commitments/{rule_id}/update", json=body, headers=_bearer(token or self.mcp)
        )

    def dismiss(self, rule_id, token=None, **body):
        body.setdefault("idempotency_key", f"k-{uuid.uuid4().hex[:12]}")
        return self.client.post(
            f"{API}/planning/commitments/{rule_id}/dismiss", json=body, headers=_bearer(token or self.mcp)
        )

    def audit_count(self) -> int:
        return self.db.query(AuditEntry).count()


class _Dek:
    def __init__(self, dek):
        self.dek = dek

    def __enter__(self):
        self.token = user_crypto.current_dek.set(self.dek)

    def __exit__(self, *exc):
        user_crypto.current_dek.reset(self.token)


@pytest.fixture
def world(client, db_session):
    return World(client, db_session)


# --- the write framework ---------------------------------------------------

def test_update_previews_by_default_and_writes_nothing(world):
    rid = world.commitment()
    r = world.update(rid, amount="12.99")
    assert r.status_code == 200, r.text
    assert r.json()["dry_run"] is True
    assert r.json()["changes"] == [{"field": "amount", "before": "10.99", "after": "12.99"}]
    assert world.rule(rid).amount == Decimal("10.99")
    assert world.audit_count() == 0


def test_update_applies_and_is_audited_with_the_grant(world):
    rid = world.commitment()
    r = world.update(rid, amount="12.99", dry_run=False)
    assert r.status_code == 200, r.text
    assert world.rule(rid).amount == Decimal("12.99")
    tool, kind, target, grant = world.db.query(
        AuditEntry.tool, AuditEntry.target_kind, AuditEntry.target_id, AuditEntry.grant_id
    ).one()
    assert (tool, kind, target) == ("update_commitment", "commitment", rid)
    assert grant is not None


def test_dismiss_marks_it_dismissed_and_undo_brings_it_back(world):
    rid = world.commitment()
    r = world.dismiss(rid, dry_run=False)
    assert r.status_code == 200, r.text
    assert world.rule(rid).status == "dismissed"
    undo = world.client.post(f"{API}/audit/{r.json()['audit_id']}/undo", headers=_bearer(world.web))
    assert undo.status_code == 200, undo.text
    assert world.rule(rid).status == "confirmed"


def test_a_read_only_token_cannot_update_or_dismiss(client, db_session):
    w = World(client, db_session, scopes=(READ,), email="ro@example.com")
    rid = w.commitment()
    assert w.update(rid, amount="1", dry_run=False).status_code == 403
    assert w.dismiss(rid, dry_run=False).status_code == 403
    assert w.rule(rid).status == "confirmed"
    assert w.audit_count() == 0


def test_another_users_commitment_is_404_and_nothing_is_audited(client, db_session):
    victim = World(client, db_session, email="victim@example.com")
    rid = victim.commitment()
    attacker = World(client, db_session, email="attacker@example.com")
    assert attacker.update(rid, amount="1", dry_run=False).status_code == 404
    assert attacker.dismiss(rid, dry_run=False).status_code == 404
    assert victim.rule(rid).amount == Decimal("10.99")
    assert victim.rule(rid).status == "confirmed"
    assert attacker.audit_count() == 0


# --- bounds and allow-list ------------------------------------------------

@pytest.mark.parametrize("body", [
    {"amount": "0"},
    {"amount": "-5"},
    {"amount": "1000000.01"},
    {"amount": "1.234"},
    {"amount": 12.5},  # a JSON float
    {"label": ""},
    {"label": "x" * 101},
    {"label": "Rent‮"},
    {"label": "Rent\n"},
    {"next_date": (date.today() - timedelta(days=400)).isoformat()},
    {"next_date": (date.today() + timedelta(days=5 * 366 + 2)).isoformat()},
    {"status": "suggested"},
    {"status": "dismissed"},
    {"cadence": "yearly"},
    {"cadence": "every_n_months"},  # needs interval_months
    {"cadence": "custom_days"},  # needs interval_days
    {"cadence": "every_n_months", "interval_months": 0},
    {"direction": "income"},
    {"match_key": "x"},
    {"match_merchant": "x"},
    {"source": "manual"},
    {"user_id": str(uuid.uuid4())},
    {"is_payday": True},
    {},  # nothing to change
])
def test_out_of_bounds_or_disallowed_input_is_422_and_writes_nothing(world, body):
    rid = world.commitment()
    r = world.update(rid, dry_run=False, **body)
    assert r.status_code == 422, r.text
    rule = world.rule(rid)
    assert (rule.amount, rule.label, rule.status, rule.direction) == (Decimal("10.99"), "Netflix", "confirmed", "expense")
    assert world.audit_count() == 0


def test_dismiss_takes_no_fields_but_the_flags(world):
    rid = world.commitment()
    assert world.dismiss(rid, dry_run=False, status="confirmed").status_code == 422


def test_cadence_with_its_interval_is_accepted(world):
    rid = world.commitment()
    r = world.update(rid, cadence="every_n_months", interval_months=3, dry_run=False)
    assert r.status_code == 200, r.text
    rule = world.rule(rid)
    assert (rule.cadence, rule.interval_months) == ("every_n_months", 3)


# --- card link (T-08-8) ---------------------------------------------------

def test_setting_the_card_link_is_the_users_link(world):
    with world.as_user():
        card_id = _account(world.db, world.user.id, atype="CREDIT_CARD", name="Amex").id
    rid = world.commitment(label="Card bill")
    r = world.update(rid, card_account_id=str(card_id), dry_run=False)
    assert r.status_code == 200, r.text
    rule = world.rule(rid)
    assert (rule.card_account_id, rule.card_link_source) == (card_id, "user")


def test_clearing_the_card_link_is_an_explicit_no_card(world):
    rid = world.commitment(label="AMEX")
    r = world.update(rid, card_account_id=None, dry_run=False)
    assert r.status_code == 200, r.text
    rule = world.rule(rid)
    assert (rule.card_account_id, rule.card_link_source) == (None, "user")


# --- sync never undoes an edit ---------------------------------------------

def _monthly_debits(world, merchant, amount, n=4):
    with world.as_user():
        acc = _account(world.db, world.user.id, name="Current")
        for i in range(n):
            d = svc._today() - timedelta(days=30 * (i + 1))
            world.db.add(Transaction(
                account_id=acc.id, external_id=f"tx-{uuid.uuid4()}", transaction_type="debit",
                amount=Decimal(amount), currency="GBP", description=merchant, merchant_name=merchant,
                transaction_date=datetime.combine(d, datetime.min.time(), tzinfo=timezone.utc),
            ))
        world.db.commit()


def _sync(world):
    with world.as_user():
        user = world.db.get(User, world.user.id)
        svc.sync_suggestions(world.db, user)


def _rules(world):
    world.db.expire_all()
    with world.as_user():
        return [(r.label, r.status) for r in world.db.query(CommitmentRule).filter(
            CommitmentRule.user_id == world.user.id)]


def test_a_relabelled_detected_commitment_keeps_its_key_and_is_not_re_suggested(world):
    _monthly_debits(world, "NETFLIX.COM", "10.99")
    _sync(world)
    detected = [r for r in _rules(world) if r[1] == "suggested"]
    assert len(detected) == 1  # precondition: detection found it
    with world.as_user():
        rule = world.db.query(CommitmentRule).filter(CommitmentRule.user_id == world.user.id).one()
        rid, key = rule.id, rule.match_key

    assert world.update(rid, label="Streaming", status="confirmed", dry_run=False).status_code == 200
    _sync(world)

    rule = world.rule(rid)
    assert rule.match_key == key  # not re-keyed from the new label
    assert _rules(world) == [("Streaming", "confirmed")]  # the merchant isn't suggested again
    with world.as_user():
        user = world.db.get(User, world.user.id)
        assert key in svc.commitment_match_keys(world.db, user)  # its payments still match it


def test_a_dismissed_commitment_is_not_re_added_by_sync(world):
    _monthly_debits(world, "GYM CO", "30.00")
    _sync(world)
    with world.as_user():
        rid = world.db.query(CommitmentRule).filter(CommitmentRule.user_id == world.user.id).one().id
    assert world.dismiss(rid, dry_run=False).status_code == 200
    _sync(world)
    assert _rules(world) == [("GYM CO", "dismissed")]


def test_sync_leaves_an_edited_amount_and_future_date_alone(world):
    rid = world.commitment()
    new_date = (svc._today() + timedelta(days=20)).isoformat()
    assert world.update(rid, amount="15.00", next_date=new_date, dry_run=False).status_code == 200
    _sync(world)
    rule = world.rule(rid)
    assert (rule.amount, rule.next_date.isoformat()) == (Decimal("15.00"), new_date)


# --- merging duplicates, and rent ------------------------------------------

def _committed(world):
    r = world.client.get(f"{API}/analytics/summary", headers=_bearer(world.web))
    assert r.status_code == 200, r.text
    return Decimal(r.json()["committed_before_payday"]), Decimal(r.json()["safe_to_spend"])


def test_a_merge_is_two_undoable_rows_sharing_a_batch(world):
    keep = world.commitment(label="Netflix", amount="10.99")
    dup = world.commitment(label="NETFLIX.COM", amount="10.99")
    batch = str(uuid.uuid4())
    assert world.dismiss(dup, batch_id=batch, dry_run=False).status_code == 200
    assert world.update(keep, amount="12.99", batch_id=batch, dry_run=False).status_code == 200

    entries = world.db.query(AuditEntry.id, AuditEntry.batch_id).order_by(AuditEntry.created_at).all()
    assert [str(batch_id) for _, batch_id in entries] == [batch, batch]
    assert _committed(world)[0] == Decimal("12.99")

    dismiss_id = entries[0][0]
    undo = world.client.post(f"{API}/audit/{dismiss_id}/undo", headers=_bearer(world.web))
    assert undo.status_code == 200, undo.text
    # Undoing only the dismiss brings the duplicate back: both count (overstates, safe).
    assert _committed(world)[0] == Decimal("12.99") + Decimal("10.99")


def test_confirming_suggested_rent_lowers_safe_to_spend_by_its_amount_once(world):
    with world.as_user():
        _account(world.db, world.user.id, name="Main", balance="3000")
    rid = world.commitment(label="RENT TRANSFER", amount="950.00", status="suggested", source="detected")
    before_committed, before_safe = _committed(world)
    r = world.update(rid, status="confirmed", dry_run=False)
    assert r.status_code == 200, r.text
    after_committed, after_safe = _committed(world)
    assert after_committed - before_committed == Decimal("950.00")
    assert before_safe - after_safe == Decimal("950.00")


# --- source=manual is server-side only (sec's conditions) -------------------

def test_an_amount_or_date_edit_leaves_a_detected_commitment_detected(world):
    rid = world.commitment(source="detected", match_key="expense:netflix")
    new_date = (svc._today() + timedelta(days=9)).isoformat()
    assert world.update(rid, amount="12.99", next_date=new_date, dry_run=False).status_code == 200
    assert world.rule(rid).source == "detected"


def _undo(world, audit_id):
    return world.client.post(f"{API}/audit/{audit_id}/undo", headers=_bearer(world.web))


def test_undo_restores_label_and_source_and_the_next_sync_re_keys(world):
    _monthly_debits(world, "NETFLIX.COM", "10.99")
    _sync(world)
    with world.as_user():
        rule = world.db.query(CommitmentRule).filter(CommitmentRule.user_id == world.user.id).one()
        rid, key, label = rule.id, rule.match_key, rule.label
    r = world.update(rid, label="Streaming", dry_run=False)
    assert world.rule(rid).source == "manual"

    assert _undo(world, r.json()["audit_id"]).status_code == 200
    rule = world.rule(rid)
    assert (rule.label, rule.source) == (label, "detected")
    _sync(world)
    assert world.rule(rid).match_key == key  # re-derived from the original label
    assert len(_rules(world)) == 1


def test_undo_is_refused_when_the_label_was_changed_in_the_app_since(world):
    rid = world.commitment(source="detected", match_key="expense:netflix")
    r = world.update(rid, label="Streaming", dry_run=False)
    app_edit = world.client.patch(
        f"{API}/analytics/commitments/{rid}", json={"label": "My streaming"}, headers=_bearer(world.web)
    )
    assert app_edit.status_code == 200, app_edit.text
    assert _undo(world, r.json()["audit_id"]).status_code == 409
    assert world.rule(rid).label == "My streaming"
