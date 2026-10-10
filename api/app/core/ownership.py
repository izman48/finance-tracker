"""Ownership checks for account ids that a request names.

Every route that accepts an account id (in the path or anywhere in the body)
goes through `owned_account`, so the "id AND user_id" filter lives in one
place. A foreign id and an unknown id get the same 404, so the response does
not reveal whether another user's account exists.
"""
import uuid

from fastapi import HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.models import Account

ACCOUNT_ID_SUFFIX = "account_id"


def owned_account(db: Session, user, account_id: uuid.UUID) -> Account:
    """The caller's account with this id, or 404."""
    account = (
        db.query(Account)
        .filter(Account.id == account_id, Account.user_id == user.id)
        .first()
    )
    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")
    return account


def require_owned_account_ids(db: Session, user, body: BaseModel) -> None:
    """404 unless every non-null `*account_id` in the body is the caller's.

    Walks nested models and lists, so a field added later is covered without
    touching the route. Call it before writing anything.
    """
    for account_id in _account_ids(body):
        owned_account(db, user, account_id)


def _account_ids(value) -> list[uuid.UUID]:
    if isinstance(value, BaseModel):
        found: list[uuid.UUID] = []
        for name in type(value).model_fields:
            field_value = getattr(value, name)
            if name.endswith(ACCOUNT_ID_SUFFIX) and field_value is not None:
                found.append(field_value)
            else:
                found.extend(_account_ids(field_value))
        return found
    if isinstance(value, (list, tuple)):
        return [account_id for item in value for account_id in _account_ids(item)]
    return []
