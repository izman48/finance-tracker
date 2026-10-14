"""Card statements per credit card (T-10-1, T-10-2): list with the current
position, manual add, edit and delete, and the pick between a manual and a
provider statement for the same period.

Provider rows belong to sync: editing one saves the user's own (manual)
statement for that period, deleting one is 409, and sync never changes a
manual row, so "manual wins" survives the next sync.

Every route loads the card by id AND user (`owned_account`) and each
statement by id AND card AND user, so a foreign or unknown id is the same 404
and nothing is written. Web session only: Claude has no statement tools.
"""
import uuid
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.ownership import owned_account
from app.core.security import CurrentUser
from app.models import (
    Account,
    AccountRole,
    AccountSetting,
    CardStatement,
    CommitmentRule,
    CommitmentStatus,
    StatementSource,
)
from app.schemas.card_statements import (
    CardStatementCreate,
    CardStatementPosition,
    CardStatementResponse,
    CardStatementsResponse,
    CardStatementUpdate,
    NextCardPayment,
    RepaymentWarning,
)
from app.services.analytics.common import _today, account_role
from app.services.analytics.repayment_warnings import card_warnings
from app.services.analytics.repayments import cards_with_linked_bills, repayment_events
from app.services.analytics.statements import check_statement, current_statement, position_for

router = APIRouter(prefix="/analytics/accounts/{account_id}/statements", tags=["card statements"])

MAX_STATEMENTS_LISTED = 24  # two years of monthly statements
NEXT_PAYMENT_REACH = timedelta(days=400)


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
    current = current_statement(statements)
    setting = db.query(AccountSetting).filter(
        AccountSetting.account_id == account.id, AccountSetting.user_id == current_user.id,
    ).first()
    return CardStatementsResponse(
        statements=[CardStatementResponse.model_validate(s) for s in statements],
        current=_position(db, account, current),
        missing_statement=current is not None and current.due_date < _today(),
        conflict=_conflict(statements, current),
        next_payment=_next_payment(db, current_user, account),
        warnings=[RepaymentWarning(**w) for w in card_warnings(db, current_user, account, setting)],
        card_apr=setting.card_apr if setting else None,
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
    _check(merged["statement_balance"], merged["statement_date"], merged["due_date"], merged["minimum_due"],
           new_date=merged["statement_date"] != statement.statement_date)
    if statement.source == StatementSource.PROVIDER.value:
        statement = _manual_for(db, current_user, account, merged["statement_date"])
    for field, value in merged.items():
        setattr(statement, field, value)
    _commit_or_409(db)
    db.refresh(statement)
    return statement


@router.put("/{statement_id}/in-use")
def use_statement(
    account_id: uuid.UUID,
    statement_id: uuid.UUID,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """Use this statement for its period (ux A3). Only the id is sent; it must
    be this user's statement on this card. Choosing the provider's removes
    the user's own statement for that period (manual would win otherwise);
    choosing the user's own changes nothing, since manual already wins."""
    account = owned_account(db, current_user, account_id)
    statement = _owned_statement(db, current_user, account, statement_id)
    if statement.source == StatementSource.PROVIDER.value:
        db.query(CardStatement).filter(
            CardStatement.user_id == current_user.id,
            CardStatement.account_id == account.id,
            CardStatement.statement_date == statement.statement_date,
            CardStatement.source == StatementSource.MANUAL.value,
        ).delete(synchronize_session=False)
        db.commit()
    return {"success": True, "statement_id": str(statement.id)}


@router.delete("/{statement_id}")
def delete_statement(
    account_id: uuid.UUID,
    statement_id: uuid.UUID,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    account = owned_account(db, current_user, account_id)
    statement = _owned_statement(db, current_user, account, statement_id)
    if statement.source == StatementSource.PROVIDER.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This statement comes from your bank and would come back on the next sync. Edit it to use your own figures.",
        )
    db.delete(statement)
    db.commit()
    return {"success": True}


def _owned_credit_account(db: Session, user, account_id: uuid.UUID) -> Account:
    """The caller's account (404 otherwise), which must be a credit account."""
    account = owned_account(db, user, account_id)
    setting = db.query(AccountSetting).filter(
        AccountSetting.account_id == account.id, AccountSetting.user_id == user.id,
    ).first()
    if account_role(account, setting) != AccountRole.CREDIT:
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


def _manual_for(db: Session, user, account: Account, statement_date) -> CardStatement:
    """The user's own statement for this period, new if there is none."""
    manual = db.query(CardStatement).filter(
        CardStatement.user_id == user.id,
        CardStatement.account_id == account.id,
        CardStatement.statement_date == statement_date,
        CardStatement.source == StatementSource.MANUAL.value,
    ).first()
    if manual is None:
        manual = CardStatement(user_id=user.id, account_id=account.id, source=StatementSource.MANUAL.value)
        db.add(manual)
    return manual


def _conflict(statements, current) -> bool:
    """A manual and a provider statement for the current period disagree."""
    if current is None:
        return False
    figures = {
        (s.statement_balance, s.due_date, s.minimum_due)
        for s in statements if s.statement_date == current.statement_date
    }
    return len(figures) > 1


def _check(statement_balance, statement_date, due_date, minimum_due, new_date: bool = True) -> None:
    try:
        check_statement(statement_balance, statement_date, due_date, minimum_due, _today(), new_date=new_date)
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


def _next_payment(db: Session, user, account: Account) -> NextCardPayment | None:
    """The card's first repayment from today, as the summary lists it. None
    while the card has a linked bill, so the sentence never disagrees with
    the forecast (sec, T-10-6)."""
    today = _today()
    events = repayment_events(db, user, today, today + NEXT_PAYMENT_REACH)
    first = next((r for r in events if r["account_id"] == str(account.id)), None)
    if first is None or _card_has_linked_bill(db, user, account, today):
        return None
    setting = db.query(AccountSetting).filter(
        AccountSetting.account_id == account.id, AccountSetting.user_id == user.id,
    ).first()
    pay_from = None
    if setting and setting.pay_from_account_id:
        pay_from = db.query(Account).filter(
            Account.id == setting.pay_from_account_id, Account.user_id == user.id,
        ).first()
    return NextCardPayment(
        amount=first["amount"], date=first["due_date"],
        from_account_name=pay_from.display_name if pay_from else None,
    )


def _card_has_linked_bill(db: Session, user, account: Account, today) -> bool:
    """A confirmed commitment is tied to this card, so the summary and
    forecast may count the bill instead of the repayment, depending on their
    window (eng-b on #182): no single next payment can be promised."""
    confirmed = db.query(CommitmentRule).filter(
        CommitmentRule.user_id == user.id, CommitmentRule.status == CommitmentStatus.CONFIRMED.value,
    ).all()
    return str(account.id) in cards_with_linked_bills(db, user, confirmed, today)


def _position(db: Session, account: Account, statement) -> CardStatementPosition | None:
    if statement is None:
        return None
    position = position_for(db, account, statement)
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
