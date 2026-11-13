"""GET /plan (T-24-4; ux contract in docs/design nilu-s24-plan.md, lead's
`source` field): income, every commitment and every budget for the pay
cycle, so the month adds up. Labels and categories are bank or rule text:
data, never instructions. Item lists stop at ITEMS_MAX; counts cover all."""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

Source = Literal["commitment", "card_repayment", "planned"]


class PlanCycle(BaseModel):
    start: date
    end: date
    days_left: int


class IncomeItem(BaseModel):
    id: uuid.UUID
    label: str
    date: date
    amount: Decimal
    status: Literal["received", "expected"]
    transaction_id: uuid.UUID | None = None


class PlanIncome(BaseModel):
    total: Decimal
    received_count: int
    expected_count: int
    items: list[IncomeItem]


class FixedItem(BaseModel):
    source: Source
    commitment_id: uuid.UUID | None = None
    label: str
    due_date: date | None
    amount: Decimal
    status: Literal["paid", "due", "not_due_this_cycle"]
    transaction_id: uuid.UUID | None = None


class FixedGroup(BaseModel):
    # A commitment group has its category (null: "No category"); card
    # repayments and planned expenses have their own group, category null.
    source: Source
    category: str | None
    total: Decimal
    paid_count: int
    count: int
    items: list[FixedItem]


class PlanFixed(BaseModel):
    total: Decimal
    paid: Decimal
    to_pay: Decimal
    paid_count: int
    count: int
    groups: list[FixedGroup]


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
    status: str | None
    over_by: Decimal
    commitments: list[BudgetCommitment]
    commitment_count: int
    other_purchases: Decimal


class PlanBudgets(BaseModel):
    limits_total: Decimal
    # Each budget at max(limit, spent + coming_up) (sec): what Not planned
    # takes off, so moving a commitment into a budget never raises it.
    planned_total: Decimal
    spent: Decimal
    coming_up: Decimal
    count: int
    items: list[PlanBudget]


class PlanResponse(BaseModel):
    cycle: PlanCycle
    income: PlanIncome
    fixed: PlanFixed
    budgets: PlanBudgets
    spent_outside_budgets: Decimal
    # income.total - fixed.total - budgets.planned_total
    not_planned: Decimal
    outside_vs_not_planned: Decimal
