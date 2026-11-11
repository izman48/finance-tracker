"""Claude's read of likely repayments (T-03-5 P8; PRD `list_repayment_candidates`).

`finance:read` (or a web session). Each call decrypts the user's recent
transactions, so it is rate limited per user. Only the caller's own
payments are read; bank text in the result is data.
"""
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.oauth_tokens import CurrentUserOrMcpRead
from app.core.rate_limit import limit_user
from app.schemas.repayments import CandidatesRequest
from app.services.analytics.common import _today
from app.services.repayment_candidates import repayment_candidates

router = APIRouter(prefix="/repayments", tags=["repayments"])


@router.post("/candidates")
def list_repayment_candidates(body: CandidatesRequest, current_user: CurrentUserOrMcpRead,
                              db: Annotated[Session, Depends(get_db)]) -> dict:
    """Incoming payments that may be repayments, newest first, each with the
    spend it most likely paid back. Read only, despite POST."""
    limit_user("repayment-candidates", current_user.id)
    return {"candidates": repayment_candidates(
        db, current_user, today=_today(), payer=body.payer, about=body.about, spend_date=body.spend_date,
        frm=body.frm, to=body.to, include_marked=body.include_marked, limit=body.limit,
    )}
