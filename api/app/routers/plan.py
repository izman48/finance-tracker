"""GET /plan (T-24-4): Cashflow > Plan. Web session only: no MCP tool reads
it (sec), and it takes no user, account or commitment id from the client."""
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.rate_limit import limit_user
from app.core.security import CurrentUser
from app.core.user_crypto import DEKUnavailableError
from app.schemas.plan import PlanResponse
from app.services.plan import plan

logger = logging.getLogger(__name__)
router = APIRouter(tags=["plan"])

PLAN_ERROR = "Couldn't load your plan."


@router.get("/plan", response_model=PlanResponse)
def get_plan(current_user: CurrentUser, db: Annotated[Session, Depends(get_db)]) -> PlanResponse:
    """Income, every commitment and every budget for this pay cycle."""
    limit_user("plan", current_user.id)  # decrypts the cycle's ledger
    try:
        return plan(db, current_user)
    except DEKUnavailableError:
        raise  # 401: sign in again
    except Exception as exc:
        # The type only: a message could carry a label, category or amount.
        logger.error("Plan not built for user %s (%s)", current_user.id, type(exc).__name__)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=PLAN_ERROR) from None
