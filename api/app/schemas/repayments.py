"""Bodies of Claude's paid-back write routes (T-03-3 P5)."""
import uuid
from decimal import Decimal
from typing import Annotated

from datetime import date

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StrictBool, StringConstraints, model_validator

from app.core.display_text import has_hidden_characters
from app.schemas import PlanningWriteRequest
from app.services.repayment_candidates import DEFAULT_LIMIT, MAX_DAYS, MAX_LIMIT


def _visible(text: str) -> str:
    if has_hidden_characters(text):
        raise ValueError("must be visible text")
    return text


Hint = Annotated[str, StringConstraints(strip_whitespace=True, max_length=100), AfterValidator(_visible)]


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


class CandidatesRequest(BaseModel):
    """POST /repayments/candidates (read only): hints in the body, so a
    payer's name never reaches an access log (as transaction search)."""

    model_config = ConfigDict(extra="forbid")

    payer: Hint | None = None
    about: Hint | None = None
    spend_date: date | None = None
    frm: date | None = None
    to: date | None = None
    include_marked: StrictBool = False
    limit: int = Field(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT)

    @model_validator(mode="after")
    def _range(self) -> "CandidatesRequest":
        if self.frm and self.to:
            if self.frm > self.to:
                raise ValueError("frm must be on or before to")
            if (self.to - self.frm).days > MAX_DAYS:
                raise ValueError(f"the range can span at most {MAX_DAYS} days")
        return self
