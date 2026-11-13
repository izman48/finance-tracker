"""Cashflow > Plan (T-25-2): Money in - Commitments - Budgets = Left over for
the pay cycle, in the shape the owner approved (sprint-25.md).

- Money in: credits this cycle that paid a confirmed income
  (`income_payments`, the lateness matcher, on the held versions), plus each
  income still expected before payday (held the lower of now and
  before-Claude; a late income adds nothing), plus other credits on a
  current account categorised Income, labelled by description. Transfers,
  card payments, refunds and credits marked paid back are never income.
- Commitments: confirmed expense commitments only (held the higher of now
  and before-Claude), grouped for display (`GROUPS`). Each instalment due
  this cycle is paid (a matched payment), coming (due today or later) or not
  seen (due earlier, no payment matched: still counted). Card repayments,
  card-tied bills, planned items and one-off purchases are not here.
- Budgets: `budget_list`; each counted at max(limit, spent + coming_up). A
  commitment whose category has a budget is counted there, not again here.

Every row is the caller's own; nothing is logged here.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy.orm import Session

from app.models import Account, AccountRole, CommitmentDirection, CommitmentRule, Transaction
from app.schemas.plan import (
    BudgetCommitment, CommitmentGroup, CommitmentItem, MoneyIn, MoneyInItem, PlanBudget, PlanBudgets,
    PlanCommitments, PlanCycle, PlanResponse,
)
from app.services.analytics.cadence import _step_back, commitment_occurrences
from app.services.analytics.commitments import rule_match_keys, transaction_match_key
from app.services.analytics.common import _d, _load, _today, resolve_roles
from app.services.analytics.late_income import income_payments, income_rule_keys, late_incomes
from app.services.analytics.repayments import card_repayment_rule_ids
from app.services.analytics.spending import (
    _effective_transfers, classify_noise, classify_purchase, financed_transaction_ids,
)
from app.services.analytics.statements import _REFUND_WORD
from app.services.budget_coming_up import coming_up_by_category
from app.services.budgets import budget_list
from app.services.categorization import INCOME_CATEGORY
from app.services.claude_keep import before_claude_label, claude_rows, counted_commitments
from app.services.commitment_category import commitment_categories
from app.services.linked_commitments import linked_commitments
from app.services.repayment_marks import marked_credit_ids

ITEMS_MAX = 50
ZERO = Decimal(0)
SAVINGS = "Savings"
OTHER = "Other"
# Display groups by category (compared case-insensitively), in this order;
# any other category is its own group after them, then "Other".
GROUPS = {
    "rent": "Rent & bills", "council tax": "Rent & bills", "utilities": "Rent & bills", "phone": "Rent & bills",
    "insurance": "Rent & bills", "debt repayments": "Debt repayments", "subscriptions": "Subscriptions",
}
ORDER = ["Rent & bills", "Debt repayments", "Subscriptions", SAVINGS]


def plan(db: Session, user) -> PlanResponse:
    today = _today()
    listing = budget_list(db, user)
    cycle = listing.cycle
    start, eve = cycle.start, cycle.end
    budgets = [b for b in listing.budgets if not b.paused]
    ledger = _ledger(db, user, start, today)

    money_in = _money_in(db, user, ledger, start, today, eve)
    commitments, budgeted_paid = _commitments(db, user, ledger, {b.category for b in budgets}, start, today, eve)
    # Every instalment: the budget list's own `coming_up.items` stops at five.
    coming = coming_up_by_category(db, user, today, eve, {b.category for b in budgets})
    plan_budgets = _budgets(budgets, budgeted_paid, coming)
    return PlanResponse(
        cycle=PlanCycle(start=start, end=eve, days_left=cycle.days_left),
        money_in=money_in, commitments=commitments, budgets=plan_budgets,
        left_over=money_in.total - commitments.total - plan_budgets.planned_total,
    )


def _ledger(db: Session, user, start: date, today: date) -> SimpleNamespace:
    """This cycle's transactions so far and what the spending lens makes of them."""
    accounts, settings = _load(db, user)
    roles = resolve_roles(accounts, settings)
    txns = (db.query(Transaction).join(Account)
            .filter(Account.user_id == user.id,
                    Transaction.transaction_date >= datetime.combine(start, datetime.min.time(), timezone.utc),
                    Transaction.transaction_date <= datetime.combine(today, datetime.max.time(), timezone.utc))
            .all())
    txns.sort(key=lambda t: (t.transaction_date, str(t.id)))
    return SimpleNamespace(txns=txns, roles=roles, transfers=_effective_transfers(txns),
                           financed=financed_transaction_ids(db, user))


# --- Money in -------------------------------------------------------------------

def _money_in(db: Session, user, ledger, start: date, today: date, eve: date) -> MoneyIn:
    items: list[MoneyInItem] = []
    # Received is matched against the held incomes only (sec on #305): an
    # unkept Claude confirm, raise or relabel never lets a credit count.
    versions = counted_commitments(db, user.id, CommitmentDirection.INCOME.value, lambda v: _d(v.amount))
    claude = claude_rows(db, user.id, [v.id for v in versions])
    held = {v.id: _as_rule(db, v, claude.get(v.id, [])) for v in versions}
    matched = set()
    for rule_id, credits in income_payments(db, user, today, rules=list(held.values())).items():
        matched |= {c.id for c in credits}
        items += [MoneyInItem(label=held[rule_id].label, date=c.day, amount=c.amount, status="received",
                              transaction_id=c.id) for c in credits if c.day >= start]
    # A credit with a confirmed income's key is that income, received or
    # still expected (paid early): never counted a second time (eng-a on #307).
    income_keys = {k for rule in held.values() for k in income_rule_keys(rule)}
    items += [MoneyInItem(label=tx.description or tx.merchant_name or "Income", date=tx.transaction_date.date(),
                          amount=_d(tx.amount), status="received", transaction_id=tx.id)
              for tx in _income_credits(db, user, ledger)
              if tx.id not in matched and transaction_match_key(tx) not in income_keys]

    first_due = today + timedelta(days=1)
    late = late_incomes(db, user, today)

    def worth(version) -> Decimal:
        return _d(version.amount) * len(commitment_occurrences(version, first_due, eve))
    for version in counted_commitments(db, user.id, CommitmentDirection.INCOME.value, worth):
        if version.id not in late:
            items += [MoneyInItem(label=version.label, date=d, amount=_d(version.amount), status="expected")
                      for d in commitment_occurrences(version, first_due, eve)]
    items.sort(key=lambda i: i.date)
    return MoneyIn(total=sum((i.amount for i in items), ZERO), items=items)


def _income_credits(db: Session, user, ledger) -> list[Transaction]:
    """Credits on a current account categorised Income that are not a
    transfer or card payment (`classify_noise`: paired legs, Transfers
    category, the user's override), a refund or marked paid back (lead, T-25-2)."""
    noise = classify_noise(ledger.txns, ledger.roles)
    paid_back = marked_credit_ids(db, user.id)
    return [
        tx for tx in ledger.txns
        if tx.transaction_type == "credit" and ledger.roles.get(tx.account_id) == AccountRole.SPENDING
        and (tx.category or "").strip().lower() == INCOME_CATEGORY.lower()
        and tx.id not in noise and tx.id not in paid_back
        and not _REFUND_WORD.search(f"{tx.description or ''} {tx.merchant_name or ''}".lower())
    ]


_MATCH_FIELDS = ("id", "direction", "label", "match_key", "amount", "cadence", "interval_days", "interval_months",
                 "next_date", "created_at", "skipped_through")


def _as_rule(db: Session, version, claude: list):
    """A held version with every field the income matcher reads: the
    version's where it has one (Claude's change held back), else the row's,
    and the label as it was before Claude's unkept relabels."""
    row = version if isinstance(version, CommitmentRule) else db.get(CommitmentRule, version.id)
    fields = {f: getattr(version, f, getattr(row, f)) for f in _MATCH_FIELDS}
    fields["label"] = before_claude_label(row, claude)
    return SimpleNamespace(**fields)


# --- Commitments ----------------------------------------------------------------

def _commitments(db: Session, user, ledger, budgeted: set[str], start: date, today: date, eve: date):
    """(the Commitments line, {budgeted category: [(payment, rule)]})."""
    def worth(version) -> Decimal:
        return _d(version.amount) * len(commitment_occurrences(version, start, eve))
    versions = [v for v in counted_commitments(db, user.id, CommitmentDirection.EXPENSE.value, worth)
                if _d(v.amount) > 0]
    rows = {r.id: r for r in db.query(CommitmentRule).filter(
        CommitmentRule.user_id == user.id, CommitmentRule.id.in_([v.id for v in versions])).all()}
    category_of = commitment_categories(db, user, rows.values())
    savings = {cid for cid, owner in linked_commitments(db, user.id).items() if owner.kind == "holding"}
    card_bills = card_repayment_rule_ids(db, user, versions, today)
    payments = _payments(ledger, [rows[v.id] for v in versions], savings)

    groups: dict[str, list[CommitmentItem]] = defaultdict(list)
    budgeted_paid: dict[str, list] = defaultdict(list)
    for version in versions:
        category = category_of.get(version.id)
        if version.id in card_bills:
            continue
        if version.id not in savings and category in budgeted:
            budgeted_paid[category] += [(tx, version) for tx in payments[version.id]]
            continue
        groups[_group_name(category, version.id in savings)] += _instalments(
            version, payments[version.id], start, today, eve)
    out = [_group(name, items) for name, items in sorted(groups.items(), key=lambda g: _order(g[0]))]
    return PlanCommitments(total=sum((g.total for g in out), ZERO), groups=out), budgeted_paid


def _payments(ledger, rules: list[CommitmentRule], savings: set) -> dict:
    """Each rule's payments this cycle so far. A payment pays one rule at
    most. A savings contribution may be filed as a transfer, so it matches
    on its key alone."""
    keys = {r.id: rule_match_keys(r) for r in rules}
    out: dict = defaultdict(list)
    for tx in ledger.txns:
        key = transaction_match_key(tx)
        for rule in rules:
            if key in keys[rule.id] and _pays(tx, keys[rule.id], ledger, rule.id in savings):
                out[rule.id].append(tx)
                break
    return out


def _pays(tx, keys: set[str], ledger, savings: bool) -> bool:
    """The one commitment matcher (`classify_purchase`, as budget spend uses)."""
    kind = classify_purchase(tx, ledger.transfers, ledger.roles, ledger.financed, keys)
    return kind == "commitment" or (savings and kind == "transfer")


def _instalments(version, paid: list[Transaction], start: date, today: date, eve: date) -> list[CommitmentItem]:
    """Its payments this cycle, then each instalment due this cycle that no
    payment has taken (earliest taken first): coming from today on, not seen
    before today. A missed match lists a bill twice, which only lowers Left
    over (the safe side)."""
    items = [CommitmentItem(commitment_id=version.id, label=version.label, date=tx.transaction_date.date(),
                            amount=_d(tx.amount), status="paid", transaction_id=tx.id) for tx in paid]
    items += [CommitmentItem(commitment_id=version.id, label=version.label, date=d, amount=_d(version.amount),
                             status="coming" if d >= today else "not_seen")
              for d in _due(version, start, eve)[len(paid):]]
    return items


def _due(version, start: date, eve: date) -> list[date]:
    """Its instalment dates in [start, eve]. The stored next date may be
    ahead of the cycle, so step back past `start` first (lessons, #210)."""
    d, guard = version.next_date, 0
    while d is not None and d >= start and guard < 600:
        d = _step_back(d, version.cadence, version.interval_days, version.interval_months)
        guard += 1
    if d is None:
        return []
    walk = SimpleNamespace(next_date=d, cadence=version.cadence, interval_days=version.interval_days,
                           interval_months=version.interval_months, ends_on=getattr(version, "ends_on", None))
    return commitment_occurrences(walk, start, eve)


def _group_name(category: str | None, savings: bool) -> str:
    if savings:
        return SAVINGS
    if not (category or "").strip():
        return OTHER
    return GROUPS.get(category.strip().lower(), category)


def _order(name: str) -> tuple:
    return (ORDER.index(name) if name in ORDER else len(ORDER), name == OTHER, name)


def _group(name: str, items: list[CommitmentItem]) -> CommitmentGroup:
    items.sort(key=lambda i: (i.date, i.label))
    return CommitmentGroup(name=name, total=sum((i.amount for i in items), ZERO), count=len(items),
                           paid_count=sum(i.status == "paid" for i in items), items=items[:ITEMS_MAX])


# --- Budgets --------------------------------------------------------------------

def _budgets(budgets, budgeted_paid: dict, coming: dict) -> PlanBudgets:
    items = []
    for b in budgets:
        lines = [BudgetCommitment(commitment_id=rule.id, label=rule.label, date=tx.transaction_date.date(),
                                  amount=_d(tx.amount), status="paid", transaction_id=tx.id)
                 for tx, rule in budgeted_paid.get(b.category, []) if tx.category == b.category]
        paid_sum = sum((line.amount for line in lines), ZERO)
        lines += [BudgetCommitment(commitment_id=i.commitment_id, label=i.label, date=i.due_date, amount=i.amount,
                                   status="due")
                  for i in (coming[b.category].instalments if b.category in coming else [])]
        limit = Decimal(b.limit_pounds)
        items.append(PlanBudget(
            budget_id=b.id, category=b.category, limit=limit, spent=b.spent, coming_up=b.coming_up.amount,
            planned=max(limit, b.spent + b.coming_up.amount), status=b.status, over_by=b.over_by,
            commitments=lines[:ITEMS_MAX], other_purchases=max(ZERO, b.spent - paid_sum)))
    return PlanBudgets(limits_total=sum((i.limit for i in items), ZERO),
                       planned_total=sum((i.planned for i in items), ZERO), items=items)
