"""Budgets API shapes (T-09-2; budgets concept sections 2, 13 and 15).

Published early (draft) so the UI (T-09-6, T-09-7) can build against them.
Money is Decimal (serialised as a string, like every other money field);
limits are whole pounds. Category is untrusted text: render it as text, and
never put it in a URL path (a budget is addressed by `id`).
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt

from app.schemas import ClaudeMarker

BUDGET_LIMIT_MAX = 100_000
BUDGETS_PER_USER_MAX = 20
CATEGORY_MAX_LENGTH = 100

# Pace status in words (concept section 2): neutral styling for all four.
PaceStatus = Literal["under_pace", "on_pace", "ahead_of_pace", "over"]


class BudgetCycle(BaseModel):
    """The pay cycle budgets track: last payday to the day before next payday.
    `fallback` is true when no payday is set (the last 30 days are used and
    the UI shows "Set your payday on Commitments so budgets follow it.")."""

    start: date
    end: date
    days_total: int
    days_left: int
    fallback: bool


class BudgetResponse(BaseModel):
    """One budget in the current cycle."""

    id: uuid.UUID
    category: str
    limit_pounds: int
    paused: bool
    created_via: Literal["web", "mcp"]
    # This cycle's spend under the budget-spend rule (T-09-1). A paused
    # budget still reports its spend; its status is null.
    spent: Decimal
    # Where even spending across the cycle would be by today (the pace tick).
    pace_spent: Decimal
    # max(0, spent - limit): "£x over".
    over_by: Decimal
    status: PaceStatus | None
    changed_by_claude: ClaudeMarker | None = None

    model_config = ConfigDict(from_attributes=True)


class NotCounted(BaseModel):
    """What the budget lens leaves out this cycle, with amounts, so the screen
    reconciles to the transactions ("Not counted here")."""

    commitments: Decimal
    transfers: Decimal
    card_payoffs: Decimal
    # A purchase moved to a payment plan: counted through its instalments.
    financed: Decimal


class Reconciliation(BaseModel):
    """The one line under the list: safe_to_spend - budgets_left -
    other_at_pace = headroom. All from this response, so the line can't
    disagree with itself; T-09-4's payday strip uses the same computation.
    safe_to_spend is the summary's figure, unchanged by budgets."""

    safe_to_spend: Decimal
    # Sum over active budgets of max(0, limit - spent). Paused or removed
    # this cycle count at max(remaining limit at pause, spend at pace) (T-09-4).
    budgets_left: Decimal
    # Other spending projected to the end of the cycle at its pace so far.
    other_at_pace: Decimal
    headroom: Decimal


class BudgetListResponse(BaseModel):
    """GET /budgets (and PUT /budgets): the current cycle."""

    cycle: BudgetCycle
    budgets: list[BudgetResponse]
    # Purchases this cycle in categories with no active, unpaused budget
    # (paused budgets' spending counts here).
    other_spending: Decimal
    # All purchases this cycle (= sum of budgets' spent + other_spending).
    total_spent: Decimal
    not_counted: NotCounted
    # Null when there's no active budget (the UI shows the empty state).
    reconciliation: Reconciliation | None = None
    # The categories a new budget can use: those on the user's purchases in
    # the last year, less those mostly commitments. Sorted. Text only. Only
    # with GET /budgets?include=categories (it reads a year of transactions);
    # null otherwise.
    budgetable_categories: list[str] | None = None


class CreateBudgetRequest(BaseModel):
    """POST /budgets."""

    model_config = ConfigDict(extra="forbid")

    category: str = Field(min_length=1, max_length=CATEGORY_MAX_LENGTH)
    limit_pounds: StrictInt = Field(ge=1, le=BUDGET_LIMIT_MAX)


class UpdateBudgetRequest(BaseModel):
    """PATCH /budgets/{id}: the limit, paused, or both."""

    model_config = ConfigDict(extra="forbid")

    limit_pounds: StrictInt | None = Field(default=None, ge=1, le=BUDGET_LIMIT_MAX)
    paused: StrictBool | None = None


class BudgetSetEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str = Field(min_length=1, max_length=CATEGORY_MAX_LENGTH)
    limit_pounds: StrictInt = Field(ge=1, le=BUDGET_LIMIT_MAX)


class BulkBudgetsRequest(BaseModel):
    """PUT /budgets: create or update each listed category's budget, all or
    nothing. Categories not listed are left as they are (removal is DELETE)."""

    model_config = ConfigDict(extra="forbid")

    budgets: list[BudgetSetEntry] = Field(min_length=1, max_length=BUDGETS_PER_USER_MAX)


class CycleFigure(BaseModel):
    start: date
    end: date
    spent: Decimal


class BudgetSuggestion(BaseModel):
    """One category's proposal. `suggested_limit` is the median of the last 3
    complete cycles rounded up to £10, or null with `reason`
    "not_enough_history"."""

    category: str
    last_cycles: list[CycleFigure]
    suggested_limit: int | None
    reason: Literal["not_enough_history"] | None = None
    # The active budget's limit today, for the diff ("£300 -> £260"), or null.
    current_limit: int | None = None


class BudgetSuggestResponse(BaseModel):
    """POST /budgets/suggest: dry, writes nothing."""

    suggestions: list[BudgetSuggestion]
    # Categories left out because their spending is mostly commitments.
    commitment_covered: list[str]
