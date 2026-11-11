"""Repayment marks: the table, the read service and the audit target
(T-03-3 P1a/P1b; PRD T-03-1 "Model", T-03-2 decisions T2, T6, T10).

A mark says "this much of an incoming payment paid back a spend, or a
category". Its amount and label are encrypted; ids, category, `active` and
`created_via` are plain. Reads clamp marks, oldest first, so a credit or a
spend is never netted past its own amount, whatever the rows say. Undoing
an unmark re-checks that room (T6). Nothing user-visible reads marks yet.
"""
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.core import user_crypto
from app.models import RepaymentMark, Transaction, User
from app.services import repayment_marks
from app.services.key_loss_purge import purge_data_under_lost_key
from app.services.planning_writes import WriteRequest
from tests.integration.test_audit_api import World, _raw_audit_count
from tests.integration.test_transactions_endpoint import _account, _tx

DINNER_DAY = date(2026, 10, 2)
T0 = datetime(2026, 10, 5, 12, tzinfo=timezone.utc)


class Ledger:
    """A user's account with helpers for transactions and marks, written
    under that user's key."""

    def __init__(self, db, user_id, dek):
        self.db, self.user_id, self.dek = db, user_id, dek
        self.n = 0
        self.account = self.as_user(lambda: _account(db, user_id))

    def as_user(self, fn):
        token = user_crypto.current_dek.set(self.dek)
        try:
            return fn()
        finally:
            user_crypto.current_dek.reset(token)

    def spend(self, amount, category="Eating out") -> Transaction:
        return self.as_user(lambda: _tx(self.db, self.account, amount, DINNER_DAY, category=category))

    def credit(self, amount, when=DINNER_DAY + timedelta(days=2)) -> Transaction:
        return self.as_user(lambda: _tx(self.db, self.account, amount, when, ttype="credit", merchant="SAM"))

    def mark(self, credit, amount, spend=None, category=None, active=True, label="Sam, dinner") -> RepaymentMark:
        self.n += 1

        def make():
            row = RepaymentMark(
                user_id=self.user_id, credit_transaction_id=credit.id,
                spend_transaction_id=spend.id if spend else None, category=category,
                amount=Decimal(amount), label=label, active=active, created_via="mcp",
                created_at=T0 + timedelta(minutes=self.n),
            )
            self.db.add(row)
            self.db.commit()
            return row
        return self.as_user(make)

    def active(self):
        return self.as_user(lambda: repayment_marks.active_marks(self.db, self.user_id))

    def mark_id(self, *args, **kwargs):
        mark = self.mark(*args, **kwargs)
        return self.as_user(lambda: mark.id)

    def applied(self):
        """{mark id: amount it nets}, so a test can't pass with the order reversed."""
        return {m.id: m.applied_amount for m in self.active()}

    def remaining(self, *txs):
        return self.as_user(lambda: repayment_marks.remaining(self.db, self.user_id, [t.id for t in txs]))


@pytest.fixture
def ledger(db_session):
    user = User(email="marks@example.com", hashed_password="x")
    db_session.add(user)
    db_session.commit()
    return Ledger(db_session, user.id, user_crypto.current_dek.get())


@pytest.fixture
def fk_on(db_session):
    """Foreign keys enforced, as on Postgres (the cascades rely on them)."""
    db_session.commit()
    db_session.connection().exec_driver_sql("PRAGMA foreign_keys=ON")
    yield
    db_session.rollback()
    db_session.connection().exec_driver_sql("PRAGMA foreign_keys=OFF")


# --- the table -------------------------------------------------------------------


def test_amount_and_label_are_encrypted_and_the_rest_is_plain(ledger, db_session):
    dinner, sam = ledger.spend("200.00"), ledger.credit("60.00")
    mark = ledger.mark(sam, "60.00", spend=dinner, label="Sam £60, Pizza Express")

    raw = db_session.execute(text("SELECT amount, label, active, created_via FROM repayment_marks")).one()
    # Fernet tokens, not the values: a substring check on base64 is flaky.
    assert raw.amount.startswith("gAAAAA") and raw.label.startswith("gAAAAA")
    assert bool(raw.active) is True and raw.created_via == "mcp"
    db_session.expire_all()
    assert ledger.as_user(lambda: (mark.amount, mark.label)) == (Decimal("60.00"), "Sam £60, Pizza Express")


@pytest.mark.parametrize("target", ["neither", "both"])
def test_a_mark_needs_exactly_one_of_spend_or_category(ledger, db_session, target):
    dinner, sam = ledger.spend("200.00"), ledger.credit("60.00")
    with pytest.raises(IntegrityError):
        if target == "neither":
            ledger.mark(sam, "60.00")
        else:
            ledger.mark(sam, "60.00", spend=dinner, category="Eating out")


def test_one_active_mark_per_credit_and_spend(ledger, db_session):
    dinner, sam = ledger.spend("200.00"), ledger.credit("60.00")
    ledger.mark(sam, "30.00", spend=dinner, active=False)  # an unmarked one doesn't count
    ledger.mark(sam, "30.00", spend=dinner)
    with pytest.raises(IntegrityError):
        ledger.mark(sam, "30.00", spend=dinner)


def test_one_active_mark_per_credit_and_category(ledger, db_session):
    sam = ledger.credit("60.00")
    ledger.mark(sam, "30.00", category="Eating out")
    ledger.mark(sam, "30.00", category="Groceries")  # another category is fine
    with pytest.raises(IntegrityError):
        ledger.mark(sam, "10.00", category="Eating out")


@pytest.mark.parametrize("deleted", ["credit", "spend"])
def test_deleting_either_transaction_deletes_its_marks(ledger, db_session, fk_on, deleted):
    dinner, sam = ledger.spend("200.00"), ledger.credit("60.00")
    ledger.mark(sam, "60.00", spend=dinner)
    gone = sam if deleted == "credit" else dinner
    db_session.execute(text("DELETE FROM transactions WHERE id = :id"), {"id": gone.id.hex})
    db_session.commit()
    assert db_session.execute(text("SELECT count(*) FROM repayment_marks")).scalar() == 0


def test_deleting_the_user_deletes_their_marks(ledger, db_session, fk_on):
    ledger.mark(ledger.credit("60.00"), "60.00", category="Eating out")
    db_session.execute(text("DELETE FROM users"))
    db_session.commit()
    assert db_session.execute(text("SELECT count(*) FROM repayment_marks")).scalar() == 0


def test_the_key_loss_purge_deletes_marks_before_their_transactions(ledger, db_session, fk_on):
    ledger.mark(ledger.credit("60.00"), "60.00", spend=ledger.spend("200.00"))
    purge_data_under_lost_key(db_session, ledger.user_id)
    db_session.commit()
    assert db_session.execute(text("SELECT count(*) FROM repayment_marks")).scalar() == 0
    assert db_session.execute(text("SELECT count(*) FROM transactions")).scalar() == 0


# --- reading marks -----------------------------------------------------------------


def test_a_user_with_no_marks_reads_none(ledger):
    ledger.spend("200.00")
    assert ledger.active() == []


def test_active_marks_are_the_users_own_and_active_only(ledger, db_session):
    dinner, sam, jo = ledger.spend("200.00"), ledger.credit("60.00"), ledger.credit("50.00")
    ledger.mark(sam, "60.00", spend=dinner, label="Sam £60, Pizza Express")
    ledger.mark(jo, "50.00", spend=dinner, active=False)
    other = User(email="other@example.com", hashed_password="x")
    db_session.add(other)
    db_session.commit()
    other_ledger = Ledger(db_session, other.id, user_crypto.generate_dek())
    other_ledger.mark(other_ledger.credit("10.00"), "10.00", category="Eating out")

    [mark] = ledger.active()
    assert (mark.credit_id, mark.spend_id, mark.category) == (sam.id, dinner.id, None)
    assert mark.recorded == mark.applied_amount == Decimal("60.00")
    assert mark.created_at is not None
    assert mark.label == "Sam £60, Pizza Express" and mark.created_via == "mcp"
    assert mark.credit_at.date() == sam.transaction_date.date()


def test_marks_on_one_credit_are_clamped_to_the_credit_oldest_first(ledger):
    starter, dinner, sam = ledger.spend("80.00"), ledger.spend("200.00"), ledger.credit("100.00")
    first = ledger.mark_id(sam, "60.00", spend=starter)
    second = ledger.mark_id(sam, "60.00", spend=dinner)  # only £40 of the credit is left

    assert ledger.applied() == {first: Decimal("60.00"), second: Decimal("40.00")}


def test_marks_on_one_spend_are_clamped_to_the_spend_oldest_first(ledger):
    dinner, sam, jo = ledger.spend("60.00"), ledger.credit("40.00"), ledger.credit("40.00")
    first = ledger.mark_id(sam, "40.00", spend=dinner)
    second = ledger.mark_id(jo, "40.00", spend=dinner)  # only £20 of the spend is left

    assert ledger.applied() == {first: Decimal("40.00"), second: Decimal("20.00")}


def test_category_marks_are_capped_by_the_credit_only(ledger):
    sam = ledger.credit("50.00")
    first = ledger.mark_id(sam, "30.00", category="Eating out")
    second = ledger.mark_id(sam, "30.00", category="Groceries")

    assert ledger.applied() == {first: Decimal("30.00"), second: Decimal("20.00")}


def test_extra_marks_preview_as_the_newest_and_are_not_saved(ledger, db_session):
    """T-03-2 T7: a preview nets proposed marks after the saved ones."""
    dinner, sam = ledger.spend("200.00"), ledger.credit("100.00")
    saved = ledger.mark_id(sam, "70.00", category="Eating out")
    dinner_id, sam_id = ledger.as_user(lambda: (dinner.id, sam.id))
    proposed = RepaymentMark(user_id=ledger.user_id, credit_transaction_id=sam_id, spend_transaction_id=dinner_id,
                             amount=Decimal("60.00"), label="Sam, dinner", created_via="mcp")

    marks = ledger.as_user(lambda: repayment_marks.active_marks(db_session, ledger.user_id, extra=[proposed]))

    assert [(m.id, m.spend_id, m.applied_amount) for m in marks] == [
        (saved, None, Decimal("70.00")), (None, dinner_id, Decimal("30.00")),
    ]
    assert db_session.execute(text("SELECT count(*) FROM repayment_marks")).scalar() == 1


def test_remaining_is_what_is_left_unmarked_on_each_transaction(ledger):
    dinner, sam, jo, untouched = ledger.spend("200.00"), ledger.credit("60.00"), ledger.credit("50.00"), ledger.spend("9.99")
    ledger.mark(sam, "60.00", spend=dinner)
    ledger.mark(jo, "20.00", category="Eating out")

    left = ledger.remaining(dinner, sam, jo, untouched)
    assert left == {dinner.id: Decimal("140.00"), sam.id: Decimal("0.00"), jo.id: Decimal("30.00"),
                    untouched.id: Decimal("9.99")}


def test_remaining_never_names_another_users_transaction(ledger, db_session):
    other = User(email="other@example.com", hashed_password="x")
    db_session.add(other)
    db_session.commit()
    theirs = Ledger(db_session, other.id, user_crypto.generate_dek())
    their_spend_id = theirs.as_user(lambda: theirs.spend("200.00").id)
    assert ledger.as_user(lambda: repayment_marks.remaining(db_session, ledger.user_id, [their_spend_id])) == {}


def test_fits_checks_both_caps(ledger):
    dinner, sam, jo = ledger.spend("100.00"), ledger.credit("60.00"), ledger.credit("70.00")
    ledger.mark(sam, "60.00", spend=dinner)
    check = lambda credit, amount, spend=None: ledger.as_user(  # noqa: E731
        lambda: repayment_marks.fits(ledger.db, ledger.user_id, credit.id, spend.id if spend else None,
                                     Decimal(amount)))

    assert check(jo, "40.00", dinner) is True
    assert check(jo, "40.01", dinner) is False  # over the spend's £40 left
    assert check(jo, "70.00") is True           # a category mark: the credit's cap only
    assert check(jo, "70.01") is False
    assert check(sam, "0.01") is False          # the credit is fully marked


# --- the audit target: Claude marks, unmarks and undo ---------------------------------


class Claude(World):
    """A user with an MCP connection who writes marks as Claude would."""

    def __init__(self, client, db):
        super().__init__(client, db)
        self.ledger = Ledger(db, self.user.id, self.dek)

    def add_mark(self, credit, amount, spend=None, category=None) -> dict:
        def apply(db, _):
            mark = RepaymentMark(
                user_id=self.user.id, credit_transaction_id=credit.id,
                spend_transaction_id=spend.id if spend else None, category=category,
                amount=Decimal(amount), label="Sam £60, Pizza Express", created_via="mcp",
            )
            db.add(mark)
            return mark
        return self.write(WriteRequest("mark_paid_back", "repayment_mark", None, apply))

    def unmark(self, mark_id) -> dict:
        def apply(db, mark):
            mark.active = False
            return mark
        return self.write(WriteRequest("unmark_paid_back", "repayment_mark", mark_id, apply))


def test_a_claude_mark_is_audited_with_its_allow_listed_fields(client, db_session):
    c = Claude(client, db_session)
    dinner, sam = c.ledger.spend("200.00"), c.ledger.credit("60.00")
    dinner_id = c.ledger.as_user(lambda: dinner.id)

    result = c.add_mark(sam, "60.00", spend=dinner)

    assert result["target_kind"] == "repayment_mark" and result["target_label"] == "Sam £60, Pizza Express"
    assert {ch["field"]: ch["after"] for ch in result["changes"]} == {
        "amount": "60.00", "spend_transaction_id": str(dinner_id), "active": True,
    }  # a create diffs only the fields it sets
    raw = " ".join(str(v) for row in db_session.execute(text("SELECT * FROM audit_entries")) for v in row)
    assert "Pizza" not in raw and "60.00" not in raw


def test_undo_of_a_mark_soft_deletes_it_and_a_second_undo_is_a_no_op(client, db_session):
    c = Claude(client, db_session)
    added = c.add_mark(c.ledger.credit("60.00"), "60.00", spend=c.ledger.spend("200.00"))
    mark_id = uuid.UUID(added["target_id"])

    first = c.undo(added["audit_id"])
    assert first.status_code == 200, first.text
    assert c.get(RepaymentMark, mark_id).active is False
    assert c.ledger.active() == []

    again = c.undo(added["audit_id"])
    assert again.status_code == 200 and again.json()["undone_at"] == first.json()["undone_at"]
    assert _raw_audit_count(db_session) == 2


def test_an_unmark_soft_deletes_and_its_undo_restores_the_mark(client, db_session):
    c = Claude(client, db_session)
    added = c.add_mark(c.ledger.credit("60.00"), "60.00", spend=c.ledger.spend("200.00"))
    mark_id = uuid.UUID(added["target_id"])

    removed = c.unmark(mark_id)
    assert c.get(RepaymentMark, mark_id).active is False
    assert c.ledger.active() == []

    assert c.undo(removed["audit_id"]).status_code == 200
    assert [m.id for m in c.ledger.active()] == [mark_id]


def test_undo_of_an_unmark_is_refused_when_the_credit_was_marked_again_since(client, db_session):
    c = Claude(client, db_session)
    dinner, drinks, sam = c.ledger.spend("200.00"), c.ledger.spend("80.00"), c.ledger.credit("60.00")
    mark_id = uuid.UUID(c.add_mark(sam, "60.00", spend=dinner)["target_id"])
    removed = c.unmark(mark_id)
    c.add_mark(sam, "60.00", spend=drinks)  # the credit is fully marked again

    res = c.undo(removed["audit_id"])

    assert res.status_code == 409 and "changed since" in res.json()["detail"]
    assert c.get(RepaymentMark, mark_id).active is False


def test_undo_of_an_unmark_is_refused_when_the_spend_was_marked_again_since(client, db_session):
    c = Claude(client, db_session)
    dinner, sam, jo = c.ledger.spend("60.00"), c.ledger.credit("60.00"), c.ledger.credit("60.00")
    mark_id = uuid.UUID(c.add_mark(sam, "60.00", spend=dinner)["target_id"])
    removed = c.unmark(mark_id)
    c.add_mark(jo, "60.00", spend=dinner)  # the spend is fully paid back by Jo now

    assert c.undo(removed["audit_id"]).status_code == 409
    assert c.get(RepaymentMark, mark_id).active is False


def test_undo_takes_the_user_lock_before_the_mark_lock(client, db_session, monkeypatch):
    """Mark writes lock the user row, then the mark. Undo must use the same
    order, or a write and an undo of the same mark can deadlock (eng-b on #272)."""
    from app.services import planning_writes

    c = Claude(client, db_session)
    added = c.add_mark(c.ledger.credit("60.00"), "60.00", spend=c.ledger.spend("200.00"))
    removed = c.unmark(uuid.UUID(added["target_id"]))
    order = []
    real_lock, real_load = planning_writes.lock_user_marks, planning_writes._load_target
    monkeypatch.setattr(planning_writes, "lock_user_marks",
                        lambda *a: (order.append("user"), real_lock(*a))[1])
    monkeypatch.setattr(planning_writes, "_load_target",
                        lambda *a, **k: (order.append("mark"), real_load(*a, **k))[1])

    assert c.undo(removed["audit_id"]).status_code == 200
    assert order[:2] == ["user", "mark"]
