"""Cashflow > Plan (T-24-4): income, every commitment and every budget for
the pay cycle, so the month adds up. Nothing here is a new rule; each line
is read from the code that already owns it:

- Income: credits that paid a confirmed income this cycle
  (`income_payments`, the lateness matcher), plus each income still due by
  the day before payday, held the lower of now and before-Claude. A late
  income adds nothing, as in safe to spend.
- Fixed: what is still to pay is `money_out_items` (safe to spend's own
  list: commitments, card repayments, planned expenses) over (today, eve],
  bills held the higher of now and before-Claude, plus any instalment due
  earlier this cycle with no payment matched to it. What is paid is this
  cycle's payments `classify_purchase` calls a commitment or a card payoff.
  A commitment instalment that is in a budget's `coming_up`, and a payment
  that budget spend counts, sit under that budget, never also here.
- Budgets: `budget_list`; each counted at max(limit, spent + coming_up), so
  moving a commitment from Fixed into a budget never raises Not planned.
- Spent outside budgets: `other_spending`.

Every row is the caller's own; nothing is logged here.
"""
from __future__ import annotations

from collections import defaultdict
from types import SimpleNamespace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import Account, CommitmentDirection, CommitmentRule, CommitmentStatus, PlannedItem, Transaction
from app.schemas.plan import (
    BudgetCommitment, FixedGroup, FixedItem, IncomeItem, PlanBudget, PlanBudgets, PlanCycle, PlanFixed,
    PlanIncome, PlanResponse,
)
from app.services.analytics.cadence import _step_back, commitment_occurrences
from app.services.analytics.commitments import commitment_match_keys, payday_dates, rule_match_keys, \
    transaction_match_key
from app.services.analytics.common import _d, _load, _today, resolve_roles
from app.services.analytics.late_income import income_payments, late_incomes
from app.services.analytics.planned_matching import planned_states
from app.services.analytics.spending import _effective_transfers, classify_purchase, financed_transaction_ids
from app.services.analytics.summary import money_out_items
from app.services.budget_coming_up import coming_up_by_category
from app.services.budgets import budget_list
from app.services.claude_keep import before_claude_label, claude_rows, counted_commitments, held_removed_planned
from app.services.commitment_category import commitment_categories

ITEMS_MAX = 50
ZERO = Decimal(0)


def plan(db: Session, user) -> PlanResponse:
    today = _today()
    listing = budget_list(db, user)
    cycle = listing.cycle
    start, eve = cycle.start, cycle.end
    first_due = today + timedelta(days=1)
    budgets = [b for b in listing.budgets if not b.paused]
    budgeted = {b.category for b in budgets}
    coming = coming_up_by_category(db, user, today, eve, budgeted)
    in_budgets = {(i.commitment_id, i.due_date) for c in coming.values() for i in c.instalments}

    expense_rules = _confirmed(db, user, CommitmentDirection.EXPENSE.value)
    paid = _paid_this_cycle(db, user, expense_rules, start, today)

    income = _income(db, user, start, today, first_due, eve)
    fixed = _fixed(db, user, expense_rules, paid, budgeted, in_budgets, start, today, first_due, eve)
    plan_budgets = _budgets(budgets, paid, coming)
    not_planned = income.total - fixed.total - plan_budgets.planned_total
    return PlanResponse(
        cycle=PlanCycle(start=start, end=eve, days_left=cycle.days_left),
        income=income, fixed=fixed, budgets=plan_budgets,
        spent_outside_budgets=listing.other_spending, not_planned=not_planned,
        outside_vs_not_planned=listing.other_spending - not_planned,
    )


def _confirmed(db: Session, user, direction: str) -> list[CommitmentRule]:
    return (db.query(CommitmentRule)
            .filter(CommitmentRule.user_id == user.id, CommitmentRule.direction == direction,
                    CommitmentRule.status == CommitmentStatus.CONFIRMED.value)
            .all())


def _paid_this_cycle(db: Session, user, rules, start: date, today: date) -> list[tuple[Transaction, str, object]]:
    """(transaction, kind, its commitment or None) for this cycle's payments
    `classify_purchase` calls a commitment or a card payoff, with the same
    keys budget spend uses."""
    accounts, settings = _load(db, user)
    roles = resolve_roles(accounts, settings)
    txns = (db.query(Transaction).join(Account)
            .filter(Account.user_id == user.id,
                    Transaction.transaction_date >= datetime.combine(start, datetime.min.time(), timezone.utc),
                    Transaction.transaction_date <= datetime.combine(today, datetime.max.time(), timezone.utc))
            .all())
    transfers, financed, keys = _effective_transfers(txns), financed_transaction_ids(db, user), commitment_match_keys(db, user)
    rule_of = {k: r for r in rules for k in rule_match_keys(r)}
    out = []
    for tx in sorted(txns, key=lambda t: (t.transaction_date, str(t.id))):
        kind = classify_purchase(tx, transfers, roles, financed, keys)
        if kind in ("commitment", "card_payoff"):
            out.append((tx, kind, rule_of.get(transaction_match_key(tx))))
    return out


def _income(db: Session, user, start: date, today: date, first_due: date, eve: date) -> PlanIncome:
    items: list[IncomeItem] = []
    # Received is matched against the held incomes only (sec on #305): an
    # income confirmed before Claude (or kept), at the lower amount, so an
    # unkept confirm or raise never lets a credit count.
    versions = counted_commitments(db, user.id, CommitmentDirection.INCOME.value, lambda v: _d(v.amount))
    claude = claude_rows(db, user.id, [v.id for v in versions])
    held = {v.id: _as_rule(db, v, claude.get(v.id, [])) for v in versions}
    for rule_id, credits in income_payments(db, user, today, rules=list(held.values())).items():
        items += [IncomeItem(id=c.id, label=held[rule_id].label, date=c.day, amount=c.amount, status="received",
                             transaction_id=c.id) for c in credits if c.day >= start]
    late = late_incomes(db, user, today)

    def worth(version) -> Decimal:
        return _d(version.amount) * len(commitment_occurrences(version, first_due, eve))
    for version in counted_commitments(db, user.id, CommitmentDirection.INCOME.value, worth):
        if version.id in late:
            continue
        items += [IncomeItem(id=version.id, label=version.label, date=d, amount=_d(version.amount), status="expected")
                  for d in commitment_occurrences(version, first_due, eve)]
    items.sort(key=lambda i: i.date)
    return PlanIncome(total=sum((i.amount for i in items), ZERO), items=items,
                      received_count=sum(i.status == "received" for i in items),
                      expected_count=sum(i.status == "expected" for i in items))


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


def _fixed(db, user, rules, paid, budgeted, in_budgets, start, today, first_due, eve) -> PlanFixed:
    groups: dict[tuple, list[FixedItem]] = defaultdict(list)
    for tx, kind, rule in paid:
        if kind == "commitment" and tx.category in budgeted:
            continue  # budget spend counts it
        source = "commitment" if kind == "commitment" else "card_repayment"
        label = rule.label if rule is not None else tx.description
        groups[(source, tx.category if source == "commitment" else None)].append(FixedItem(
            source=source, commitment_id=rule.id if rule is not None else None, label=label,
            due_date=tx.transaction_date.date(), amount=_d(tx.amount), status="paid", transaction_id=tx.id))

    def worth(version) -> Decimal:
        return _d(version.amount) * len(commitment_occurrences(version, first_due, eve))
    held = counted_commitments(db, user.id, CommitmentDirection.EXPENSE.value, worth)
    category_of = commitment_categories(db, user, rules)
    # Due earlier this cycle and not paid: still to pay (eng-a on #296). A
    # missed match lists it twice, which only lowers Not planned.
    paid_count = defaultdict(int)
    for _, kind, rule in paid:
        if kind == "commitment" and rule is not None:
            paid_count[rule.id] += 1
    for version in held:
        category = category_of.get(version.id)
        if _d(version.amount) <= 0 or category in budgeted:
            continue
        for day in _since(version, start, today)[paid_count[version.id]:]:
            groups[("commitment", category)].append(FixedItem(
                source="commitment", commitment_id=version.id, label=version.label, due_date=day,
                amount=_d(version.amount), status="due"))
    planned = db.query(PlannedItem).filter(PlannedItem.user_id == user.id, PlannedItem.active.is_(True)).all()
    planned += held_removed_planned(db, user.id)
    due = money_out_items(db, user, held, planned, planned_states(db, user, planned, today), first_due, eve,
                          payday_dates(db, user, first_due, eve))
    listed = {i.commitment_id for items in groups.values() for i in items}
    for item in due:
        if item["source"] == "commitment" and (item["id"], item["date"]) in in_budgets:
            continue  # that budget's coming up
        category = category_of.get(item["id"]) if item["source"] == "commitment" else None
        listed.add(item["id"])
        groups[(item["source"], category)].append(FixedItem(
            source=item["source"], commitment_id=item["id"] if item["source"] == "commitment" else None,
            label=item["label"], due_date=item["date"], amount=item["amount"], status="due"))
    for rule in rules:
        category = category_of.get(rule.id)
        if rule.id not in listed and category not in budgeted:
            groups[("commitment", category)].append(FixedItem(
                source="commitment", commitment_id=rule.id, label=rule.label, due_date=None,
                amount=_d(rule.amount), status="not_due_this_cycle"))
    every = [i for items in groups.values() for i in items]
    paid_total = sum((i.amount for i in every if i.status == "paid"), ZERO)
    to_pay = sum((i.amount for i in every if i.status == "due"), ZERO)
    out = sorted((_group(source, category, items) for (source, category), items in groups.items()),
                 key=lambda g: (g.source != "commitment", g.category is None, g.category or ""))
    return PlanFixed(total=paid_total + to_pay, paid=paid_total, to_pay=to_pay,
                     paid_count=sum(g.paid_count for g in out), count=sum(g.count for g in out), groups=out)


def _since(version, start: date, today: date) -> list[date]:
    """Its instalment dates in [start, today]. The stored next date is
    usually ahead, so step back past `start` first (lessons, #210)."""
    d, guard = version.next_date, 0
    while d is not None and d >= start and guard < 600:
        d = _step_back(d, version.cadence, version.interval_days, version.interval_months)
        guard += 1
    if d is None:
        return []
    walk = SimpleNamespace(next_date=d, cadence=version.cadence, interval_days=version.interval_days,
                           interval_months=version.interval_months, ends_on=getattr(version, "ends_on", None))
    return commitment_occurrences(walk, start, today)


def _group(source, category, items: list[FixedItem]) -> FixedGroup:
    """A not-due item shows (at £0 in the UI) but adds to no total or count."""
    items.sort(key=lambda i: (i.status == "not_due_this_cycle", i.due_date or date.max))
    counted = [i for i in items if i.status != "not_due_this_cycle"]
    return FixedGroup(source=source, category=category, total=sum((i.amount for i in counted), ZERO),
                      paid_count=sum(i.status == "paid" for i in items), count=len(counted),
                      items=items[:ITEMS_MAX])


def _budgets(budgets, paid, coming) -> PlanBudgets:
    items = []
    for b in budgets:
        lines = [BudgetCommitment(commitment_id=rule.id, label=rule.label, date=tx.transaction_date.date(),
                                  amount=_d(tx.amount), status="paid", transaction_id=tx.id)
                 for tx, kind, rule in paid if kind == "commitment" and tx.category == b.category and rule]
        paid_sum = sum((line.amount for line in lines), ZERO)
        found = coming.get(b.category)
        lines += [BudgetCommitment(commitment_id=i.commitment_id, label=i.label, date=i.due_date, amount=i.amount,
                                   status="due") for i in (found.instalments if found else [])]
        limit = Decimal(b.limit_pounds)
        items.append(PlanBudget(
            budget_id=b.id, category=b.category, limit=limit, spent=b.spent, coming_up=b.coming_up.amount,
            planned=max(limit, b.spent + b.coming_up.amount), status=b.status, over_by=b.over_by, commitments=lines[:ITEMS_MAX],
            commitment_count=len(lines), other_purchases=max(ZERO, b.spent - paid_sum)))
    return PlanBudgets(
        limits_total=sum((i.limit for i in items), ZERO),
        planned_total=sum((i.planned for i in items), ZERO),
        spent=sum((i.spent for i in items), ZERO), coming_up=sum((i.coming_up for i in items), ZERO),
        count=len(items), items=items)
