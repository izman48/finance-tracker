"""Card statements per credit card (T-10-1): list with the current position,
manual add, edit and delete.

Every route loads the card by id AND user (`owned_account`) and each
statement by id AND card AND user, so a foreign or unknown id is the same 404
and nothing is written. Web session only: Claude has no statement tools.
"""
import uuid
from datetime import datetime, time, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.ownership import owned_account
from app.core.security import CurrentUser
from app.models import Account, AccountRole, AccountSetting, CardStatement, StatementSource, Transaction
from app.schemas.card_statements import (
    CardStatementCreate,
    CardStatementPosition,
    CardStatementResponse,
    CardStatementsResponse,
    CardStatementUpdate,
)
from app.services.analytics.common import _today, default_role
from app.services.analytics.statements import check_statement, current_statement, statement_position
from app.services.balance_sign import credit_owed

router = APIRouter(prefix="/analytics/accounts/{account_id}/statements", tags=["card statements"])

MAX_STATEMENTS_LISTED = 24  # two years of monthly statements


@router.get("", response_model=CardStatementsResponse)
def list_statements(
    account_id: uuid.UUID,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> CardStatementsResponse:
    account = owned_account(db, current_user, account_id)
    statements = (
        db.query(CardStatement)
        .filter(CardStatement.account_id == account.id, CardStatement.user_id == current_user.id)
        .order_by(CardStatement.statement_date.desc(), CardStatement.source)
        .limit(MAX_STATEMENTS_LISTED)
        .all()
    )
    return CardStatementsResponse(
        statements=[CardStatementResponse.model_validate(s) for s in statements],
        current=_position(db, account, current_statement(statements)),
    )


@router.post("", response_model=CardStatementResponse, status_code=status.HTTP_201_CREATED)
def add_statement(
    account_id: uuid.UUID,
    data: CardStatementCreate,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> CardStatement:
    account = _owned_credit_account(db, current_user, account_id)
    _check(data.statement_balance, data.statement_date, data.due_date, data.minimum_due)
    statement = CardStatement(
        user_id=current_user.id, account_id=account.id, source=StatementSource.MANUAL.value,
        **data.model_dump(),
    )
    db.add(statement)
    _commit_or_409(db)
    db.refresh(statement)
    return statement


@router.patch("/{statement_id}", response_model=CardStatementResponse)
def update_statement(
    account_id: uuid.UUID,
    statement_id: uuid.UUID,
    data: CardStatementUpdate,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> CardStatement:
    account = _owned_credit_account(db, current_user, account_id)
    statement = _owned_statement(db, current_user, account, statement_id)
    merged = {
        "statement_balance": statement.statement_balance,
        "statement_date": statement.statement_date,
        "due_date": statement.due_date,
        "minimum_due": statement.minimum_due,
        **data.model_dump(exclude_unset=True),
    }
    if merged["statement_balance"] is None:
        raise HTTPException(status_code=422, detail="A statement needs a balance.")
    if merged["statement_date"] is None or merged["due_date"] is None:
        raise HTTPException(status_code=422, detail="A statement needs a statement date and a due date.")
    _check(merged["statement_balance"], merged["statement_date"], merged["due_date"], merged["minimum_due"])
    for field, value in merged.items():
        setattr(statement, field, value)
    _commit_or_409(db)
    db.refresh(statement)
    return statement


@router.delete("/{statement_id}")
def delete_statement(
    account_id: uuid.UUID,
    statement_id: uuid.UUID,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    account = owned_account(db, current_user, account_id)
    db.delete(_owned_statement(db, current_user, account, statement_id))
    db.commit()
    return {"success": True}


def _owned_credit_account(db: Session, user, account_id: uuid.UUID) -> Account:
    """The caller's account (404 otherwise), which must be a credit account."""
    account = owned_account(db, user, account_id)
    setting = db.query(AccountSetting).filter(
        AccountSetting.account_id == account.id, AccountSetting.user_id == user.id,
    ).first()
    role = AccountRole(setting.role) if setting else default_role(account)
    if role != AccountRole.CREDIT:
        raise HTTPException(status_code=422, detail="Statements are only for credit cards.")
    return account


def _owned_statement(db: Session, user, account: Account, statement_id: uuid.UUID) -> CardStatement:
    statement = db.query(CardStatement).filter(
        CardStatement.id == statement_id,
        CardStatement.account_id == account.id,
        CardStatement.user_id == user.id,
    ).first()
    if not statement:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Statement not found")
    return statement


def _check(statement_balance, statement_date, due_date, minimum_due) -> None:
    try:
        check_statement(statement_balance, statement_date, due_date, minimum_due, _today())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


def _commit_or_409(db: Session) -> None:
    """One manual statement per card per statement date (DB constraint)."""
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You already have a statement for that date. Edit it instead.",
        ) from None


def _position(db: Session, account: Account, statement) -> CardStatementPosition | None:
    if statement is None:
        return None
    after = datetime.combine(statement.statement_date + timedelta(days=1), time.min, tzinfo=timezone.utc)
    card_transactions = db.query(Transaction).filter(
        Transaction.account_id == account.id, Transaction.transaction_date >= after,
    ).all()
    position = statement_position(statement, credit_owed(account), card_transactions)
    return CardStatementPosition(
        statement_id=statement.id,
        source=statement.source,
        statement_balance=statement.statement_balance,
        statement_date=statement.statement_date,
        due_date=statement.due_date,
        minimum_due=statement.minimum_due,
        payments_since_statement=position.payments_since_statement,
        amount_still_due=position.amount_still_due,
        unbilled=position.unbilled,
        paid=position.paid,
    )
