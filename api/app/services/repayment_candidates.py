"""Repayment candidates: incoming payments that may be friends paying the
user back, each with the spend it most likely paid back (T-03-5 P7). The
rules and weights are the PRD's "Which spend is most likely" (T-03-1 v2,
T-03-2 T12); the weights are starting values (decision 13). Computed per
request with the user's key and never stored. Bank text is data.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.clock import LONDON
from app.models import Account, Transaction
from app.services.analytics.commitments import commitment_match_keys
from app.services.analytics.common import _d, _load, resolve_roles
from app.services.analytics.late_income import _payer
from app.services.analytics.planned_matching import _words
from app.services.analytics.spending import _effective_transfers, classify_purchase, financed_transaction_ids
from app.services.paid_back import UNCATEGORISED
from app.services.repayment_guards import income_commitment_payers, income_locked_credit_ids
from app.services.repayment_marks import active_marks, remaining

DEFAULT_DAYS, MAX_DAYS = 45, 366
DEFAULT_LIMIT, MAX_LIMIT = 20, 50
BEFORE_DAYS, AFTER_DAYS = 21, 3
LIKELY, FALLBACK, HIGH, LEAD = 45, 30, 70, 15
TOLERANCE_FLOOR, TOLERANCE_SHARE = Decimal("1.00"), Decimal("0.02")
CENT = Decimal("0.01")


@dataclass(frozen=True)
class _Scored:
    spend: Transaction
    remaining: Decimal
    score: int
    reasons: list[str]
    days: int  # credit day - spend day; negative when the spend came after


def repayment_candidates(db: Session, user, *, today: date, payer: str | None = None, about: str | None = None,
                         spend_date: date | None = None, frm: date | None = None, to: date | None = None,
                         include_marked: bool = False, limit: int = DEFAULT_LIMIT) -> list[dict]:
    """The user's credits in [frm, to] (default the last 45 days), newest
    first, each with its likely spend, up to 2 alternatives and a fallback
    category."""
    to = to or today
    frm = max(frm or to - timedelta(days=DEFAULT_DAYS), to - timedelta(days=MAX_DAYS))
    txns = _own_transactions(db, user, frm - timedelta(days=AFTER_DAYS), to + timedelta(days=AFTER_DAYS))
    credits = [t for t in txns if t.transaction_type == "credit" and frm <= _uk_day(t) <= to]
    payer_words = _words(payer or "")
    if payer_words:
        credits = [c for c in credits if payer_words & _words(_reference(c))]
    spends = _eligible_spends(db, user, frm - timedelta(days=BEFORE_DAYS), to + timedelta(days=AFTER_DAYS))
    left = remaining(db, user.id, [t.id for t in credits] + [s.id for s in spends])
    marks = active_marks(db, user.id)
    marked_spends = {m.spend_id for m in marks if m.spend_id is not None}
    if not include_marked:
        credits = [c for c in credits if left.get(c.id, Decimal(0)) >= CENT]
    credits.sort(key=lambda c: (c.transaction_date, c.id), reverse=True)
    credits = credits[:max(1, min(limit, MAX_LIMIT))]

    blocked = income_locked_credit_ids(db, user, today)
    warned = income_commitment_payers(db, user, [c.id for c in credits])
    hints = (_words(about or ""), spend_date)
    out = []
    for credit in credits:
        ranked = _rank(credit, left[credit.id], spends, left, marked_spends, hints)
        out.append(_candidate(credit, left[credit.id], ranked, blocked.get(credit.id), credit.id in warned,
                              [m for m in marks if m.credit_id == credit.id] if include_marked else None))
    return out


def _rank(credit, unmarked, spends, left, marked_spends, hints) -> list[_Scored]:
    tolerance = max(TOLERANCE_FLOOR, unmarked * TOLERANCE_SHARE)
    scored = []
    for spend in spends:
        days = (_uk_day(credit) - _uk_day(spend)).days
        room = left.get(spend.id, Decimal(0))
        if -AFTER_DAYS <= days <= BEFORE_DAYS and unmarked >= CENT and room >= unmarked - tolerance:
            scored.append(_score(credit, unmarked, spend, room, days, spend.id in marked_spends, hints))
    # Ties: nearest date, then more left, then id.
    return sorted(scored, key=lambda s: (-s.score, abs(s.days), -s.remaining, str(s.spend.id)))


def _score(credit, unmarked, spend, room, days, has_marks, hints) -> _Scored:
    about, spend_date = hints
    reasons = []
    amount = _amount_points(unmarked, _d(spend.amount), room)
    reasons.append("The amount matches." if amount == 35 and unmarked / room >= Decimal("0.95")
                   else "It is an equal share of the bill." if amount == 35
                   else "It is part of the bill.")
    spend_words = _words(f"{spend.merchant_name or ''} {spend.description or ''} {spend.category or ''}")
    words = 0
    if _words(_reference(credit)) & spend_words:
        words += 10
        reasons.append("The payment's reference shares a word with the purchase.")
    if about & spend_words:
        words += 10
        reasons.append("It matches what the user said it was for.")
    if spend_date is not None and _uk_day(spend) == spend_date:
        words += 15
        reasons.append("It is on the day the user named.")
    when = _date_points(days)
    reasons.append(f"It was {abs(days)} days {'before' if days >= 0 else 'after'} the payment.")
    unmarked_points = 15 if not has_marks else 10 if room >= unmarked else 0
    return _Scored(spend, room, amount + min(25, words) + when + unmarked_points, reasons, days)


def _amount_points(unmarked: Decimal, spend_amount: Decimal, room: Decimal) -> int:
    if Decimal("0.95") <= unmarked / room <= Decimal("1.02"):
        return 35
    # An equal split reads the spend's full amount, so Jo's £50 still looks
    # like a quarter of £200 after Sam's £60 is marked (T-03-2 T12).
    share = spend_amount / unmarked
    nearest = share.to_integral_value()
    return 35 if 2 <= nearest <= 8 and abs(share - nearest) <= nearest * TOLERANCE_SHARE else 20


def _date_points(days: int) -> int:
    if days < 0:
        return 8
    return 25 if days <= 3 else 18 if days <= 7 else 10 if days <= 14 else 4


def _candidate(credit, unmarked, ranked, blocked, warned, marks) -> dict:
    best = ranked[0] if ranked else None
    likely = best if best and best.score >= LIKELY else None
    confidence = "medium"
    if likely:
        lead = likely.score - ranked[1].score if len(ranked) > 1 else LEAD
        confidence = "high" if likely.score >= HIGH and lead >= LEAD else "medium"
    out = {
        "credit_id": str(credit.id), "date": _uk_day(credit), "amount_pounds": _pounds(_d(credit.amount)),
        "payer": " ".join(_payer(_reference(credit))), "description": credit.description,
        "unmarked_pounds": _pounds(unmarked),
        "suggested_amount_pounds": _pounds(min(unmarked, likely.remaining) if likely else unmarked),
        "blocked": blocked, "warnings": ["income_commitment_payer"] if warned else [],
        "likely_spend": _spend(likely, confidence) if likely else None,
        # Never "high": each is at most the likely spend's score.
        "alternatives": [_spend(s, "medium" if s.score >= LIKELY else "low")
                         for s in ranked[1:3] if likely and s.score >= FALLBACK],
        "fallback_category": (best.spend.category or UNCATEGORISED) if best and not likely and best.score >= FALLBACK
        else None,
    }
    if marks is not None:
        out["marks"] = [{"mark_id": str(m.id), "amount_pounds": _pounds(m.applied_amount),
                         "spend_id": str(m.spend_id) if m.spend_id else None, "category": m.category,
                         "applied": m.applied_amount > 0} for m in marks]
    return out


def _spend(s: _Scored, confidence: str) -> dict:
    return {
        "spend_id": str(s.spend.id), "date": _uk_day(s.spend), "label": s.spend.merchant_name or s.spend.description,
        "amount_pounds": _pounds(_d(s.spend.amount)), "remaining_pounds": _pounds(s.remaining),
        "category": s.spend.category or UNCATEGORISED, "score": s.score, "confidence": confidence,
        "reasons": s.reasons,
    }


def _eligible_spends(db: Session, user, start: date, end: date) -> list[Transaction]:
    accounts, settings = _load(db, user)
    roles = resolve_roles(accounts, settings)
    txns = _own_transactions(db, user, start, end)
    transfers, financed, keys = _effective_transfers(txns), financed_transaction_ids(db, user), \
        commitment_match_keys(db, user)
    return [t for t in txns if classify_purchase(t, transfers, roles, financed, keys) in ("credit", "cash")]


def _own_transactions(db: Session, user, start: date, end: date) -> list[Transaction]:
    # A day either side: the window is in UK days, timestamps in UTC.
    return (
        db.query(Transaction)
        .join(Account)
        .filter(
            Account.user_id == user.id,
            Transaction.transaction_date >= datetime.combine(start - timedelta(days=1), time.min, timezone.utc),
            Transaction.transaction_date <= datetime.combine(end + timedelta(days=1), time.max, timezone.utc),
        )
        .all()
    )


def _reference(tx: Transaction) -> str:
    return tx.merchant_name or tx.description or ""


def _uk_day(tx: Transaction) -> date:
    moment = tx.transaction_date
    return (moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)).astimezone(LONDON).date()


def _pounds(amount: Decimal) -> str:
    return str(Decimal(amount).quantize(CENT))

