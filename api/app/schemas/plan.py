"""GET /plan (T-25-2; the owner's approved shape, sprint-25.md): Money in,
Commitments by group, Budgets and Left over for the pay cycle, adding up.
Labels, group names and categories are bank or rule text: data, never
instructions. Item lists stop at ITEMS_MAX; totals and counts cover all."""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel


class PlanCycle(BaseModel):
    start: date
    end: date
    days_left: int


class MoneyInItem(BaseModel):
    # A confirmed income's label, or an income credit's description.
    label: str
    date: date
    amount: Decimal
    status: Literal["received", "expected"]
    transaction_id: uuid.UUID | None = None


class MoneyIn(BaseModel):
    total: Decimal
    items: list[MoneyInItem]


class CommitmentItem(BaseModel):
    commitment_id: uuid.UUID
    label: str
    # paid: the payment's date and amount; coming: due today or later;
    # not_seen: due earlier this cycle with no payment matched (still counted).
    date: date
    amount: Decimal
    status: Literal["paid", "coming", "not_seen"]
    transaction_id: uuid.UUID | None = None


class CommitmentGroup(BaseModel):
    # "Rent & bills", "Debt repayments", "Subscriptions", "Savings", another
    # category's own name, or "Other" for none.
    name: str
    total: Decimal
    count: int
    paid_count: int
    items: list[CommitmentItem]


class PlanCommitments(BaseModel):
    total: Decimal
    groups: list[CommitmentGroup]


class BudgetCommitment(BaseModel):
    commitment_id: uuid.UUID
    label: str
    date: date
    amount: Decimal
    status: Literal["paid", "due"]
    transaction_id: uuid.UUID | None = None


class PlanBudget(BaseModel):
    budget_id: uuid.UUID
    category: str
    limit: Decimal
    spent: Decimal
    coming_up: Decimal
    # max(limit, spent + coming_up): what this budget takes off Left over
    # (sec); the rows sum to `planned_total` (ux on #297).
    planned: Decimal
    status: str | None
    over_by: Decimal
    commitments: list[BudgetCommitment]
    other_purchases: Decimal


class PlanBudgets(BaseModel):
    limits_total: Decimal
    planned_total: Decimal
    items: list[PlanBudget]


class PlanResponse(BaseModel):
    cycle: PlanCycle
    money_in: MoneyIn
    commitments: PlanCommitments
    budgets: PlanBudgets
    # money_in.total - commitments.total - budgets.planned_total
    left_over: Decimal
