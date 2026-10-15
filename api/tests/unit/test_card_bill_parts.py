"""What a card bill is made of (T-12-7a part 2; lead decision 2026-10-15).

Each card repayment says whether it is projected and what it is made of,
from the API, summed to the amount; no amount or date moves:
- the statement's still-due amount is a real bill: not projected, part
  "statement";
- the spend since the statement, paid on the next pay day, is projected,
  part "spent_since";
- with no statement (or an overdue one), the whole balance on the next pay
  day is projected, part "balance";
- any other strategy is shown as today: not projected, no parts.
Synthetic figures only.
"""
from decimal import Decimal

from app.services import analytics_service as svc
from tests.clock import TODAY
from tests.unit.test_statement_balance_strategy import DUE, NEXT_DUE, World
from datetime import timedelta


def _events(w):
    return svc.repayment_events(w.db, w.user, TODAY, TODAY + timedelta(days=80))


def _shape(w):
    return [(r["due_date"], r["amount"], r["projected"], [(p["kind"], p["amount"]) for p in r["parts"]]) for r in _events(w)]


def test_a_statement_and_the_spend_since_it(db_session):
    w = World(db_session)
    w.statement()
    assert _shape(w) == [
        (DUE, Decimal("5000"), False, [("statement", Decimal("5000"))]),
        (NEXT_DUE, Decimal("1000"), True, [("spent_since", Decimal("1000"))]),
    ]


def test_no_statement_is_the_whole_balance_projected(db_session):
    w = World(db_session)
    (only,) = _shape(w)
    assert only[1:] == (Decimal("6000"), True, [("balance", Decimal("6000"))])


def test_parts_always_sum_to_the_amount(db_session):
    for balance in ("6000", "5000", "4500"):
        w = World(db_session, balance=balance)
        w.statement()
        for r in _events(w):
            assert sum(p["amount"] for p in r["parts"]) == r["amount"]


def test_another_strategy_is_shown_as_today(db_session):
    w = World(db_session, strategy="full_balance")
    w.statement()
    assert [(r["projected"], r["parts"]) for r in _events(w)] == [(False, [])]


def test_the_forecast_marks_a_projected_bill(db_session):
    w = World(db_session)
    w.statement()
    f = svc.get_forecast(w.db, w.user, horizon="80")
    marks = [(p["date"], e["projected"]) for p in f["timeline"] for e in p["events"] if e["kind"] == "repayment"]
    assert marks == [(DUE, False), (NEXT_DUE, True)]
