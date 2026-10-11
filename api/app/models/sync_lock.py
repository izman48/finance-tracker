"""One bank sync per user at a time, across workers (T-08-22, sec).

A lease, not an in-process lock: both uvicorn workers see the same row.
`locked_until` is when a crashed holder's lease lapses; `lock_token` lets
only the holder release it. No user data here, so nothing is encrypted.
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class UserSyncLock(Base):
    __tablename__ = "user_sync_locks"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lock_token: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
