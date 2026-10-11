"""At most one bank sync per user at a time, across workers (T-08-22, sec).

TrueLayer rotates a refresh token on use, so two concurrent refreshes of one
connection race and the loser's token is rejected. A lease row per user in
the database (`user_sync_locks`) makes the second sync wait its turn: it is
taken with one conditional UPDATE, so two workers can't both win, and it
lapses after LEASE so a crashed worker can't block syncing for good.
"""
from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Iterator

from sqlalchemy import or_, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import UserSyncLock

LEASE = timedelta(minutes=5)
RETRY_AFTER_SECONDS = 30


class SyncBusy(Exception):
    """Another sync for this user holds the lease."""


def acquire(db: Session, user_id: uuid.UUID, now: datetime | None = None) -> uuid.UUID | None:
    """Take the user's lease and commit; its token, or None if it's held."""
    now = now or datetime.now(timezone.utc)
    _ensure_row(db, user_id)
    token = uuid.uuid4()
    taken = db.execute(
        update(UserSyncLock)
        .where(
            UserSyncLock.user_id == user_id,
            or_(UserSyncLock.locked_until.is_(None), UserSyncLock.locked_until < now),
        )
        .values(locked_until=now + LEASE, lock_token=token)
        .execution_options(synchronize_session=False)
    ).rowcount
    db.commit()
    return token if taken == 1 else None


def release(db: Session, user_id: uuid.UUID, token: uuid.UUID) -> None:
    """Give the lease back, if this holder still has it.

    This rolls the session back first: a failed or cut-off sync may have
    left it mid-transaction, and that uncommitted work is discarded, never
    committed with the release. A sync commits what it means to keep as it
    goes, so nothing it finished is lost."""
    db.rollback()
    db.execute(
        update(UserSyncLock)
        .where(UserSyncLock.user_id == user_id, UserSyncLock.lock_token == token)
        .values(locked_until=None, lock_token=None)
        .execution_options(synchronize_session=False)
    )
    db.commit()


@contextmanager
def sync_lease(db: Session, user_id: uuid.UUID) -> Iterator[None]:
    token = acquire(db, user_id)
    if token is None:
        raise SyncBusy()
    try:
        yield
    finally:
        release(db, user_id, token)


def _ensure_row(db: Session, user_id: uuid.UUID) -> None:
    if db.get(UserSyncLock, user_id) is not None:
        return
    db.add(UserSyncLock(user_id=user_id))
    try:
        db.commit()
    except IntegrityError:  # another worker made it first
        db.rollback()
