"""Bodies of Claude's paid-back write routes (T-03-3 P5)."""
import uuid
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StringConstraints

from app.schemas import PlanningWriteRequest


class MarkEntry(BaseModel):
    """One mark: a credit and exactly one of a spend or a category (checked
    by the route, so Claude gets the PRD's sentence). No amount: the smaller
    of what is left on the credit and on the spend."""

    model_config = ConfigDict(extra="forbid")

    credit_id: uuid.UUID
    spend_id: uuid.UUID | None = None
    category: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)] | None = None
    amount_pounds: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)


class ClaudeMarkRequest(PlanningWriteRequest):
    """POST /planning/repayments/mark: 1 to 8 marks, saved together or not
    at all. `accept_warnings` lets a mark through the income-payer warning."""

    marks: list[MarkEntry] = Field(min_length=1, max_length=8)
    accept_warnings: StrictBool = False


class ClaudeUnmarkRequest(PlanningWriteRequest):
    """POST /planning/repayments/{mark_id}/unmark: `dry_run` and the
    idempotency key only (a body, so a dry run is charged as one)."""
