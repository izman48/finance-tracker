"""Holdings, read-only, for Claude and the web (T-11-7; sec T-11-7)."""
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.oauth_tokens import CurrentUserOrMcpRead
from app.schemas.holdings_list import HoldingList
from app.services.holdings.listing import list_holdings

router = APIRouter(prefix="/holdings", tags=["holdings"])


@router.get("", response_model=HoldingList, response_model_by_alias=True)
def get_holdings(current_user: CurrentUserOrMcpRead, db: Annotated[Session, Depends(get_db)]) -> HoldingList:
    """Each holding (at most 100; `truncated` says when there are more):
    value today, growth %, monthly contribution or repayment, whether a bill
    is linked, and the engine's projected values at 1, 5 and 10 years. A
    fixed path with no inputs. Names are the user's text."""
    return HoldingList(**list_holdings(db, current_user))
