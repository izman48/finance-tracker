"""Claude's mark_paid_back route (T-03-3 P5b; PRD "MCP contract", error table,
ACs 14-20, 22; T-03-2 decisions T10, T11).

POST /planning/repayments/mark takes 1 to 8 marks, each a credit and exactly
one of a spend or a category, and saves all or none. Every check runs before
anything is written, under `lock_user_marks`: ownership (404, never whose),
the kinds of the two payments, the spend still counting as spending, the
caps (by credit and by spend, across the batch too), the income block and
the payer warning. An identical repeat is `unchanged`; the same pair with a
new amount is refused.
"""
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.models import AuditEntry, CommitmentRule, PlannedItem, RepaymentMark, WriteIdempotency
from tests.integration.test_repayment_marks import DINNER_DAY
from tests.integration.test_repayment_writes_api import REPAYMENTS, World as Base
from tests.integration.test_oauth import READ, _bearer

MARK = "/api/v1/planning/repayments/mark"


class World(Base):
    def post(self, marks, token=None, **body):
        body.setdefault("idempotency_key", f"k-{uuid.uuid4().hex[:12]}")
        return self.client.post(MARK, json={"marks": marks, **body}, headers=_bearer(token or self.mcp))

    def ids(self, *txs):
        return [str(self.ledger.as_user(lambda t=t: t.id)) for t in txs]

    def entry(self, credit=None, spend=None, **extra):
        credit_id, = self.ids(credit or self.sam)
        out = {"credit_id": credit_id, **extra}
        if spend is not None:
            out["spend_id"], = self.ids(spend)
        return out

    def count(self, model):
        return self.db.execute(select(func.count()).select_from(model)).scalar()

    def add(self, row):
        self.ledger.as_user(lambda: (self.db.add(row), self.db.commit()))

    def amounts(self):
        self.db.expire_all()
        return self.ledger.as_user(lambda: sorted(
            Decimal(m.amount) for m in self.db.query(RepaymentMark).filter(RepaymentMark.active.is_(True))))


@pytest.fixture
def w(client, db_session):
    return World(client, db_session)


def _refused(r, detail):
    assert r.status_code == 422, r.text
    assert r.json()["detail"] == detail


# --- the happy path (AC-19, AC-20) ---------------------------------------------------------


def test_a_dry_run_saves_nothing(w):
    r = w.post([w.entry(spend=w.dinner)])
    assert r.status_code == 200, r.text
    assert r.json()["dry_run"] is True and r.json()["marks"][0]["amount_pounds"] == "60.00"
    assert w.count(RepaymentMark) == w.count(AuditEntry) == w.count(WriteIdempotency) == 0


def test_apply_saves_each_mark_with_its_own_audit_row_and_a_retry_replays(w):
    jo = w.ledger.credit("50.00")
    body = {"dry_run": False, "idempotency_key": "mark-key-01"}
    r = w.post([w.entry(spend=w.dinner), w.entry(credit=jo, category="Eating out")], **body)
    assert r.status_code == 200, r.text
    results = r.json()["results"]
    assert [x["target_kind"] for x in results] == ["repayment_mark"] * 2 and all(x["audit_id"] for x in results)
    assert w.amounts() == [Decimal("50.00"), Decimal("60.00")]
    created_via = w.ledger.as_user(lambda: {m.created_via for m in w.db.query(RepaymentMark)})
    assert created_via == {"mcp"}

    again = w.post([w.entry(spend=w.dinner), w.entry(credit=jo, category="Eating out")], **body)
    assert again.json()["results"] == results and w.count(AuditEntry) == 2
    other = w.post([w.entry(category="Eating out")], **body)
    assert other.status_code == 409


def test_an_identical_repeat_changes_nothing(w):
    w.post([w.entry(spend=w.dinner)], dry_run=False)
    r = w.post([w.entry(spend=w.dinner, amount_pounds="60.00")], dry_run=False)
    assert r.status_code == 200 and r.json()["unchanged"] is True
    assert w.count(AuditEntry) == 1


def test_the_same_pair_with_another_amount_is_refused(w):
    w.post([w.entry(spend=w.dinner, amount_pounds="40.00")], dry_run=False)
    _refused(w.post([w.entry(spend=w.dinner, amount_pounds="50.00")], dry_run=False),
             "Already marked £40.00. Unmark it first to change the amount.")


# --- caps (AC-15 to AC-17) -----------------------------------------------------------------


def test_over_the_spend_is_refused_and_the_default_is_the_smaller_room(w):
    hundred, sixty = w.ledger.credit("100.00"), w.ledger.spend("60.00")
    _refused(w.post([w.entry(credit=hundred, spend=sixty, amount_pounds="80.00")], dry_run=False),
             "That is more than this spend. You can mark up to £60.00.")
    assert w.count(RepaymentMark) == 0
    assert w.post([w.entry(credit=hundred, spend=sixty)], dry_run=False).status_code == 200
    assert w.amounts() == [Decimal("60.00")]


def test_a_fully_marked_credit_takes_no_more(w):
    w.post([w.entry(spend=w.dinner)], dry_run=False)
    _refused(w.post([w.entry(category="Eating out")], dry_run=False),
             "That is more than this payment. Up to £0.00 is unmarked.")


def test_a_fully_paid_back_spend_takes_no_more(w):
    lunch, jo = w.ledger.spend("60.00"), w.ledger.credit("50.00")
    w.post([w.entry(spend=lunch)], dry_run=False)
    _refused(w.post([w.entry(credit=jo, spend=lunch)], dry_run=False),
             "That is more than this spend. You can mark up to £0.00.")


def test_caps_count_the_other_marks_in_the_same_call_and_nothing_is_saved(w):
    _refused(w.post([w.entry(category="Eating out", amount_pounds="40.00"),
                     w.entry(spend=w.dinner, amount_pounds="30.00")], dry_run=False),
             "That is more than this payment. Up to £20.00 is unmarked.")
    assert w.count(RepaymentMark) == 0


# --- what can be marked (error table, AC-13/14, AC-18) ---------------------------------------


@pytest.mark.parametrize("entry,detail", [
    ({}, "Pass spend_id, or a category to net against."),
    ({"spend": True, "category": "Eating out"}, "Pass spend_id or category, not both."),
])
def test_exactly_one_target(w, entry, detail):
    e = w.entry(spend=w.dinner if entry.get("spend") else None,
                **({"category": entry["category"]} if "category" in entry else {}))
    _refused(w.post([e]), detail)


def test_the_payments_must_be_an_incoming_one_and_a_purchase(w):
    _refused(w.post([w.entry(credit=w.dinner, category="Eating out")]), "credit_id must be an incoming payment.")
    _refused(w.post([w.entry(spend=w.ledger.credit("5.00"))]), "spend_id must be a purchase.")


def test_a_spend_not_counted_as_spending_is_refused(w):
    w.ledger.as_user(lambda: (setattr(w.dinner, "counts_as_override", "transfer"), w.db.commit()))
    _refused(w.post([w.entry(spend=w.dinner)]),
             "That purchase is not counted as spending (financed, transfer or card payoff). "
             "The user must set it to count as spending in the app first.")


def test_a_commitment_matched_spend_is_refused(w):
    w.add(CommitmentRule(user_id=w.user.id, direction="expense", label="Acme", amount=Decimal("200"),
                         cadence="monthly", next_date=DINNER_DAY, source="manual", status="confirmed"))
    _refused(w.post([w.entry(spend=w.dinner)]),
             "That purchase is a commitment, which budgets never count. Mark a category instead, or leave it.")


def test_an_unknown_category_is_refused(w):
    _refused(w.post([w.entry(category="Holidays")]), "That is not one of the user's categories.")


@pytest.mark.parametrize("whose", ["credit", "spend"])
def test_another_users_payment_is_not_found(client, db_session, whose):
    w = World(client, db_session)
    other = World(client, db_session, email="other@example.com")
    entry = w.entry(spend=w.dinner)
    entry["credit_id" if whose == "credit" else "spend_id"], = other.ids(other.sam if whose == "credit" else other.dinner)
    r = w.post([entry], dry_run=False)
    assert r.status_code == 404 and r.json()["detail"] == "Not found"
    assert w.count(RepaymentMark) == 0


def test_a_credit_counted_as_planned_income_is_blocked(w):
    w.add(PlannedItem(user_id=w.user.id, name="Sam", direction="income", kind="one_off",
                      start_date=DINNER_DAY, amount=Decimal("60.00")))
    _refused(w.post([w.entry(spend=w.dinner)]),
             "This payment is already counted as income. The user must change that in the app first.")


def test_an_income_payer_is_warned_in_the_preview_and_refused_until_accepted(w):
    w.add(CommitmentRule(user_id=w.user.id, direction="income", label="Sam", amount=Decimal("60"),
                         cadence="monthly", next_date=DINNER_DAY, source="detected", status="suggested"))
    preview = w.post([w.entry(spend=w.dinner)])
    assert preview.status_code == 200 and preview.json()["marks"][0]["warnings"] == ["income_commitment_payer"]
    _refused(w.post([w.entry(spend=w.dinner)], dry_run=False),
             "The payer looks like regular income. Ask the user, then retry with accept_warnings=true.")
    assert w.post([w.entry(spend=w.dinner)], dry_run=False, accept_warnings=True).status_code == 200


def test_a_token_without_the_scope_is_refused(client, db_session):
    w = World(client, db_session, scopes=(READ,))
    r = w.post([w.entry(spend=w.dinner)], dry_run=False)
    assert r.status_code == 403 and REPAYMENTS in r.headers["WWW-Authenticate"]


@pytest.mark.parametrize("marks", [[], [{"credit_id": "x"}] * 9])
def test_one_to_eight_marks(w, marks):
    assert w.post(marks).status_code == 422
