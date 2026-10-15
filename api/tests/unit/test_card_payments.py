"""The once-per-window rule for planned card payments (T-12-4a)."""
from datetime import date
from decimal import Decimal

from app.services.analytics.card_payments import pay_windows, resolve

D = date(2026, 11, 1)


def _rep(day, amount):
    return {"account_id": "c", "label": "Card", "amount": Decimal(amount), "due_date": date(2026, 11, day)}


def _plan(day, amount):
    return ("item", date(2026, 11, day), Decimal(amount))


def test_windows_are_cut_at_each_payday():
    assert pay_windows(D, date(2026, 12, 31), [date(2026, 11, 25), date(2026, 12, 25)]) == [
        (D, date(2026, 11, 24)), (date(2026, 11, 25), date(2026, 12, 24)), (date(2026, 12, 25), date(2026, 12, 31)),
    ]
    assert pay_windows(D, date(2026, 11, 30), []) == [(D, date(2026, 11, 30))]


def test_the_larger_side_counts_and_a_tie_keeps_the_planned_side():
    windows = [(D, date(2026, 11, 30))]
    plan, reps, _ = resolve(windows, [_plan(3, "500")], [_rep(5, "640")])
    assert (plan, [r["amount"] for r in reps]) == ([], [Decimal("640")])
    plan, reps, _ = resolve(windows, [_plan(3, "640")], [_rep(5, "640")])
    assert (len(plan), reps) == (1, [])


def test_each_window_is_decided_on_its_own():
    windows = pay_windows(D, date(2026, 11, 30), [date(2026, 11, 15)])
    plan, reps, out = resolve(windows, [_plan(20, "900")], [_rep(5, "640"), _rep(25, "300")])
    assert [p[2] for p in plan] == [Decimal("900")]
    assert [r["due_date"].day for r in reps] == [5]  # the 25th gives way to the larger planned 900
    assert [(w.overlaps, w.keeps_planned) for w in out] == [(False, False), (True, True)]


def test_nothing_is_ever_subtracted():
    windows = [(D, date(2026, 11, 30))]
    plan, reps, _ = resolve(windows, [_plan(3, "400")], [_rep(5, "640")])
    total = sum((p[2] for p in plan), Decimal(0)) + sum((r["amount"] for r in reps), Decimal(0))
    assert total == Decimal("640")  # max(400, 640), not 640 - 400 or 1,040
