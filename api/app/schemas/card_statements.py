"""Card statement API shapes (T-10-1).

Requests allow-list their fields (`extra="forbid"`): the client can never set
`user_id`, `source` or a derived figure. Money is Decimal (a string in JSON),
greater than 0, at most £1,000,000, 2 dp. Date rules that need today or the
stored row are checked by `services/analytics/statements.check_statement`.
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

MAX_STATEMENT_AMOUNT = Decimal("1000000")
StatementMoney = Annotated[Decimal, Field(gt=0, le=MAX_STATEMENT_AMOUNT, decimal_places=2)]


class CardStatementCreate(BaseModel):
    statement_balance: StatementMoney
    statement_date: date
    due_date: date
    minimum_due: StatementMoney | None = None

    model_config = ConfigDict(extra="forbid")


class CardStatementUpdate(BaseModel):
    """Patch a statement; omitted fields keep their stored value."""

    statement_balance: StatementMoney | None = None
    statement_date: date | None = None
    due_date: date | None = None
    minimum_due: StatementMoney | None = None

    model_config = ConfigDict(extra="forbid")


class CardStatementResponse(BaseModel):
    id: uuid.UUID
    account_id: uuid.UUID
    statement_balance: Decimal
    statement_date: date
    due_date: date
    minimum_due: Decimal | None
    source: str

    model_config = ConfigDict(from_attributes=True)


class CardStatementPosition(BaseModel):
    """The current statement and what is left of it. Derived on read."""

    statement_id: uuid.UUID
    source: str
    statement_balance: Decimal
    statement_date: date
    due_date: date
    minimum_due: Decimal | None
    payments_since_statement: Decimal
    amount_still_due: Decimal
    unbilled: Decimal
    paid: bool


class CardStatementsResponse(BaseModel):
    statements: list[CardStatementResponse]
    current: CardStatementPosition | None
